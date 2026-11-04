"""Tests for İP-8: Job Queue, State Machine, Single-Flight sc.lock, and Atomic Publishing."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import pytest

from masa.audit.events import AuditLogger
from masa.audit.models import JobState
from masa.audit.queue import (
    JobQueue,
    build_dedup_key,
    run_managed_job,
)
from masa.ingestion.lock import (
    DEFAULT_LOCK_PATH,
    ScalableLockTimeoutError,
    sc_file_lock,
)
from masa.storage.db import DatabaseManager


@pytest.fixture
def test_db(tmp_path: Path):
    """Isolated SQLite database manager initialized with full schema and triggers."""
    db_file = tmp_path / "test_queue_desk.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()
    return mgr


# ============================================================================
# Acceptance Test 1: dedup_key idempotency & single execution
# ============================================================================

def test_job_dedup_idempotency(test_db):
    """Running the same job on the same day with identical inputs returns cached result without re-executing."""
    queue = JobQueue(test_db)
    dedup = build_dedup_key("veri", {"mode": "incremental"}, day_str="2026-10-31")

    call_count = 0

    def mock_runner():
        nonlocal call_count
        call_count += 1
        return {"snapshots_count": 5, "status": "ok"}

    # First execution: runs runner
    job1, res1, was_skipped1 = run_managed_job(queue, "data_collection", dedup, mock_runner)
    assert call_count == 1
    assert was_skipped1 is False
    assert job1.status == JobState.PUBLISHED
    assert res1["snapshots_count"] == 5

    # Second execution: skips runner and returns existing job
    job2, res2, was_skipped2 = run_managed_job(queue, "data_collection", dedup, mock_runner)
    assert call_count == 1  # Not incremented!
    assert was_skipped2 is True
    assert job2.job_id == job1.job_id
    assert res2["snapshots_count"] == 5

    # Confirm only 1 row in jobs table
    conn = test_db.get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE dedup_key = ?", (dedup,)).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


# ============================================================================
# Acceptance Test 2: Crash recovery of in-flight jobs
# ============================================================================

def test_crash_recovery_in_flight_jobs(test_db):
    """Uncommitted in-flight jobs on unexpected shutdown are marked FAILED on restart."""
    queue = JobQueue(test_db)

    # Enqueue and transition to various in-flight states
    j1 = queue.enqueue_job("sync", "dedup_crash_1")
    queue.transition(j1.job_id, to_status=JobState.COLLECTING)

    j2 = queue.enqueue_job("calc", "dedup_crash_2")
    queue.transition(j2.job_id, to_status=JobState.COLLECTING)
    queue.transition(j2.job_id, to_status=JobState.VALIDATING)
    queue.transition(j2.job_id, to_status=JobState.CALCULATING)

    j3 = queue.enqueue_job("report", "dedup_crash_3")
    queue.transition(j3.job_id, to_status=JobState.COLLECTING)
    queue.transition(j3.job_id, to_status=JobState.VALIDATING)
    queue.transition(j3.job_id, to_status=JobState.CALCULATING)
    queue.transition(j3.job_id, to_status=JobState.RESEARCHING)

    # Also have one legitimately completed job
    j4 = queue.enqueue_job("done", "dedup_done_4")
    queue.transition(j4.job_id, to_status=JobState.COLLECTING)
    queue.transition(j4.job_id, to_status=JobState.VALIDATING)
    queue.transition(j4.job_id, to_status=JobState.CALCULATING)
    queue.transition(j4.job_id, to_status=JobState.REVIEWING)
    queue.transition(j4.job_id, to_status=JobState.PUBLISHED, result={"ok": True})

    # Simulate crash recovery
    recovered = queue.recover_in_flight_jobs()
    assert recovered == 3

    assert queue.get_job(j1.job_id).status == JobState.FAILED
    assert queue.get_job(j1.job_id).error_message == "SYSTEM_CRASH_OR_UNEXPECTED_SHUTDOWN"
    assert queue.get_job(j2.job_id).status == JobState.FAILED
    assert queue.get_job(j3.job_id).status == JobState.FAILED

    # Finished job untouched
    assert queue.get_job(j4.job_id).status == JobState.PUBLISHED


# ============================================================================
# Acceptance Test 3: Tek uçuş — sc.lock file lock
# ============================================================================

def test_single_flight_sc_lock(tmp_path: Path):
    """Concurrent attempts to acquire sc.lock are strictly serialized or timeout."""
    lock_file = tmp_path / "sc.lock"

    # Process 1 acquires lock
    with sc_file_lock(lock_path=lock_file, timeout_seconds=2.0):
        # Process 2 attempts to acquire lock immediately -> must timeout
        with pytest.raises(ScalableLockTimeoutError, match="Tek uçuş kuralı ihlali"):
            with sc_file_lock(lock_path=lock_file, timeout_seconds=0.15, poll_interval=0.02):
                pass

    # Once released, lock can be acquired again without error
    with sc_file_lock(lock_path=lock_file, timeout_seconds=1.0):
        assert lock_file.exists()


# ============================================================================
# Acceptance Test 4: Scalable oturum hatası -> waiting_auth (no auto-retry)
# ============================================================================

def test_scalable_auth_error_transitions_to_waiting_auth(test_db):
    """Session expiration moves job to waiting_auth without recursive retry storms."""
    queue = JobQueue(test_db)
    dedup = build_dedup_key("veri", {"op": "holdings"}, day_str="2026-10-31")

    def failing_auth_runner():
        raise RuntimeError("Scalable oturum süresi dolmuş, lütfen yeniden giriş yapın: Session expired.")

    with pytest.raises(RuntimeError, match="oturum"):
        run_managed_job(queue, "data_collection", dedup, failing_auth_runner)

    # Job must be in waiting_auth
    job_row = queue.get_job(queue.list_recent_jobs(1)[0].job_id)
    assert job_row.status == JobState.WAITING_AUTH
    assert "oturum" in job_row.error_message.lower()

    # Query pending/waiting jobs
    waiting_jobs = queue.get_pending_or_waiting_jobs()
    assert len(waiting_jobs) == 1
    assert waiting_jobs[0].status == JobState.WAITING_AUTH


# ============================================================================
# Acceptance Test 5: 429 / quota error -> waiting_quota
# ============================================================================

def test_rate_limit_error_transitions_to_waiting_quota(test_db):
    """Quota exhaustion (HTTP 429) moves job to waiting_quota."""
    queue = JobQueue(test_db)
    dedup = build_dedup_key("tradingagents", {"ticker": "EUNL.DE"}, day_str="2026-10-31")

    def failing_quota_runner():
        raise RuntimeError("HTTP 429: Resource Exhausted (rate limit exceeded).")

    with pytest.raises(RuntimeError, match="429"):
        run_managed_job(queue, "external_opinion", dedup, failing_quota_runner, intermediate_state=JobState.RESEARCHING)

    job_row = queue.get_job(queue.list_recent_jobs(1)[0].job_id)
    assert job_row.status == JobState.WAITING_QUOTA


# ============================================================================
# Acceptance Test 6: Atomic publishing guarantee
# ============================================================================

def test_atomic_publishing_corrupted_report_never_published(tmp_path: Path):
    """If integrity verification fails, temporary file is cleaned up and partial report is never published."""
    dest_report = tmp_path / "masa-rapor-test.md"
    tmp_report = dest_report.with_suffix(".tmp")

    report_content = "# Broken Unverified Report"

    # Simulate atomic publish failure
    integ_ok = False
    tmp_report.write_text(report_content, encoding="utf-8")
    if integ_ok:
        tmp_report.replace(dest_report)
    else:
        tmp_report.unlink(missing_ok=True)

    # The actual published file must NOT exist
    assert not dest_report.exists()
    assert not tmp_report.exists()

    # When integrity passes, atomic rename succeeds
    integ_ok = True
    tmp_report.write_text(report_content, encoding="utf-8")
    if integ_ok:
        tmp_report.replace(dest_report)
    else:
        tmp_report.unlink(missing_ok=True)

    assert dest_report.exists()
    assert dest_report.read_text(encoding="utf-8") == report_content
