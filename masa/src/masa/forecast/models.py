"""Pydantic v2 strict models for Daily Forecast and Settlement Engine (IP-5)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from masa.identity.isin import validate_isin


class ForecastDirection(str, Enum):
    """Forecast market direction enum."""
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class ForecastType(str, Enum):
    """Forecast type enum."""
    DAILY_CLOSE = "DAILY_CLOSE"


class PoolInstrument(BaseModel):
    """Instrument definition within the forecast pool."""
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    isin: str
    ad: str
    sembol: str
    yahoo: str
    rol: str
    mic: str
    para_birimi: str = "EUR"
    asset_type: str = "ETF"  # 'ETF' or 'EQUITY'

    @field_validator("isin")
    @classmethod
    def check_isin(cls, v: str) -> str:
        clean = v.strip().upper()
        validate_isin(clean)
        return clean


class ForecastPoolConfig(BaseModel):
    """Full pool configuration from config/tahmin_havuzu.json."""
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = 1
    guncellenme_tarihi: str
    etf: Dict[str, PoolInstrument]
    hisse: Dict[str, PoolInstrument]

    def all_instruments(self) -> List[PoolInstrument]:
        return list(self.etf.values()) + list(self.hisse.values())


class ForecastEntry(BaseModel):
    """Immutable, sealed forecast entry."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    forecast_id: str
    isin: str
    target_date: str  # YYYY-MM-DD
    forecast_type: str = "DAILY_CLOSE"
    direction: ForecastDirection
    reference_price: Decimal
    target_price: Decimal
    confidence_pct: Decimal
    model_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: str

    @property
    def display_confidence(self) -> str:
        if self.confidence_pct is None or self.confidence_pct == Decimal("0.00") or self.confidence_pct == Decimal("0"):
            return "—"
        return f"%{self.confidence_pct:.1f}"

    @field_validator("isin")
    @classmethod
    def check_isin(cls, v: str) -> str:
        clean = v.strip().upper()
        validate_isin(clean)
        return clean

    def to_db_row(self) -> Dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "isin": self.isin,
            "target_date": self.target_date,
            "forecast_type": self.forecast_type,
            "direction": self.direction.value,
            "reference_price": str(self.reference_price),
            "target_price": str(self.target_price),
            "confidence_pct": str(self.confidence_pct),
            "model_id": self.model_id,
            "created_at": self.created_at,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> ForecastEntry:
        vals = dict(row)
        return cls(
            forecast_id=vals["forecast_id"],
            isin=vals["isin"],
            target_date=vals["target_date"],
            forecast_type=vals.get("forecast_type", "DAILY_CLOSE"),
            direction=ForecastDirection(vals["direction"]),
            reference_price=Decimal(str(vals["reference_price"])),
            target_price=Decimal(str(vals["target_price"])),
            confidence_pct=Decimal(str(vals["confidence_pct"])),
            model_id=vals["model_id"],
            created_at=vals["created_at"],
            record_hash=vals["record_hash"],
        )


class SettlementEntry(BaseModel):
    """Immutable, sealed forecast settlement entry."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    settlement_id: str
    forecast_id: str
    isin: str
    settlement_date: str  # YYYY-MM-DD
    actual_close_price: Decimal
    error_eur: Decimal
    error_pct: Decimal
    direction_hit: int  # 1 or 0
    settled_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    record_hash: str

    @field_validator("isin")
    @classmethod
    def check_isin(cls, v: str) -> str:
        clean = v.strip().upper()
        validate_isin(clean)
        return clean

    def to_db_row(self) -> Dict[str, Any]:
        return {
            "settlement_id": self.settlement_id,
            "forecast_id": self.forecast_id,
            "isin": self.isin,
            "settlement_date": self.settlement_date,
            "actual_close_price": str(self.actual_close_price),
            "error_eur": str(self.error_eur),
            "error_pct": str(self.error_pct),
            "direction_hit": int(self.direction_hit),
            "settled_at": self.settled_at,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> SettlementEntry:
        vals = dict(row)
        return cls(
            settlement_id=vals["settlement_id"],
            forecast_id=vals["forecast_id"],
            isin=vals["isin"],
            settlement_date=vals["settlement_date"],
            actual_close_price=Decimal(str(vals["actual_close_price"])),
            error_eur=Decimal(str(vals["error_eur"])),
            error_pct=Decimal(str(vals["error_pct"])),
            direction_hit=int(vals["direction_hit"]),
            settled_at=vals["settled_at"],
            record_hash=vals["record_hash"],
        )


class ForecastPerformanceMetrics(BaseModel):
    """Aggregated performance scorecard for settled forecasts."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_forecasts: int
    settled_count: int
    pending_count: int
    hit_rate_pct: Decimal
    etf_hit_rate_pct: Optional[Decimal] = None
    stock_hit_rate_pct: Optional[Decimal] = None
    mape_pct: Decimal
    mae_eur: Decimal
    mpe_pct: Decimal
    is_small_sample: bool = True
    warning_message: Optional[str] = None
    baseline_flat_hit_rate_pct: Optional[Decimal] = None
    baseline_yesterday_hit_rate_pct: Optional[Decimal] = None
    beats_baselines: Optional[bool] = None
    baseline_warning: Optional[str] = None
