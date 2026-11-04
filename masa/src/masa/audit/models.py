"""Audit and work queue data contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class JobState(str, Enum):
    """Finite state machine states for the ETF Desk work queue."""
    QUEUED = "queued"
    COLLECTING = "collecting"
    VALIDATING = "validating"
    CALCULATING = "calculating"
    RESEARCHING = "researching"
    REVIEWING = "reviewing"
    PUBLISHED = "published"
    WAITING_AUTH = "waiting_auth"
    WAITING_QUOTA = "waiting_quota"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRecord(BaseModel):
    """Representation of an operational job."""
    model_config = ConfigDict(frozen=True)

    job_id: str
    job_type: str
    status: JobState
    dedup_key: str
    params: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AuditEvent(BaseModel):
    """Cryptographic audit event representation."""
    model_config = ConfigDict(frozen=True)

    event_id: int
    event_uuid: str
    event_time: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload_json: str
    payload_sha256: str
    prev_hash: str
    curr_hash: str
