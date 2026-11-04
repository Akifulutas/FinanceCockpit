"""Pydantic v2 domain models for Model Registry, Evaluations, and Execution Manifests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
from typing import Any, Dict, List, Mapping, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from masa.storage.hash_chain import (
    compute_model_evaluation_hash,
    compute_model_registry_hash,
    compute_model_run_hash,
)


class ModelAccessTier(str, Enum):
    SUBSCRIPTION = "subscription"
    FREE = "free"
    LOCAL = "local"


class ModelPrivacyClass(str, Enum):
    CONFIDENTIAL_ANONYMIZED = "confidential_anonymized"
    PUBLIC_DATA_ONLY = "public_data_only"


class ModelStatus(str, Enum):
    DISCOVERED = "discovered"
    ACCESS_VERIFIED = "access_verified"
    EVALUATED = "evaluated"
    ELIGIBLE = "eligible"
    PAUSED = "paused"
    REVOKED = "revoked"


class TaskCategory(str, Enum):
    TABLE_EXTRACTION = "table_extraction"
    CLAIM_SOURCE_MATCHING = "claim_source_matching"
    FLAWED_REPORT_DETECTION = "flawed_report_detection"
    TURKISH_SEMANTICS = "turkish_semantics"


class ModelRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_QUOTA = "waiting_quota"
    FAILED = "failed"


class ModelRecord(BaseModel):
    """Pydantic v2 model representing an immutable model registry entry."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    provider: str
    model_name: str
    access_tier: ModelAccessTier
    region_compliance: str = "EU_COMPLIANT"
    quota_info: Optional[str] = None
    privacy_class: ModelPrivacyClass = ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED
    status: ModelStatus = ModelStatus.DISCOVERED
    last_verified_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "model_name": self.model_name,
            "access_tier": self.access_tier.value if isinstance(self.access_tier, ModelAccessTier) else str(self.access_tier),
            "region_compliance": self.region_compliance,
            "quota_info": self.quota_info,
            "privacy_class": self.privacy_class.value if isinstance(self.privacy_class, ModelPrivacyClass) else str(self.privacy_class),
            "status": self.status.value if isinstance(self.status, ModelStatus) else str(self.status),
            "last_verified_at": self.last_verified_at,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ModelRecord:
        vals = dict(row)
        return cls(
            model_id=vals["model_id"],
            provider=vals["provider"],
            model_name=vals["model_name"],
            access_tier=ModelAccessTier(vals["access_tier"]),
            region_compliance=vals.get("region_compliance", "EU_COMPLIANT"),
            quota_info=vals.get("quota_info"),
            privacy_class=ModelPrivacyClass(vals.get("privacy_class", "confidential_anonymized")),
            status=ModelStatus(vals.get("status", "discovered")),
            last_verified_at=vals.get("last_verified_at"),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class ModelEvaluationRecord(BaseModel):
    """Pydantic v2 model representing an immutable benchmark evaluation score."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: f"eval_{uuid.uuid4().hex[:12]}")
    model_id: str
    eval_dataset_version: str = "v1.0"
    task_category: TaskCategory
    score_pct: Decimal = Field(ge=Decimal("0.00"), le=Decimal("100.00"))
    critical_error_passed: bool = False
    is_champion: bool = False
    eval_metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "model_id": self.model_id,
            "eval_dataset_version": self.eval_dataset_version,
            "task_category": self.task_category.value if isinstance(self.task_category, TaskCategory) else str(self.task_category),
            "score_pct": str(self.score_pct),
            "critical_error_passed": 1 if self.critical_error_passed else 0,
            "is_champion": 1 if self.is_champion else 0,
            "eval_metrics_json": json.dumps(self.eval_metrics, sort_keys=True, ensure_ascii=False),
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ModelEvaluationRecord:
        vals = dict(row)
        metrics_raw = vals.get("eval_metrics_json", "{}")
        try:
            metrics_dict = json.loads(metrics_raw) if isinstance(metrics_raw, str) else metrics_raw
        except Exception:
            metrics_dict = {}
        return cls(
            evaluation_id=vals["evaluation_id"],
            model_id=vals["model_id"],
            eval_dataset_version=vals["eval_dataset_version"],
            task_category=TaskCategory(vals["task_category"]),
            score_pct=Decimal(str(vals["score_pct"])),
            critical_error_passed=bool(vals["critical_error_passed"]),
            is_champion=bool(vals["is_champion"]),
            eval_metrics=metrics_dict,
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class ModelRunRecord(BaseModel):
    """Pydantic v2 model representing an immutable execution run manifest."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(default_factory=lambda: f"mrun_{uuid.uuid4().hex[:12]}")
    task_name: str
    quick_model_id: str
    deep_model_id: str
    route_label: str
    prompt_hash: str
    tools_used: str = "[]"
    selection_rationale: str
    status: ModelRunStatus = ModelRunStatus.COMPLETED
    parent_run_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_name": self.task_name,
            "quick_model_id": self.quick_model_id,
            "deep_model_id": self.deep_model_id,
            "route_label": self.route_label,
            "prompt_hash": self.prompt_hash,
            "tools_used": self.tools_used,
            "selection_rationale": self.selection_rationale,
            "status": self.status.value if isinstance(self.status, ModelRunStatus) else str(self.status),
            "parent_run_id": self.parent_run_id,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ModelRunRecord:
        vals = dict(row)
        return cls(
            run_id=vals["run_id"],
            task_name=vals["task_name"],
            quick_model_id=vals["quick_model_id"],
            deep_model_id=vals["deep_model_id"],
            route_label=vals["route_label"],
            prompt_hash=vals["prompt_hash"],
            tools_used=vals.get("tools_used", "[]"),
            selection_rationale=vals["selection_rationale"],
            status=ModelRunStatus(vals.get("status", "completed")),
            parent_run_id=vals.get("parent_run_id"),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class ModelManifest(BaseModel):
    """Runtime execution manifest accompanying model invocations."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_name: str
    quick_provider: str
    quick_model: str
    deep_provider: str
    deep_model: str
    prompt_summary: str
    eval_version: str = "v1.0"
    tools: List[str] = Field(default_factory=list)
    rationale: str
