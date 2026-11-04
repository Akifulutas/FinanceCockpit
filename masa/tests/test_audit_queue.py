"""Tests for work queue state machine, dedup_key idempotency, and crash recovery."""

from pathlib import Path
import pytest

from masa.audit import (
    AuditLogger,
    InvalidStateTransitionError,
    JobQueue,
    JobState,
    JobStateError,
    WorkQueue,
)
from masa.storage import DatabaseManager, get_database_connection


class TestWorkQueueStateMachine:
    """Verify state transitions, idempotency, and crash recovery."""

    def test_dedup_key_prevents_duplicate_job_insertion(self, tmp_path: Path) -> None:
        conn = get_database_connection(tmp_path / "queue.db")
        queue = WorkQueue(conn)

        job1 = queue.enqueue_job(job_type="daily_snapshot", dedup_key="2026-10-30:daily_snapshot")
        assert job1.status == "queued"
        assert job1.status == JobState.QUEUED

        # Enqueueing same dedup_key should return existing job
        existing = queue.enqueue_job(job_type="daily_snapshot", dedup_key="2026-10-30:daily_snapshot")
        assert existing.job_id == job1.job_id
        assert existing.status == JobState.QUEUED

    def test_valid_state_transitions_full_lifecycle(self, tmp_path: Path) -> None:
        mgr = DatabaseManager(tmp_path / "lifecycle.db")
        mgr.initialize_schema()
        audit = AuditLogger(mgr)
        queue = JobQueue(mgr, audit_logger=audit)

        job = queue.enqueue_job(job_type="portfolio_sync", dedup_key="job_trans_1")
        assert job.status == JobState.QUEUED

        # 1. queued -> collecting
        queue.transition(job.job_id, to_status="collecting")
        updated = queue.get_job(job.job_id)
        assert updated is not None
        assert updated.status == JobState.COLLECTING
        assert updated.started_at is not None

        # 2. collecting -> validating
        queue.transition(job.job_id, to_status=JobState.VALIDATING)
        assert queue.get_job(job.job_id).status == JobState.VALIDATING

        # 3. validating -> calculating
        queue.transition(job.job_id, to_status="calculating")
        assert queue.get_job(job.job_id).status == JobState.CALCULATING

        # 4. calculating -> reviewing
        queue.transition(job.job_id, to_status="reviewing")
        assert queue.get_job(job.job_id).status == JobState.REVIEWING

        # 5. reviewing -> published
        res = {"total_eur": "15000.00", "valid_count": 5}
        queue.transition(job.job_id, to_status="published", result=res)
        final_job = queue.get_job(job.job_id)
        assert final_job is not None
        assert final_job.status == JobState.PUBLISHED
        assert final_job.result == res
        assert final_job.completed_at is not None

        # Audit ledger must be cryptographically sound
        valid, err = audit.verify_integrity()
        assert valid is True
        assert err is None

    def test_invalid_state_transitions_fail(self, tmp_path: Path) -> None:
        conn = get_database_connection(tmp_path / "invalid.db")
        queue = WorkQueue(conn)

        job = queue.enqueue_job(job_type="daily_snapshot", dedup_key="job_invalid_1")

        # Direct jump from queued to published is strictly prohibited
        with pytest.raises((JobStateError, InvalidStateTransitionError)):
            queue.transition(job.job_id, to_status="published")

        # Direct jump from queued to calculating is prohibited
        with pytest.raises((JobStateError, InvalidStateTransitionError)):
            queue.transition(job.job_id, to_status="calculating")

        # Transition to collecting, then attempt invalid jump to published
        queue.transition(job.job_id, to_status="collecting")
        with pytest.raises((JobStateError, InvalidStateTransitionError)):
            queue.transition(job.job_id, to_status="published")

    def test_crash_recovery_of_in_flight_jobs(self, tmp_path: Path) -> None:
        mgr = DatabaseManager(tmp_path / "recovery.db")
        mgr.initialize_schema()
        audit = AuditLogger(mgr)
        queue = JobQueue(mgr, audit_logger=audit)

        # Enqueue and move jobs to various in-flight states
        j1 = queue.enqueue_job("type1", "dedup1")
        queue.transition(j1.job_id, to_status="collecting")

        j2 = queue.enqueue_job("type2", "dedup2")
        queue.transition(j2.job_id, to_status="collecting")
        queue.transition(j2.job_id, to_status="validating")

        j3 = queue.enqueue_job("type3", "dedup3")
        queue.transition(j3.job_id, to_status="collecting")
        queue.transition(j3.job_id, to_status="validating")
        queue.transition(j3.job_id, to_status="calculating")

        # Terminal and queued jobs that should NOT be affected
        j_queued = queue.enqueue_job("type_q", "dedup_q")

        j_pub = queue.enqueue_job("type_p", "dedup_p")
        queue.transition(j_pub.job_id, to_status="collecting")
        queue.transition(j_pub.job_id, to_status="validating")
        queue.transition(j_pub.job_id, to_status="calculating")
        queue.transition(j_pub.job_id, to_status="reviewing")
        queue.transition(j_pub.job_id, to_status="published")

        # Perform recovery
        recovered_count = queue.recover_in_flight_jobs()
        assert recovered_count == 3

        # Verify in-flight jobs are now failed with error message
        rec1 = queue.get_job(j1.job_id)
        assert rec1.status == JobState.FAILED
        assert rec1.error_message == "SYSTEM_CRASH_OR_UNEXPECTED_SHUTDOWN"
        assert rec1.completed_at is not None

        rec2 = queue.get_job(j2.job_id)
        assert rec2.status == JobState.FAILED

        rec3 = queue.get_job(j3.job_id)
        assert rec3.status == JobState.FAILED

        # Queued job remains queued
        assert queue.get_job(j_queued.job_id).status == JobState.QUEUED

        # Published job remains published
        assert queue.get_job(j_pub.job_id).status == JobState.PUBLISHED

        # Audit ledger remains cryptographically valid after recovery
        valid, err = audit.verify_integrity()
        assert valid is True
        assert err is None
