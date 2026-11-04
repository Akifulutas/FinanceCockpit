"""Data contracts for calendar and quote age assessments."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class MarketSessionState(str, Enum):
    """Status of the exchange market session at observation time."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class QuoteAgeAssessment(BaseModel):
    """Immutable audit assessment of quote freshness and market session."""
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    quote_time: datetime = Field(..., description="Timestamp of the quote (UTC)")
    snapshot_time: datetime = Field(..., description="Observation/snapshot ingestion timestamp (UTC)")
    age_seconds: float = Field(..., ge=0.0, description="Absolute elapsed age in seconds")
    session_state: MarketSessionState = Field(
        ...,
        description="Market state: OPEN, CLOSED, or UNKNOWN (when venue is unverified)",
    )
    venue_mic: Optional[str] = Field(
        default=None,
        description="Market Identifier Code (e.g. XETR) or None if source unknown/consolidated",
    )
    is_stale: bool = Field(..., description="Whether quote violates freshness policy for its state")
    calendar_name: Optional[str] = Field(default=None, description="Calendar identifier (e.g. XETR)")
    calendar_version: Optional[str] = Field(default=None, description="Installed exchange-calendars version")
    diagnostic_note: str = Field(default="", description="Human-readable audit explanation of the evaluation")

    @property
    def session_status(self) -> str:
        """String representation of session_state for compatibility."""
        return self.session_state.value

    @property
    def exchange_used(self) -> Optional[str]:
        """Alias for venue_mic."""
        return self.venue_mic

    @property
    def quote_timestamp(self) -> datetime:
        """Alias for quote_time."""
        return self.quote_time

    @property
    def retrieved_at(self) -> datetime:
        """Alias for snapshot_time."""
        return self.snapshot_time
