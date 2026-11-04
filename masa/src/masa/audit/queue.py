"""Work queue and state machine (JobQueue / WorkQueue).

Manages idempotent task dispatching, transitions, crash recovery, and audit tracking.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, Generator, Optional, Set, Tuple, Union
import uuid

from masa.audit.events import AuditLogger
from masa.audit.models import JobRecord, JobState
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import canonical_json

VALID_TRANSITIONS: Dict[JobState, Set[JobState]] = {
    JobState.QUEUED: {JobState.COLLECTING, JobState.CANCELLED},
    JobState.COLLECTING: {JobState.VALIDATING, JobState.WAITING_AUTH, JobState.FAILED, JobState.CANCELLED},
    JobState.VALIDATING: {JobState.CALCULATING, JobState.NEEDS_REVIEW, JobState.FAILED, JobState.CANCELLED},
    JobState.CALCULATING: {JobState.RESEARCHING, JobState.REVIEWING, JobState.NEEDS_REVIEW, JobState.FAILED, JobState.CANCELLED},
    JobState.RESEARCHING: {JobState.REVIEWING, JobState.WAITING_QUOTA, JobState.FAILED, JobState.CANCELLED},
    JobState.REVIEWING: {JobState.PUBLISHED, JobState.NEEDS_REVIEW, JobState.FAILED, JobState.CANCELLED},
    JobState.WAITING_AUTH: {JobState.COLLECTING, JobState.FAILED, JobState.CANCELLED},
    JobState.WAITING_QUOTA: {JobState.RESEARCHING, JobState.FAILED, JobState.CANCELLED},
    JobState.NEEDS_REVIEW: {JobState.COLLECTING, JobState.VALIDATING, JobState.CALCULATING, JobState.PUBLISHED, JobState.CANCELLED},
    JobState.PUBLISHED: set(),  # Terminal
    JobState.FAILED: {JobState.QUEUED},  # Permitted for retry
    JobState.CANCELLED: set(),  # Terminal
}


class InvalidStateTransitionError(Exception):
    """Raised when an illegal transition in the job state machine is attempted."""
    pass


# Compatibility alias
JobStateError = InvalidStateTransitionError


class JobQueue:
    """Finite state machine work queue backed by SQLite."""

    def __init__(
        self,
        db: Union[DatabaseManager, sqlite3.Connection],
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self.db = db
        self.audit = audit_logger or AuditLogger(db)

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        if hasattr(self.db, "transaction"):
            with self.db.transaction() as conn:
                yield conn
        else:
            try:
                yield self.db
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def enqueue(
        self,
        job_type: str,
        dedup_key: str,
        params: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Enqueue a new job with dedup_key idempotency."""
        jid = job_id or f"job_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        params_dict = params or {}
        params_json = canonical_json(params_dict)

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE dedup_key = ?", (dedup_key,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing), False

            cursor.execute(
                """INSERT INTO jobs (job_id, job_type, status, dedup_key, params_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (jid, job_type, JobState.QUEUED.value, dedup_key, params_json, now_iso),
            )

        self.audit.log_event(
            actor="queue_worker",
            action="JOB_ENQUEUED",
            entity_type="job",
            entity_id=jid,
            payload={"job_type": job_type, "dedup_key": dedup_key},
        )
        return {
            "job_id": jid,
            "job_type": job_type,
            "status": JobState.QUEUED.value,
            "dedup_key": dedup_key,
            "params": params_dict,
            "created_at": now_iso,
        }, True

    def enqueue_job(
        self,
        job_type: str,
        dedup_key: str,
        params: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
    ) -> JobRecord:
        """Compatibility method returning a JobRecord model."""
        res_dict, _ = self.enqueue(job_type, dedup_key, params=params, job_id=job_id)
        return self.get_job(res_dict["job_id"])  # type: ignore

    def transition(
        self,
        job_id: str,
        to_state: Optional[Union[JobState, str]] = None,
        to_status: Optional[Union[JobState, str]] = None,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Safely advance job state, enforcing state transition matrix and audit logging."""
        target_raw = to_state if to_state is not None else to_status
        if target_raw is None:
            raise ValueError("Target state must be provided via 'to_state' or 'to_status'")

        if isinstance(target_raw, JobState):
            target_state = target_raw
        else:
            target_state = JobState(str(target_raw).lower())
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Job not found: {job_id}")

            current_state = JobState(row["status"])
            if target_state not in VALID_TRANSITIONS.get(current_state, set()):
                raise InvalidStateTransitionError(
                    f"Invalid state transition: '{current_state.value}' -> '{target_state.value}'"
                )

            started_at = row["started_at"]
            if current_state == JobState.QUEUED and target_state == JobState.COLLECTING:
                started_at = now_iso

            completed_at = row["completed_at"]
            if target_state in {JobState.PUBLISHED, JobState.FAILED, JobState.CANCELLED}:
                completed_at = now_iso

            result_json = canonical_json(result) if result is not None else row["result_json"]
            err_msg = error_message or row["error_message"]

            cursor.execute(
                """UPDATE jobs
                   SET status = ?, result_json = ?, error_message = ?, started_at = ?, completed_at = ?
                   WHERE job_id = ?""",
                (target_state.value, result_json, err_msg, started_at, completed_at, job_id),
            )

        self.audit.log_event(
            actor="queue_worker",
            action="JOB_STATE_TRANSITION",
            entity_type="job",
            entity_id=job_id,
            payload={
                "from_state": current_state.value,
                "to_state": target_state.value,
                "error": error_message,
            },
        )
        return {"job_id": job_id, "status": target_state.value, "error_message": err_msg}

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve job record by ID."""
        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None

            params = {}
            if row["params_json"]:
                try:
                    params = json.loads(row["params_json"])
                except Exception:
                    pass

            result = None
            if row["result_json"]:
                try:
                    result = json.loads(row["result_json"])
                except Exception:
                    pass

            return JobRecord(
                job_id=row["job_id"],
                job_type=row["job_type"],
                status=JobState(row["status"]),
                dedup_key=row["dedup_key"],
                params=params,
                result=result,
                error_message=row["error_message"],
                retry_count=row["retry_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
                started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            )

    def recover_in_flight_jobs(self) -> int:
        """Mark uncommitted in-flight jobs as failed on restart and log audit events."""
        in_flight_states = [
            JobState.COLLECTING.value,
            JobState.VALIDATING.value,
            JobState.CALCULATING.value,
            JobState.RESEARCHING.value,
            JobState.REVIEWING.value,
        ]
        placeholders = ",".join("?" for _ in in_flight_states)
        now_iso = datetime.now(timezone.utc).isoformat()
        recovered_count = 0

        recovered_jobs: List[Tuple[str, str]] = []
        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT job_id, status FROM jobs WHERE status IN ({placeholders})", in_flight_states)
            rows = cursor.fetchall()

            for row in rows:
                jid = row["job_id"]
                cursor.execute(
                    """UPDATE jobs
                       SET status = ?, error_message = ?, completed_at = ?
                       WHERE job_id = ?""",
                    (JobState.FAILED.value, "SYSTEM_CRASH_OR_UNEXPECTED_SHUTDOWN", now_iso, jid),
                )
                recovered_jobs.append((jid, row["status"]))

        for jid, prev_status in recovered_jobs:
            self.audit.log_event(
                actor="queue_recovery",
                action="JOB_RECOVERED_AFTER_CRASH",
                entity_type="job",
                entity_id=jid,
                payload={"previous_status": prev_status},
            )

        return len(recovered_jobs)

    def advance_to_published(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Safely advance from any in-flight state through valid transitions to PUBLISHED."""
        current = self.get_job(job_id)
        if not current:
            raise ValueError(f"Job not found: {job_id}")

        state = current.status
        if state == JobState.COLLECTING:
            self.transition(job_id, to_status=JobState.VALIDATING)
            state = JobState.VALIDATING
        if state == JobState.VALIDATING:
            self.transition(job_id, to_status=JobState.CALCULATING)
            state = JobState.CALCULATING
        if state == JobState.CALCULATING:
            self.transition(job_id, to_status=JobState.REVIEWING)
            state = JobState.REVIEWING
        if state == JobState.RESEARCHING:
            self.transition(job_id, to_status=JobState.REVIEWING)
            state = JobState.REVIEWING
        if state in (JobState.REVIEWING, JobState.NEEDS_REVIEW):
            return self.transition(job_id, to_status=JobState.PUBLISHED, result=result)

        return self.transition(job_id, to_status=JobState.PUBLISHED, result=result)

    def list_recent_jobs(self, limit: int = 20) -> List[JobRecord]:
        """List recent jobs ordered by created_at DESC."""
        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            result = []
            for row in rows:
                params = {}
                if row["params_json"]:
                    try:
                        params = json.loads(row["params_json"])
                    except Exception:
                        pass
                res_json = None
                if row["result_json"]:
                    try:
                        res_json = json.loads(row["result_json"])
                    except Exception:
                        pass
                result.append(
                    JobRecord(
                        job_id=row["job_id"],
                        job_type=row["job_type"],
                        status=JobState(row["status"]),
                        dedup_key=row["dedup_key"],
                        params=params,
                        result=res_json,
                        error_message=row["error_message"],
                        retry_count=row["retry_count"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    )
                )
            return result

    def get_pending_or_waiting_jobs(self) -> List[JobRecord]:
        """Fetch jobs requiring user action (waiting_auth, waiting_quota) or currently in-flight."""
        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM jobs
                   WHERE status IN ('waiting_auth', 'waiting_quota', 'collecting', 'validating',
                                    'calculating', 'researching', 'reviewing', 'queued')
                   ORDER BY created_at DESC"""
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                params = {}
                if row["params_json"]:
                    try:
                        params = json.loads(row["params_json"])
                    except Exception:
                        pass
                res_json = None
                if row["result_json"]:
                    try:
                        res_json = json.loads(row["result_json"])
                    except Exception:
                        pass
                result.append(
                    JobRecord(
                        job_id=row["job_id"],
                        job_type=row["job_type"],
                        status=JobState(row["status"]),
                        dedup_key=row["dedup_key"],
                        params=params,
                        result=res_json,
                        error_message=row["error_message"],
                        retry_count=row["retry_count"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    )
                )
            return result


def build_dedup_key(
    command: str,
    inputs: Optional[Dict[str, Any]] = None,
    day_str: Optional[str] = None,
) -> str:
    """Generate dedup_key = command + input_summary + day."""
    import hashlib
    day = day_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    inp_json = canonical_json(inputs or {})
    inp_hash = hashlib.sha256(inp_json.encode("utf-8")).hexdigest()[:12]
    return f"{command.lower().strip()}:{inp_hash}:{day}"


def run_managed_job(
    queue: JobQueue,
    job_type: str,
    dedup_key: str,
    runner_fn: Any,
    params: Optional[Dict[str, Any]] = None,
    intermediate_state: JobState = JobState.COLLECTING,
    allow_skip_if_published: bool = True,
) -> Tuple[JobRecord, Any, bool]:
    """Execute a task wrapped in the JobQueue state machine with dedup and error handling.
    
    Guarantees:
    - If job already exists and is PUBLISHED, returns (existing_job, cached_result, True).
    - If Scalable session expired, transitions to WAITING_AUTH without automatic retry loop.
    - If rate limit (429 / quota), transitions to WAITING_QUOTA.
    - If unexpected failure, transitions to FAILED.
    - On success, transitions through to PUBLISHED.
    """
    res_dict, created = queue.enqueue(job_type, dedup_key, params=params)
    job_id = res_dict["job_id"]
    current_job = queue.get_job(job_id)

    if not created and current_job and current_job.status == JobState.PUBLISHED and allow_skip_if_published:
        return current_job, current_job.result, True

    # Transition to intermediate state
    queue.transition(job_id, to_status=JobState.COLLECTING)
    if intermediate_state in (JobState.VALIDATING, JobState.CALCULATING, JobState.RESEARCHING, JobState.REVIEWING):
        queue.transition(job_id, to_status=JobState.VALIDATING)
        if intermediate_state in (JobState.CALCULATING, JobState.RESEARCHING, JobState.REVIEWING):
            queue.transition(job_id, to_status=JobState.CALCULATING)
            if intermediate_state in (JobState.RESEARCHING, JobState.REVIEWING):
                queue.transition(job_id, to_status=intermediate_state)

    try:
        outcome = runner_fn()
        queue.advance_to_published(job_id, result=outcome if isinstance(outcome, dict) else {"outcome": str(outcome)})
        final_job = queue.get_job(job_id)
        return final_job, outcome, False
    except Exception as exc:
        err_str = str(exc).lower()
        if any(w in err_str for w in ("oturum", "login", "auth", "yetki", "unauthorized", "session")):
            queue.transition(job_id, to_status=JobState.WAITING_AUTH, error_message=str(exc))
        elif any(w in err_str for w in ("429", "rate limit", "quota", "resource_exhausted", "too many requests")):
            queue.transition(job_id, to_status=JobState.WAITING_QUOTA, error_message=str(exc))
        else:
            queue.transition(job_id, to_status=JobState.FAILED, error_message=str(exc))
        raise


# Compatibility alias
WorkQueue = JobQueue
