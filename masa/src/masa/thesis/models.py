"""Investment thesis data contracts, models, and enums (IP-5)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
from typing import Any, Dict, List, Mapping, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from masa.identity.isin import validate_isin


class ThesisStatus(str, Enum):
    """Lifecycle status of an investment thesis version."""
    ACTIVE = "ACTIVE"              # Aktif yürürlükteki tez
    INVALIDATED = "INVALIDATED"    # Falsifiye edilmiş / geçersiz kılınmış tez
    REVISED = "REVISED"            # Yeni bir sürüme evrilmiş
    SUPERSEDED = "SUPERSEDED"      # Yerine yeni sürüm geçmiş eski versiyon


class ThesisCategory(str, Enum):
    """Investment thesis asset category."""
    CORE = "CORE"                  # Çekirdek geniş piyasa ETF'i (ACWI, World, S&P500)
    FACTOR = "FACTOR"              # Faktör eğilimi ETF'i (Value, Momentum, Quality)
    THEMATIC = "THEMATIC"          # Tematik / Sektörel ETF (Yarıiletken, Sağlık vb.)
    SATELLITE = "SATELLITE"        # Uydu / Taktiksel pozisyon
    STOCK = "STOCK"                # Bireysel hisse senedi tezi
    HEDGE = "HEDGE"                # Sabit getiri / Emtia / Korunma


class ThesisHorizon(str, Enum):
    """Analytical time horizon for thesis evaluation."""
    SHORT_TERM = "SHORT_TERM"      # Kısa vade: < 6 ay
    MEDIUM_TERM = "MEDIUM_TERM"    # Orta vade: 6 ay - 2 yıl
    LONG_TERM = "LONG_TERM"        # Uzun vade: 2 - 5 yıl
    SECULAR = "SECULAR"            # Yapısal / Çok uzun vade: 5+ yıl


class ThesisRecord(BaseModel):
    """Pydantic v2 model representing an immutable, sealed thesis version."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    version_id: str = Field(default_factory=lambda: f"thv_{uuid.uuid4().hex[:12]}")
    thesis_id: str = Field(default_factory=lambda: f"th_{uuid.uuid4().hex[:12]}")
    supersedes_id: Optional[str] = None
    version_number: int = Field(default=1, ge=1)
    isin: str
    category: ThesisCategory
    horizon: ThesisHorizon
    status: ThesisStatus = ThesisStatus.ACTIVE
    title: str = Field(min_length=3, max_length=200)
    one_line_summary: str = Field(min_length=10, max_length=500)
    economic_rationale: str = Field(min_length=10)
    evidence_pillars: List[str] = Field(default_factory=list)
    counter_arguments: Optional[str] = None
    falsification_triggers: List[str] = Field(default_factory=list)
    benchmark_reference: str = Field(default="araştırma referansı")
    sources: List[str] = Field(default_factory=list)
    target_allocation_pct: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"), le=Decimal("1.00"))
    next_review_date: Optional[str] = None
    revision_rationale: Optional[str] = None
    author: str = Field(default="user")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: Optional[str] = None

    @field_validator("title")
    @classmethod
    def check_title(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 3:
            raise ValueError("Başlık en az 3 karakter olmalıdır.")
        return s

    @field_validator("one_line_summary")
    @classmethod
    def check_summary(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 10:
            raise ValueError("Tek satırlık özet en az 10 karakter olmalıdır.")
        return s

    @field_validator("economic_rationale")
    @classmethod
    def check_rationale(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 10:
            raise ValueError("Ekonomik gerekçe en az 10 karakter olmalıdır.")
        return s

    @field_validator("isin")
    @classmethod
    def check_isin(cls, v: str) -> str:
        clean = v.strip().upper()
        validate_isin(clean)
        return clean

    @field_validator("falsification_triggers")
    @classmethod
    def check_triggers(cls, v: List[str]) -> List[str]:
        cleaned = [t.strip() for t in v if t and t.strip()]
        if len(set(cleaned)) < 2:
            raise ValueError("Bir tez en az 2 somut çürütme koşulu (falsification triggers) içermelidir.")
        return list(dict.fromkeys(cleaned))

    @field_validator("next_review_date")
    @classmethod
    def check_review_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("İnceleme tarihi (next_review_date) geçerli bir 'YYYY-MM-DD' formatında olmalıdır.")

    @model_validator(mode="after")
    def validate_lifecycle_and_rationale(self) -> ThesisRecord:
        if self.supersedes_id and self.supersedes_id == self.version_id:
            raise ValueError("Bir tez sürümü kendi kendisinin yerine geçemez (supersedes_id != version_id).")

        # Sürüm 2 ve sonrası için supersedes_id ve revision_rationale zorunludur
        if self.version_number > 1:
            if not self.supersedes_id:
                raise ValueError("Sürüm 1'den büyük tezlerde supersedes_id zorunludur.")
            if not self.revision_rationale or len(self.revision_rationale.strip()) < 10:
                raise ValueError("Tez revizyonlarında en az 10 karakterlik açıklayıcı gerekçe (revision_rationale) zorunludur.")
        else:
            if self.supersedes_id is not None:
                raise ValueError("İlk sürümde (v1) supersedes_id tanımlanamaz.")

        # Geçersiz kılınan tez kontrolü
        if self.status == ThesisStatus.INVALIDATED:
            if not self.revision_rationale or len(self.revision_rationale.strip()) < 10:
                raise ValueError("Tezi geçersiz kılarken en az 10 karakterlik gerekçe (revision_rationale) zorunludur.")

        return self

    def to_db_row(self, computed_hash: str) -> Dict[str, Any]:
        """Convert to row mapping matching schema.sql thesis_versions columns."""
        return {
            "version_id": self.version_id,
            "thesis_id": self.thesis_id,
            "supersedes_id": self.supersedes_id,
            "version_number": self.version_number,
            "isin": self.isin,
            "category": self.category.value,
            "horizon": self.horizon.value,
            "status": self.status.value,
            "title": self.title,
            "one_line_summary": self.one_line_summary,
            "economic_rationale": self.economic_rationale,
            "evidence_pillars_json": json.dumps(self.evidence_pillars, ensure_ascii=False),
            "counter_arguments": self.counter_arguments,
            "falsification_triggers_json": json.dumps(self.falsification_triggers, ensure_ascii=False),
            "benchmark_reference": self.benchmark_reference,
            "sources_json": json.dumps(self.sources, ensure_ascii=False),
            "target_allocation_pct": str(self.target_allocation_pct) if self.target_allocation_pct is not None else None,
            "next_review_date": self.next_review_date,
            "revision_rationale": self.revision_rationale,
            "author": self.author,
            "created_at": self.created_at,
            "record_hash": computed_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ThesisRecord:
        """Hydrate from SQLite thesis_versions row."""
        vals = dict(row)
        return cls(
            version_id=vals["version_id"],
            thesis_id=vals["thesis_id"],
            supersedes_id=vals.get("supersedes_id"),
            version_number=int(vals.get("version_number", 1)),
            isin=vals["isin"],
            category=ThesisCategory(vals["category"]),
            horizon=ThesisHorizon(vals["horizon"]),
            status=ThesisStatus(vals.get("status", "ACTIVE")),
            title=vals["title"],
            one_line_summary=vals["one_line_summary"],
            economic_rationale=vals["economic_rationale"],
            evidence_pillars=json.loads(vals.get("evidence_pillars_json", "[]")),
            counter_arguments=vals.get("counter_arguments"),
            falsification_triggers=json.loads(vals.get("falsification_triggers_json", "[]")),
            benchmark_reference=vals.get("benchmark_reference", "araştırma referansı"),
            sources=json.loads(vals.get("sources_json", "[]")),
            target_allocation_pct=Decimal(str(vals["target_allocation_pct"])) if vals.get("target_allocation_pct") is not None else None,
            next_review_date=vals.get("next_review_date"),
            revision_rationale=vals.get("revision_rationale"),
            author=vals.get("author", "user"),
            created_at=vals["created_at"],
            record_hash=vals.get("record_hash"),
        )
