"""Data models and validation types for ETF holdings baskets (İP-4)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class HoldingsValidationError(ValueError):
    """Raised when holdings file or records violate integrity invariants."""


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    CASH = "CASH"
    DERIVATIVE = "DERIVATIVE"
    OTHER = "OTHER"


class ParsedHoldingItem(BaseModel):
    """A single constituent line item within an ETF holdings basket."""
    model_config = ConfigDict(frozen=True)

    item_order: int
    constituent_name: str = Field(min_length=1)
    weight_pct: Decimal  # Normalized proportion in [-1.0, 1.0]
    constituent_isin: Optional[str] = None
    constituent_ticker: Optional[str] = None
    shares_held: Optional[Decimal] = None
    market_value: Optional[Decimal] = None
    currency: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    asset_class: str = AssetClass.EQUITY.value


class ParsedHoldingsSet(BaseModel):
    """A complete parsed ETF holdings basket."""
    model_config = ConfigDict(frozen=True)

    isin: str
    as_of_date: date
    source_file: str
    provider: str
    total_records: int
    total_weight_pct: Decimal  # Normalized proportion total (<= 1.0001)
    total_equity_weight: Decimal = Decimal("0")
    total_cash_weight: Decimal = Decimal("0")
    total_derivative_weight: Decimal = Decimal("0")
    items: List[ParsedHoldingItem] = Field(default_factory=list)
