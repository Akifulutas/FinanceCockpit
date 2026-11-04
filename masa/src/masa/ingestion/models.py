"""Pydantic v2 DTO models for Scalable CLI read-only data ingestion."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RawBrokerPayload(BaseModel):
    """Raw response wrapper from Scalable CLI execution."""
    model_config = ConfigDict(frozen=True)

    command: str
    args: List[str]
    retrieved_at: datetime
    stdout_raw: str
    parsed_json: dict[str, Any]
    payload_sha256: str


class QuoteData(BaseModel):
    """Lossless Decimal parsed security quote from 'sc broker quote'."""
    model_config = ConfigDict(frozen=True)

    isin: str
    name: str
    security_type: str
    bid: Decimal = Field(..., gt=0, description="Highest price a buyer will pay")
    ask: Decimal = Field(..., gt=0, description="Lowest price a seller will accept")
    mid: Decimal = Field(..., gt=0, description="Provider reported mid price")
    computed_mid: Decimal = Field(..., gt=0, description="Locally computed mid: (bid + ask) / 2")
    spread: Decimal = Field(..., ge=0, description="Spread: ask - bid")
    spread_pct: Decimal = Field(..., ge=0, description="Spread percentage of computed mid: (spread / computed_mid) * 100")
    currency: str
    is_outdated: Optional[bool] = Field(None, description="True/False if explicitly reported, None if N/A or absent")
    timestamp_utc: datetime
    account_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    performances: Dict[str, Decimal] = Field(default_factory=dict, description="timeframe -> fractional return (0.01 = 1%)")


class ChartPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp_utc: datetime
    mid_price: Decimal = Field(..., gt=0)


class ChartSeries(BaseModel):
    """`sc broker chart` price history for one ISIN (sampled, source e.g. CONSOLIDATED)."""
    model_config = ConfigDict(frozen=True)
    isin: str
    currency: str
    source: str
    timeframe: str
    reference: Optional[ChartPoint] = None
    points: List[ChartPoint]
    retrieved_at: datetime


class PositionItem(BaseModel):
    """Individual portfolio holding parsed from 'sc broker holdings'."""
    model_config = ConfigDict(frozen=True)

    isin: str
    name: str
    security_type: str
    quantity: Decimal = Field(..., ge=0)
    fifo_price: Optional[Decimal] = None
    quote_mid_price: Decimal = Field(..., gt=0)
    quote_currency: str
    quote_timestamp_utc: datetime
    valuation: Decimal = Field(..., ge=0)
    valuation_currency: str
    blocked_quantity: Decimal = Decimal("0")
    pending_quantity: Decimal = Decimal("0")


class PositionsResult(BaseModel):
    """Aggregated portfolio holdings container."""
    model_config = ConfigDict(frozen=True)

    account_id: str
    portfolio_id: str
    count: int
    items: List[PositionItem]
    retrieved_at: datetime


class CashBreakdownResult(BaseModel):
    """Cash and liquidity breakdown from 'sc broker cash-breakdown'."""
    model_config = ConfigDict(frozen=True)

    account_id: str
    portfolio_id: str
    cash_balance: Decimal
    buying_power: Decimal
    buying_power_without_credit: Decimal
    available_credit_line: Decimal
    derivatives_buying_power: Decimal
    pending_buy_orders_amount: Decimal
    possible_taxes: Decimal
    retrieved_at: datetime


class TransactionItem(BaseModel):
    """Historical broker transaction item from 'sc broker transactions'."""
    model_config = ConfigDict(frozen=True)

    id: str
    type: str  # e.g., SECURITY_TRANSACTION, CASH_TRANSACTION
    cash_transaction_type: Optional[str] = None  # e.g., FEE, DEPOSIT, WITHDRAWAL
    security_transaction_type: Optional[str] = None  # e.g., SINGLE
    side: Optional[str] = None  # BUY, SELL
    isin: Optional[str] = None
    description: Optional[str] = None
    amount: Decimal
    currency: str
    quantity: Optional[Decimal] = None
    limit_price: Optional[Decimal] = None
    status: str  # SETTLED, FILLED, etc.
    is_cancellation: bool = False
    last_event_datetime: datetime


class TransactionsResult(BaseModel):
    """Paginated transactions container."""
    model_config = ConfigDict(frozen=True)

    account_id: str
    portfolio_id: str
    count: int
    total: Optional[int] = None
    cursor: Optional[str] = None
    items: List[TransactionItem]
    retrieved_at: datetime
