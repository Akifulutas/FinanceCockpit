"""Research Evidence Models and Data Contracts (IP-6)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    """Classification of research sources."""
    FACTSHEET = "FACTSHEET"
    REGULATORY_FILING = "REGULATORY_FILING"
    CENTRAL_BANK = "CENTRAL_BANK"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    PROSPECTUS = "PROSPECTUS"
    OFFICIAL_WEBSITE = "OFFICIAL_WEBSITE"
    OTHER = "OTHER"


class ClaimType(str, Enum):
    """Semantic classification of extracted research claims."""
    FACT = "fact"
    SOURCED_ESTIMATE = "sourced_estimate"
    COMPUTATION = "computation"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class ClaimVerificationStatus(str, Enum):
    """Verification status of extracted claims."""
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REFUTED = "REFUTED"


class SourceRecord(BaseModel):
    """Pydantic v2 model representing an immutable research source."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(default_factory=lambda: f"src_{uuid.uuid4().hex[:12]}")
    source_type: SourceType
    title: str = Field(min_length=3)
    url_or_path: str = Field(min_length=3)
    publisher: str = Field(min_length=2)
    publication_date: Optional[str] = None  # YYYY-MM-DD
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    content_sha256: str = Field(min_length=64, max_length=64)
    raw_object_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "title": self.title,
            "url_or_path": self.url_or_path,
            "publisher": self.publisher,
            "publication_date": self.publication_date,
            "retrieved_at": self.retrieved_at,
            "content_sha256": self.content_sha256,
            "raw_object_id": self.raw_object_id,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> SourceRecord:
        vals = dict(row)
        return cls(
            source_id=vals["source_id"],
            source_type=SourceType(vals["source_type"]),
            title=vals["title"],
            url_or_path=vals["url_or_path"],
            publisher=vals["publisher"],
            publication_date=vals.get("publication_date"),
            retrieved_at=vals["retrieved_at"],
            content_sha256=vals["content_sha256"],
            raw_object_id=vals.get("raw_object_id"),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class EvidenceBundleRecord(BaseModel):
    """Container grouping verified claims and metrics for an instrument."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str = Field(default_factory=lambda: f"bnd_{uuid.uuid4().hex[:12]}")
    instrument_id: str
    run_id: Optional[str] = None
    as_of_date: str  # YYYY-MM-DD
    model_id: str = "user"
    claims_count: int = 0
    metrics_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "instrument_id": self.instrument_id,
            "run_id": self.run_id,
            "as_of_date": self.as_of_date,
            "model_id": self.model_id,
            "claims_count": self.claims_count,
            "metrics_count": self.metrics_count,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> EvidenceBundleRecord:
        vals = dict(row)
        return cls(
            bundle_id=vals["bundle_id"],
            instrument_id=vals["instrument_id"],
            run_id=vals.get("run_id"),
            as_of_date=vals["as_of_date"],
            model_id=vals.get("model_id", "user"),
            claims_count=int(vals.get("claims_count", 0)),
            metrics_count=int(vals.get("metrics_count", 0)),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class ClaimRecord(BaseModel):
    """Verbatim backed claim extracted from a verified source."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:12]}")
    bundle_id: str
    instrument_id: str
    claim_text: str = Field(min_length=5)
    claim_type: ClaimType = ClaimType.FACT
    source_id: str
    quote_verbatim: str = Field(min_length=5)
    section_ref: Optional[str] = None
    page_num: Optional[int] = None
    confidence_pct: Decimal = Decimal("100.00")
    verification_status: ClaimVerificationStatus = ClaimVerificationStatus.VERIFIED
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "bundle_id": self.bundle_id,
            "instrument_id": self.instrument_id,
            "claim_text": self.claim_text,
            "claim_type": self.claim_type.value if isinstance(self.claim_type, ClaimType) else str(self.claim_type),
            "source_id": self.source_id,
            "quote_verbatim": self.quote_verbatim,
            "section_ref": self.section_ref,
            "page_num": self.page_num,
            "confidence_pct": str(self.confidence_pct),
            "verification_status": self.verification_status.value,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ClaimRecord:
        vals = dict(row)
        raw_type = vals.get("claim_type", "fact")
        try:
            claim_type = ClaimType(raw_type)
        except Exception:
            claim_type = ClaimType.FACT
        return cls(
            claim_id=vals["claim_id"],
            bundle_id=vals["bundle_id"],
            instrument_id=vals["instrument_id"],
            claim_text=vals["claim_text"],
            claim_type=claim_type,
            source_id=vals["source_id"],
            quote_verbatim=vals["quote_verbatim"],
            section_ref=vals.get("section_ref"),
            page_num=int(vals["page_num"]) if vals.get("page_num") is not None else None,
            confidence_pct=Decimal(str(vals.get("confidence_pct", "100.00"))),
            verification_status=ClaimVerificationStatus(vals.get("verification_status", "VERIFIED")),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )


class MetricRecord(BaseModel):
    """Verified quantitative financial metric mapped to an instrument and source."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str = Field(default_factory=lambda: f"met_{uuid.uuid4().hex[:12]}")
    bundle_id: Optional[str] = None
    instrument_id: str
    metric_name: str = Field(min_length=2)
    value: Decimal
    unit: str = Field(min_length=1)  # e.g. "EUR", "%", "BPS", "RATIO"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    source_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "bundle_id": self.bundle_id,
            "instrument_id": self.instrument_id,
            "metric_name": self.metric_name,
            "value": str(self.value),
            "unit": self.unit,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "source_id": self.source_id,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> MetricRecord:
        vals = dict(row)
        return cls(
            metric_id=vals["metric_id"],
            bundle_id=vals.get("bundle_id"),
            instrument_id=vals["instrument_id"],
            metric_name=vals["metric_name"],
            value=Decimal(str(vals["value"])),
            unit=vals["unit"],
            period_start=vals.get("period_start"),
            period_end=vals.get("period_end"),
            source_id=vals["source_id"],
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )
