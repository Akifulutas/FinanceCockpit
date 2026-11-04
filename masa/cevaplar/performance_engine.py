"""SPEC-PROMPT-PERF-001 / 1.0.0 — read-only portfolio performance engine.

Python >=3.10, Pydantic >=2.  No other runtime dependencies.

Public API:
    calculate_performance(payload, *, context=None) -> PerformanceEngineOutput
    audit_cost_basis(payload, *, context=None) -> list[CostBasisAudit]

``payload`` has exactly the PerformanceEngineInput JSON keys in the specification.
The optional, separate ``context`` is essential when the specification cannot
identify opening lots, per-ISIN terminal marks, dividend attribution, non-cash
transfers, or corporate actions. The original input/output contracts are never
extended or silently populated with invented market values.

CLI:
    python performance_engine.py input.json [--context context.json] [-o out.json]

Conventions:
* All inputs/outputs named *_pct are percentage points (10.0 means 10%).
  TWR step returns and accumulated returns are decimal fractions.
* Realized PnL in the strict output is FIFO realized PnL; audit_cost_basis()
  exposes both FIFO and WAC realized PnL separately.
* Purchases include execution fees and purchase taxes in acquisition cost;
  disposal PnL uses proceeds net of sale fees and taxes.
* Under the specified classification, BROKER_FEE is an external outflow.
* A zero opening capital / zero opening pre-flow equity TWR segment is neutral
  only when its ending pre-flow equity is also exactly zero.
* At identical timestamps, corporate actions precede transactions, and
  transactions preserve their order in the input list. External cash flows are
  aggregated for TWR to avoid dependence on the input row order.
* A period shorter than 90 calendar days reports *period* MWR in the legacy
  field xirr_annualized_pct with status SUB_ANNUAL_UNANNUALIZED. This legacy
  field name is from the strict specification and cannot be changed.

Known specification gaps, handled explicitly rather than guessed:
- The original input has no opening lots, per-ISIN marks, dividend/ISIN
  mapping, corporate action type, or non-cash transfer flag.
- Without enough context to value open positions, MissingMarketDataError is
  raised instead of outputting fabricated unrealized PnL.
- A positive opening positions_value requires opening_lots when there are
  position transactions/holdings to account for. Standalone return calculations
  still work with an empty transaction list and no opening lots, in which case
  opening/ending position reconciliation is marked incomplete.
- The stated acceptance-test identity "remaining basis + realized PnL +
  unrealized PnL = invested capital" is not a valid accounting identity.
  Correctly, net disposals + ending market value = acquisition cost +
  realized PnL + unrealized PnL, for a fully reconstructed holding history.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Annotated, Mapping, Sequence

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
    WithJsonSchema,
    field_validator,
    model_validator,
)

ZERO = Decimal("0")
ONE = Decimal("1")
CASH_TOL = Decimal("0.01")
SHARE_TOL = Decimal("0.000000000001")
NPV_TOL = 1e-5
YEAR_SECONDS = 365.25 * 86400.0


class PerformanceError(ValueError):
    """Invalid accounting facts or fundamentally underdetermined calculation."""


class MissingMarketDataError(PerformanceError):
    """Cannot allocate terminal market value to all open ISIN positions."""


class NegativePositionError(PerformanceError):
    """Sale or corporate action would result in a negative position."""


def _numeric(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("JSON numeric field must be a number, not a string/bool")
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("invalid numeric field") from exc
    if not result.is_finite():
        raise ValueError("numeric field must be finite")
    return result


def _as_json_number(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("cannot represent Decimal as finite JSON number")
    return result


Number = Annotated[
    Decimal,
    BeforeValidator(_numeric),
    PlainSerializer(_as_json_number, return_type=float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EvaluationPeriod(StrictModel):
    start_date: datetime
    end_date: datetime
    calendar_days: int = Field(ge=1)

    @model_validator(mode="after")
    def check_period(self) -> EvaluationPeriod:
        if self.start_date.tzinfo is None or self.end_date.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware RFC3339 datetimes")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        days = (self.end_date.date() - self.start_date.date()).days
        if days != self.calendar_days:
            raise ValueError(
                f"calendar_days={self.calendar_days}, but date difference={days}"
            )
        return self


class PortfolioValuation(StrictModel):
    total_equity: Number = Field(ge=ZERO)
    cash_balance: Number
    positions_value: Number = Field(ge=ZERO)


class SubperiodValuation(StrictModel):
    timestamp: datetime
    equity_before_flow: Number = Field(ge=ZERO)


class FlowType(str, Enum):
    EXTERNAL_DEPOSIT = "EXTERNAL_DEPOSIT"
    EXTERNAL_WITHDRAWAL = "EXTERNAL_WITHDRAWAL"
    SPARPLAN_EXTERNAL_DEBIT = "SPARPLAN_EXTERNAL_DEBIT"
    INTERNAL_DIVIDEND = "INTERNAL_DIVIDEND"
    INTERNAL_TRADE_CASH = "INTERNAL_TRADE_CASH"
    BROKER_FEE = "BROKER_FEE"


EXTERNAL_TYPES = frozenset({
    FlowType.EXTERNAL_DEPOSIT,
    FlowType.EXTERNAL_WITHDRAWAL,
    FlowType.SPARPLAN_EXTERNAL_DEBIT,
    FlowType.BROKER_FEE,
})


class CashFlow(StrictModel):
    flow_id: str = Field(min_length=1)
    timestamp: datetime
    raw_description: str
    amount: Number
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    classified_type: FlowType

    @model_validator(mode="after")
    def check_sign(self) -> CashFlow:
        typ = self.classified_type
        if typ in {FlowType.EXTERNAL_DEPOSIT, FlowType.SPARPLAN_EXTERNAL_DEBIT} and self.amount < 0:
            raise ValueError(f"{typ.value} must have a nonnegative amount")
        if typ in {FlowType.EXTERNAL_WITHDRAWAL, FlowType.BROKER_FEE} and self.amount > 0:
            raise ValueError(f"{typ.value} must have a nonpositive amount")
        return self


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Transaction(StrictModel):
    tx_id: str = Field(min_length=1)
    timestamp: datetime
    isin: str = Field(min_length=1)
    side: Side
    shares: Number = Field(gt=ZERO)
    execution_price: Number = Field(gt=ZERO)
    fees: Number = Field(default=ZERO, ge=ZERO)
    taxes: Number = Field(default=ZERO, ge=ZERO)
    total_cash_impact: Number

    @model_validator(mode="after")
    def check_cash(self) -> Transaction:
        gross = self.shares * self.execution_price
        estimated = (
            -gross - self.fees - self.taxes if self.side is Side.BUY
            else gross - self.fees - self.taxes
        )
        if abs(self.total_cash_impact - estimated) > CASH_TOL:
            raise ValueError(
                f"tx_id={self.tx_id}: cash impact {self.total_cash_impact} "
                f"inconsistent with gross/fees/taxes ({estimated})"
            )
        return self


class AccountingOptions(StrictModel):
    compute_modified_dietz: bool = True
    compute_true_twr: bool = True
    compute_xirr: bool = True
    annualize_threshold_days: int = Field(default=365, ge=1)


class PerformanceEngineInput(StrictModel):
    evaluation_period: EvaluationPeriod
    initial_valuation: PortfolioValuation
    terminal_valuation: PortfolioValuation
    subperiod_valuations: list[SubperiodValuation] = Field(default_factory=list)
    cash_flows: list[CashFlow]
    transactions: list[Transaction]
    accounting_options: AccountingOptions

    @model_validator(mode="after")
    def check_events(self) -> PerformanceEngineInput:
        period = self.evaluation_period
        for collection, name in (
            (self.cash_flows, "cash_flows"),
            (self.transactions, "transactions"),
            (self.subperiod_valuations, "subperiod_valuations"),
        ):
            for event in collection:
                if event.timestamp.tzinfo is None:
                    raise ValueError(f"{name}: all timestamps must include timezone")
                if not period.start_date <= event.timestamp <= period.end_date:
                    raise ValueError(f"{name}: timestamp outside evaluation period")
        for events, id_field in ((self.cash_flows, "flow_id"), (self.transactions, "tx_id")):
            identifiers = [getattr(event, id_field) for event in events]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {id_field}")
        stamps = [event.timestamp for event in self.subperiod_valuations]
        if len(stamps) != len(set(stamps)):
            raise ValueError("duplicate subperiod valuation timestamp")
        currencies = {event.currency for event in self.cash_flows}
        if len(currencies) > 1:
            raise ValueError("mixed cash flow currencies require FX conversion (not in spec)")
        return self


class OpeningLot(StrictModel):
    isin: str = Field(min_length=1)
    timestamp: datetime
    shares: Number = Field(gt=ZERO)
    cost_per_share: Number = Field(ge=ZERO)


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    ISIN_CHANGE = "ISIN_CHANGE"
    MERGER = "MERGER"


class CorporateAction(StrictModel):
    timestamp: datetime
    isin: str = Field(min_length=1)
    action_type: CorporateActionType
    ratio: Number = Field(gt=ZERO)  # New shares / original shares
    new_isin: str | None = None

    @model_validator(mode="after")
    def check_target(self) -> CorporateAction:
        if self.action_type is CorporateActionType.SPLIT:
            if self.new_isin is not None:
                raise ValueError("SPLIT must not set new_isin")
        elif not self.new_isin or self.new_isin == self.isin:
            raise ValueError("ISIN_CHANGE / MERGER require a different new_isin")
        return self


class SecurityTransfer(StrictModel):
    """In-kind inbound securities, valued externally at their market value.

    Cost basis is provided independently: for taxable lots it need not equal
    the transfer-date market value. One cash-flow ID can describe several lots.
    """

    flow_id: str = Field(min_length=1)
    timestamp: datetime
    isin: str = Field(min_length=1)
    shares: Number = Field(gt=ZERO)
    cost_per_share: Number = Field(ge=ZERO)
    market_value: Number = Field(ge=ZERO)


class EngineContext(StrictModel):
    """Separate optional facts absent from the locked PerformanceEngineInput schema.

    terminal_position_values is an exact *valuation per ISIN*, not a quoted
    share price. One missing valuation can be calculated from the portfolio total.
    dividend_flow_to_isin maps existing INTERNAL_DIVIDEND flow IDs to ISINs.
    noncash_external_flow_ids marks EXTERNAL_DEPOSIT flows as securities
    transfers rather than cash. security_transfers supplies the individual
    transfer lots, their market values, and their independent tax cost basis.
    """

    opening_lots: list[OpeningLot] = Field(default_factory=list)
    terminal_position_values: dict[str, Number] = Field(default_factory=dict)
    dividend_flow_to_isin: dict[str, str] = Field(default_factory=dict)
    noncash_external_flow_ids: set[str] = Field(default_factory=set)
    security_transfers: list[SecurityTransfer] = Field(default_factory=list)
    corporate_actions: list[CorporateAction] = Field(default_factory=list)

    @field_validator("terminal_position_values")
    @classmethod
    def check_marks(cls, values: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(not k or v < ZERO for k, v in values.items()):
            raise ValueError("ISIN must be nonempty and terminal valuations nonnegative")
        return values


class EngineMetadata(StrictModel):
    calculation_timestamp: datetime
    period_start: datetime
    period_end: datetime
    calendar_days: int


class ReturnsSummary(StrictModel):
    start_equity: Number
    end_equity: Number
    net_external_flow: Number
    absolute_gain_loss: Number
    modified_dietz_pct: Number | None
    dietz_capital_base: Number | None
    true_twr_cumulative_pct: Number | None = None
    true_twr_annualized_pct: Number | None = None
    xirr_annualized_pct: Number | None = None
    xirr_convergence_status: str = "NOT_REQUESTED"

    @field_validator("xirr_convergence_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        permitted = {"CONVERGED", "ROOT_NOT_FOUND", "SUB_ANNUAL_UNANNUALIZED", "NOT_REQUESTED"}
        if value not in permitted:
            raise ValueError(f"invalid xirr convergence status: {value}")
        return value


class CashFlowLedgerRow(StrictModel):
    flow_id: str
    timestamp: datetime
    classified_type: FlowType
    amount: Number
    is_external_flow: bool
    dietz_day_weight: Number
    weighted_flow_amount: Number


class PositionCostBasis(StrictModel):
    isin: str
    shares: Number
    current_valuation: Number
    wac_cost_per_share: Number
    wac_unrealized_pnl: Number
    fifo_cost_per_share: Number
    fifo_unrealized_pnl: Number
    fifo_open_lots_count: int
    period_realized_pnl: Number
    period_dividends: Number


class TWRStep(StrictModel):
    step_index: int
    flow_timestamp: datetime
    equity_before: Number
    external_flow: Number
    subperiod_return: Number
    cumulative_twr: Number


class ReconciliationDiagnostics(StrictModel):
    unexplained_cash_gap: Number
    is_balanced: bool
    warnings: list[str]


class PerformanceEngineOutput(StrictModel):
    engine_metadata: EngineMetadata
    returns_summary: ReturnsSummary
    cash_flow_ledger: list[CashFlowLedgerRow]
    position_cost_basis: list[PositionCostBasis]
    subperiod_twr_steps: list[TWRStep] = Field(default_factory=list)
    reconciliation_diagnostics: ReconciliationDiagnostics


class CostBasisAudit(StrictModel):
    """Optional audit view; NOT included in locked PerformanceEngineOutput JSON."""

    isin: str
    opening_acquisition_cost: Number
    purchase_cost_in_period: Number
    net_sale_proceeds_in_period: Number
    wac_realized_pnl: Number
    fifo_realized_pnl: Number
    wac_remaining_basis: Number
    fifo_remaining_basis: Number
    wac_unrealized_pnl: Number
    fifo_unrealized_pnl: Number


class _Lot:
    __slots__ = ("shares", "cost_per_share", "timestamp")

    def __init__(self, shares: Decimal, price: Decimal, timestamp: datetime):
        self.shares = shares
        self.cost_per_share = price
        self.timestamp = timestamp


class _Holding:
    def __init__(self) -> None:
        self.shares: Decimal = ZERO
        self.wac_basis: Decimal = ZERO
        self.lots: deque[_Lot] = deque()
        self.realized_wac: Decimal = ZERO
        self.realized_fifo: Decimal = ZERO
        self.opening_cost: Decimal = ZERO
        self.purchases: Decimal = ZERO
        self.net_proceeds: Decimal = ZERO

    def buy(self, q: Decimal, basis: Decimal, timestamp: datetime, *, opening: bool) -> None:
        self.shares += q
        self.wac_basis += basis
        self.lots.append(_Lot(q, basis / q, timestamp))
        if opening:
            self.opening_cost += basis
        else:
            self.purchases += basis

    def sell(self, q: Decimal, net_proceeds: Decimal, *, isin: str) -> None:
        if q > self.shares + SHARE_TOL:
            raise NegativePositionError(
                f"{isin}: sale of {q} shares exceeds existing {self.shares} shares"
            )
        if q > self.shares:  # Tiny quantity input rounding, not a short position.
            q = self.shares
        self.net_proceeds += net_proceeds
        average = self.wac_basis / self.shares
        wac_removed = average * q
        self.realized_wac += net_proceeds - wac_removed
        self.wac_basis -= wac_removed
        self.shares -= q
        remaining = q
        fifo_removed = ZERO
        while remaining > SHARE_TOL:
            if not self.lots:
                raise NegativePositionError(f"{isin}: corrupt FIFO inventory")
            lot = self.lots[0]
            used = min(lot.shares, remaining)
            fifo_removed += used * lot.cost_per_share
            lot.shares -= used
            remaining -= used
            if lot.shares <= SHARE_TOL:
                self.lots.popleft()
        self.realized_fifo += net_proceeds - fifo_removed
        if self.shares <= SHARE_TOL:
            self.shares = ZERO
            self.wac_basis = ZERO
            self.lots.clear()

    def transformed_lots(self, ratio: Decimal) -> list[_Lot]:
        return [_Lot(l.shares * ratio, l.cost_per_share / ratio, l.timestamp)
                for l in self.lots]

    @property
    def fifo_basis(self) -> Decimal:
        return sum((lot.shares * lot.cost_per_share for lot in self.lots), ZERO)


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _fraction_after(start: datetime, end: datetime, instant: datetime) -> Decimal:
    total = Decimal(str((_utc(end) - _utc(start)).total_seconds()))
    remaining = Decimal(str((_utc(end) - _utc(instant)).total_seconds()))
    if total <= 0:
        raise PerformanceError("non-positive period duration")
    return min(ONE, max(ZERO, remaining / total))


def _validate_context(data: PerformanceEngineInput, context: EngineContext) -> None:
    p = data.evaluation_period
    flow_map = {f.flow_id: f for f in data.cash_flows}
    for lot in context.opening_lots:
        if lot.timestamp.tzinfo is None or lot.timestamp > p.start_date:
            raise PerformanceError("opening lot must be dated on/before start_date with timezone")
    for action in context.corporate_actions:
        if action.timestamp.tzinfo is None or not p.start_date <= action.timestamp <= p.end_date:
            raise PerformanceError("corporate action outside period or without timezone")
    for flow_id in context.noncash_external_flow_ids:
        if flow_id not in flow_map or flow_map[flow_id].classified_type is not FlowType.EXTERNAL_DEPOSIT:
            raise PerformanceError(f"{flow_id}: only EXTERNAL_DEPOSIT may be noncash")
    transfer_values: dict[str, Decimal] = defaultdict(lambda: ZERO)
    seen_transfers: set[str] = set()
    for transfer in context.security_transfers:
        flow = flow_map.get(transfer.flow_id)
        if flow is None or transfer.flow_id not in context.noncash_external_flow_ids:
            raise PerformanceError(f"{transfer.flow_id}: transfer lot must reference marked noncash external deposit")
        if transfer.timestamp.tzinfo is None or _utc(transfer.timestamp) != _utc(flow.timestamp):
            raise PerformanceError(f"{transfer.flow_id}: transfer timestamp must match flow")
        transfer_values[transfer.flow_id] += transfer.market_value
        seen_transfers.add(transfer.flow_id)
    if set(context.noncash_external_flow_ids) != seen_transfers:
        raise PerformanceError("every noncash external flow requires explicit transfer lot(s)")
    for flow_id, value in transfer_values.items():
        if abs(value - flow_map[flow_id].amount) > CASH_TOL:
            raise PerformanceError(f"{flow_id}: securities transfer value does not match external flow amount")
    for flow_id, isin in context.dividend_flow_to_isin.items():
        if flow_id not in flow_map or flow_map[flow_id].classified_type is not FlowType.INTERNAL_DIVIDEND:
            raise PerformanceError(f"{flow_id}: must reference an INTERNAL_DIVIDEND")
        if not isin:
            raise PerformanceError("dividend mapping requires an ISIN")


def _flow_ledger(data: PerformanceEngineInput) -> tuple[list[CashFlowLedgerRow], Decimal, Decimal]:
    p = data.evaluation_period
    rows: list[CashFlowLedgerRow] = []
    net = ZERO
    weighted = ZERO
    for flow in sorted(data.cash_flows, key=lambda f: _utc(f.timestamp)):
        external = flow.classified_type in EXTERNAL_TYPES
        weight = _fraction_after(p.start_date, p.end_date, flow.timestamp) if external else ZERO
        weighted_flow = flow.amount * weight if external else ZERO
        rows.append(CashFlowLedgerRow(
            flow_id=flow.flow_id, timestamp=flow.timestamp,
            classified_type=flow.classified_type, amount=flow.amount,
            is_external_flow=external, dietz_day_weight=weight,
            weighted_flow_amount=weighted_flow,
        ))
        net += flow.amount if external else ZERO
        weighted += weighted_flow
    return rows, net, weighted


def _twr(
    data: PerformanceEngineInput, warnings: list[str]
) -> tuple[Decimal | None, list[TWRStep]]:
    p = data.evaluation_period
    grouped: dict[datetime, Decimal] = defaultdict(lambda: ZERO)
    for flow in data.cash_flows:
        if flow.classified_type in EXTERNAL_TYPES and flow.amount != ZERO:
            grouped[_utc(flow.timestamp)] += flow.amount
    grouped = {k: v for k, v in grouped.items() if v != ZERO}
    marks = {_utc(v.timestamp): v.equity_before_flow for v in data.subperiod_valuations}
    start, end = _utc(p.start_date), _utc(p.end_date)
    missing = sorted(t for t in grouped if t not in marks and t not in {start, end})
    if missing:
        warnings.append("TRUE_TWR_UNAVAILABLE: missing pre-flow valuations: " +
                        ", ".join(t.isoformat() for t in missing) +
                        "; Modified Dietz is an APPROXIMATION")
        return None, []

    prior = data.initial_valuation.total_equity
    product = ONE
    steps: list[TWRStep] = []
    idx = 0

    def segment(before: Decimal, moment: datetime, external_flow: Decimal) -> bool:
        nonlocal idx, product
        if prior == ZERO:
            if before != ZERO:
                warnings.append("TRUE_TWR_UNAVAILABLE: return on zero invested equity is undefined")
                return False
            growth = ONE  # No invested capital and no economic gain before funding.
        else:
            growth = before / prior
        if growth < ZERO:
            warnings.append("TRUE_TWR_UNAVAILABLE: negative subperiod valuation ratio")
            return False
        product *= growth
        idx += 1
        steps.append(TWRStep(
            step_index=idx, flow_timestamp=moment, equity_before=before,
            external_flow=external_flow, subperiod_return=growth - ONE,
            cumulative_twr=product - ONE,
        ))
        return True

    for moment, amount in sorted(grouped.items()):
        if moment == start:
            before = data.initial_valuation.total_equity
        elif moment == end and moment not in marks:
            # Terminal value is post-flow: reconstruct the immediately pre-flow mark.
            before = data.terminal_valuation.total_equity - amount
        else:
            before = marks[moment]
        if before < ZERO:
            warnings.append("TRUE_TWR_UNAVAILABLE: negative pre-flow equity at " + moment.isoformat())
            return None, []
        if not segment(before, moment, amount):
            return None, []
        after = before + amount
        if after < ZERO:
            warnings.append("TRUE_TWR_UNAVAILABLE: negative equity after external flow at " + moment.isoformat())
            return None, []
        prior = after
    if not segment(data.terminal_valuation.total_equity, end, ZERO):
        return None, []
    if data.initial_valuation.total_equity == ZERO and not grouped:
        warnings.append("TRUE_TWR_UNAVAILABLE: no capital and no nonzero external cash flow")
        return None, []
    if prior == ZERO and data.terminal_valuation.total_equity == ZERO and product == ONE:
        # If the portfolio was fully withdrawn, TWR prior to withdrawal remains defined.
        pass
    return product - ONE, steps


def _npv_factory(data: PerformanceEngineInput):
    p = data.evaluation_period
    start = _utc(p.start_date)
    terms: list[tuple[float, float]] = [(-float(data.initial_valuation.total_equity), 0.0)]
    for flow in data.cash_flows:
        if flow.classified_type in EXTERNAL_TYPES and flow.amount != ZERO:
            year_fraction = (_utc(flow.timestamp) - start).total_seconds() / YEAR_SECONDS
            terms.append((-float(flow.amount), year_fraction))
    terminal_fraction = (_utc(p.end_date) - start).total_seconds() / YEAR_SECONDS
    terms.append((float(data.terminal_valuation.total_equity), terminal_fraction))

    def evaluate(rate: float) -> tuple[float, float]:
        if rate <= -1 or not math.isfinite(rate):
            return math.nan, math.nan
        ln = math.log1p(rate)
        values: list[float] = []
        derivs: list[float] = []
        for amount, years in terms:
            try:
                item = amount * math.exp(-years * ln)
                values.append(item)
                derivs.append(-years * item / (1.0 + rate))
            except OverflowError:
                return math.copysign(math.inf, amount), math.nan
        return math.fsum(values), math.fsum(derivs)

    return evaluate


def _hybrid_root(fn: Any, low: float, high: float) -> float | None:
    fl, _ = fn(low)
    fh, _ = fn(high)
    if math.isnan(fl) or math.isnan(fh) or fl * fh > 0:
        return None
    if abs(fl) < NPV_TOL:
        return low
    if abs(fh) < NPV_TOL:
        return high
    x = min(max(0.0, low), high)
    for _ in range(256):
        fx, derivative = fn(x)
        if math.isfinite(fx) and abs(fx) < NPV_TOL:
            return x
        if not math.isfinite(fx):
            x = (low + high) / 2.0
            fx, derivative = fn(x)
            if not math.isfinite(fx):
                return None
        if (fl < 0 < fx) or (fl > 0 > fx):
            high, fh = x, fx
        else:
            low, fl = x, fx
        if high - low <= 1e-14 * max(1.0, abs(x)):
            mid = (high + low) / 2.0
            residual, _ = fn(mid)
            return mid if math.isfinite(residual) and abs(residual) < NPV_TOL else None
        # Guarded Newton, with bisection fallback.
        candidate = x - fx / derivative if math.isfinite(derivative) and derivative != 0 else math.nan
        margin = (high - low) * 0.05
        x = candidate if math.isfinite(candidate) and low + margin < candidate < high - margin else (low + high) / 2.0
    return None


def _xirr(data: PerformanceEngineInput, warnings: list[str]) -> tuple[Decimal | None, str]:
    # Bracket strictly specified as [-0.99, +5.0]; scan because NPV can have
    # more than one root when deposits and withdrawals alternate.
    values = [-float(data.initial_valuation.total_equity),
              *(-float(f.amount) for f in data.cash_flows
                if f.classified_type in EXTERNAL_TYPES and f.amount != ZERO),
              float(data.terminal_valuation.total_equity)]
    if all(x == 0.0 for x in values):
        warnings.append("XIRR_UNDEFINED: identically zero cash-flow sequence")
        return None, "ROOT_NOT_FOUND"
    if not any(x > 0 for x in values) or not any(x < 0 for x in values):
        warnings.append("XIRR_UNDEFINED: NPV does not have both cash-flow signs")
        return None, "ROOT_NOT_FOUND"
    fn = _npv_factory(data)
    # Uniform in log(1+r) samples both near -1 and at high rates.
    lo_ln, hi_ln = math.log1p(-0.99), math.log1p(5.0)
    sampled = [math.expm1(lo_ln + (hi_ln - lo_ln) * k / 1024) for k in range(1025)]
    sampled.append(0.0)
    sampled = sorted(set(sampled))
    roots: list[float] = []
    previous = sampled[0]
    fp, _ = fn(previous)
    for current in sampled[1:]:
        fc, _ = fn(current)
        if math.isfinite(fp) and abs(fp) < NPV_TOL:
            roots.append(previous)
        if (math.isfinite(fp) and math.isfinite(fc) and
                ((fp < 0 < fc) or (fp > 0 > fc))):
            root = _hybrid_root(fn, previous, current)
            if root is not None:
                roots.append(root)
        previous, fp = current, fc
    if math.isfinite(fp) and abs(fp) < NPV_TOL:
        roots.append(previous)
    roots.sort()
    unique: list[float] = []
    for r in roots:
        if not unique or abs(r - unique[-1]) > 1e-9:
            unique.append(r)
    if not unique:
        warnings.append("XIRR_ROOT_NOT_FOUND: no verified root in [-0.99, 5.0]")
        return None, "ROOT_NOT_FOUND"
    if len(unique) > 1:
        warnings.append(f"XIRR_MULTIPLE_ROOTS: {len(unique)} roots; selected nearest zero")
    root = min(unique, key=lambda r: (abs(r), r))
    residual, _ = fn(root)
    if not math.isfinite(residual) or abs(residual) >= NPV_TOL:
        warnings.append("XIRR_ROOT_NOT_FOUND: root failed absolute NPV verification")
        return None, "ROOT_NOT_FOUND"
    if data.evaluation_period.calendar_days < 90:
        period_years = (
            _utc(data.evaluation_period.end_date) - _utc(data.evaluation_period.start_date)
        ).total_seconds() / YEAR_SECONDS
        period_return = math.expm1(period_years * math.log1p(root))
        warnings.append("XIRR_SUB_ANNUAL: xirr_annualized_pct holds unannualized PERIOD return")
        return Decimal(str(period_return * 100.0)), "SUB_ANNUAL_UNANNUALIZED"
    return Decimal(str(root * 100.0)), "CONVERGED"


def _reconstruct_inventory(
    data: PerformanceEngineInput, context: EngineContext, warnings: list[str]
) -> tuple[list[PositionCostBasis], list[CostBasisAudit], bool]:
    holdings: dict[str, _Holding] = defaultdict(_Holding)
    used_opening_context = bool(context.opening_lots)
    opening_unknown = data.initial_valuation.positions_value > ZERO and not used_opening_context
    if opening_unknown:
        if data.transactions or context.corporate_actions:
            raise PerformanceError(
                "Opening securities exist but opening_lots are unavailable; "
                "FIFO/WAC cannot be determined from in-period trades alone"
            )
        warnings.append("OPENING_LOTS_UNAVAILABLE: opening securities cannot be cost-accounted")
    for lot in sorted(context.opening_lots, key=lambda x: (_utc(x.timestamp), x.isin)):
        holdings[lot.isin].buy(lot.shares, lot.shares * lot.cost_per_share,
                               lot.timestamp, opening=True)

    # Corporate actions are optional context because the locked schema has no
    # corresponding input field. Cost and acquisition order must be preserved.
    events: list[tuple[datetime, int, int, Any]] = []
    for i, action in enumerate(context.corporate_actions):
        events.append((_utc(action.timestamp), 0, i, action))
    for i, transfer in enumerate(context.security_transfers):
        events.append((_utc(transfer.timestamp), 1, i, transfer))
    for i, tx in enumerate(data.transactions):
        events.append((_utc(tx.timestamp), 2, i, tx))
    for _when, _priority, _index, event in sorted(events):
        if isinstance(event, SecurityTransfer):
            holdings[event.isin].buy(
                event.shares, event.shares * event.cost_per_share,
                event.timestamp, opening=False,
            )
            continue
        if isinstance(event, Transaction):
            h = holdings[event.isin]
            if event.side is Side.BUY:
                basis = (event.shares * event.execution_price + event.fees + event.taxes)
                h.buy(event.shares, basis, event.timestamp, opening=False)
            else:
                proceeds = event.shares * event.execution_price - event.fees - event.taxes
                h.sell(event.shares, proceeds, isin=event.isin)
            continue
        old = holdings[event.isin]
        if old.shares <= ZERO:
            raise NegativePositionError(f"corporate action on empty position {event.isin}")
        if event.action_type is CorporateActionType.SPLIT:
            old.shares *= event.ratio
            old.lots = deque(old.transformed_lots(event.ratio))
            # WAC total basis stays the same; FIFO each lot basis stays the same.
        else:
            new = holdings[event.new_isin]
            new.shares += old.shares * event.ratio
            new.wac_basis += old.wac_basis
            new.lots.extend(old.transformed_lots(event.ratio))
            new.lots = deque(sorted(new.lots, key=lambda x: _utc(x.timestamp)))
            # Carry gain/cost audit records with original shares (no gain/loss).
            new.opening_cost += old.opening_cost
            new.purchases += old.purchases
            new.net_proceeds += old.net_proceeds
            new.realized_fifo += old.realized_fifo
            new.realized_wac += old.realized_wac
            holdings.pop(event.isin)

    dividends: dict[str, Decimal] = defaultdict(lambda: ZERO)
    unknown_dividends = []
    for flow in data.cash_flows:
        if flow.classified_type is FlowType.INTERNAL_DIVIDEND:
            isin = context.dividend_flow_to_isin.get(flow.flow_id)
            if isin:
                dividends[isin] += flow.amount
            elif flow.amount != ZERO:
                unknown_dividends.append(flow.flow_id)
    if unknown_dividends:
        warnings.append("DIVIDENDS_UNALLOCATED: missing ISIN for flow IDs " +
                        ", ".join(sorted(unknown_dividends)))

    active = sorted(isin for isin, h in holdings.items() if h.shares > ZERO)
    total_mark = data.terminal_valuation.positions_value
    marks = dict(context.terminal_position_values)
    unknown_marks = set(marks) - set(active)
    if unknown_marks:
        if any(marks[i] != ZERO for i in unknown_marks):
            raise MissingMarketDataError("valuation for non-open ISIN(s): " + ", ".join(sorted(unknown_marks)))
        for i in unknown_marks:
            marks.pop(i)
    missing_marks = [i for i in active if i not in marks]
    remainder = total_mark - sum(marks.values(), ZERO)
    if remainder < -CASH_TOL:
        raise MissingMarketDataError("per-ISIN valuations exceed terminal positions_value")
    if len(missing_marks) == 1:
        if remainder < ZERO:
            raise MissingMarketDataError("negative residual position valuation")
        marks[missing_marks[0]] = remainder
    elif len(missing_marks) > 1:
        if total_mark == ZERO:
            marks.update({isin: ZERO for isin in missing_marks})
        else:
            raise MissingMarketDataError(
                "multiple open ISINs cannot be valued from one aggregate positions_value; "
                "provide context.terminal_position_values for all but one"
            )
    elif abs(remainder) > CASH_TOL and not opening_unknown:
        raise MissingMarketDataError("sum of ISIN valuations does not equal terminal positions_value")

    positions: list[PositionCostBasis] = []
    audits: list[CostBasisAudit] = []
    for isin in sorted(set(holdings) | set(dividends)):
        h = holdings[isin]
        equity = marks.get(isin, ZERO)
        if h.shares == ZERO and equity != ZERO:
            raise MissingMarketDataError(f"closed position {isin} cannot have market valuation")
        avg = h.wac_basis / h.shares if h.shares else ZERO
        fifo = h.fifo_basis / h.shares if h.shares else ZERO
        unreal_wac, unreal_fifo = equity - h.wac_basis, equity - h.fifo_basis
        positions.append(PositionCostBasis(
            isin=isin, shares=h.shares, current_valuation=equity,
            wac_cost_per_share=avg, wac_unrealized_pnl=unreal_wac,
            fifo_cost_per_share=fifo, fifo_unrealized_pnl=unreal_fifo,
            fifo_open_lots_count=len(h.lots), period_realized_pnl=h.realized_fifo,
            period_dividends=dividends[isin],
        ))
        audits.append(CostBasisAudit(
            isin=isin, opening_acquisition_cost=h.opening_cost,
            purchase_cost_in_period=h.purchases, net_sale_proceeds_in_period=h.net_proceeds,
            wac_realized_pnl=h.realized_wac, fifo_realized_pnl=h.realized_fifo,
            wac_remaining_basis=h.wac_basis, fifo_remaining_basis=h.fifo_basis,
            wac_unrealized_pnl=unreal_wac, fifo_unrealized_pnl=unreal_fifo,
        ))
        # Internally provable cost/proceeds/mark identity, for both methods.
        total_spent = h.opening_cost + h.purchases
        for remaining_basis, realized, unreal in (
            (h.wac_basis, h.realized_wac, unreal_wac),
            (h.fifo_basis, h.realized_fifo, unreal_fifo),
        ):
            # net proceeds + market value = total original cost + PnL
            if abs(h.net_proceeds + equity - total_spent - realized - unreal) > CASH_TOL:
                raise PerformanceError(f"cost conservation failed for ISIN {isin}")
        if abs(h.wac_basis - h.fifo_basis) > CASH_TOL:
            warnings.append(f"WAC_FIFO_BASIS_DIFFER: {isin}; FIFO period_realized_pnl used in strict output")
    if opening_unknown:
        if total_mark != ZERO:
            warnings.append("POSITION_RECONCILIATION_INCOMPLETE: unknown opening inventory")
        return positions, audits, False
    if abs(sum((p.current_valuation for p in positions), ZERO) - total_mark) > CASH_TOL:
        warnings.append("POSITION_VALUE_GAP: reconstructed sum != terminal positions_value")
        return positions, audits, False
    return positions, audits, True


def _cash_reconcile(
    data: PerformanceEngineInput, context: EngineContext, warnings: list[str]
) -> tuple[Decimal, bool]:
    running = data.initial_valuation.cash_balance
    if running < ZERO:
        warnings.append("NEGATIVE_CASH_BALANCE: opening cash balance is negative")
    movements: dict[datetime, Decimal] = defaultdict(lambda: ZERO)
    internal_trade_cash = ZERO
    for flow in data.cash_flows:
        if flow.classified_type in EXTERNAL_TYPES:
            if flow.flow_id not in context.noncash_external_flow_ids:
                movements[_utc(flow.timestamp)] += flow.amount
        elif flow.classified_type is FlowType.INTERNAL_DIVIDEND:
            movements[_utc(flow.timestamp)] += flow.amount
        else:
            # INTERNAL_TRADE_CASH is documentary of the corresponding trade.
            internal_trade_cash += flow.amount
    sum_transactions = ZERO
    for transaction in data.transactions:
        movements[_utc(transaction.timestamp)] += transaction.total_cash_impact
        sum_transactions += transaction.total_cash_impact
    if internal_trade_cash != ZERO and abs(internal_trade_cash - sum_transactions) > CASH_TOL:
        warnings.append("INTERNAL_TRADE_CASH_MISMATCH: ledger rows are documentary, not booked twice")
    went_negative = running < ZERO
    for instant, delta in sorted(movements.items()):
        running += delta
        if running < -CASH_TOL:
            went_negative = True
            warnings.append("NEGATIVE_CASH_BALANCE: computed cash at " + instant.isoformat())
    gap = data.terminal_valuation.cash_balance - running
    if abs(gap) > CASH_TOL:
        warnings.append(f"UNEXPLAINED_CASH_GAP: {gap}; not booked as return, tax or fictitious flow")
    return gap, went_negative


def _coerce_payload(payload: PerformanceEngineInput | Mapping[str, Any] | str | bytes) -> PerformanceEngineInput:
    if isinstance(payload, PerformanceEngineInput):
        return payload
    if isinstance(payload, (str, bytes)):
        return PerformanceEngineInput.model_validate_json(payload)
    return PerformanceEngineInput.model_validate(payload)


def _coerce_context(context: EngineContext | Mapping[str, Any] | str | bytes | None) -> EngineContext:
    if context is None:
        return EngineContext()
    if isinstance(context, EngineContext):
        return context
    if isinstance(context, (str, bytes)):
        return EngineContext.model_validate_json(context)
    return EngineContext.model_validate(context)


def _compute(
    payload: PerformanceEngineInput | Mapping[str, Any] | str | bytes,
    context: EngineContext | Mapping[str, Any] | str | bytes | None,
) -> tuple[PerformanceEngineOutput, list[CostBasisAudit]]:
    data, supplementary = _coerce_payload(payload), _coerce_context(context)
    _validate_context(data, supplementary)
    warnings: list[str] = []
    start, end = data.initial_valuation.total_equity, data.terminal_valuation.total_equity
    ledger, net_flow, weighted = _flow_ledger(data)
    gain = end - start - net_flow
    denom = start + weighted
    dietz: Decimal | None = None
    if data.accounting_options.compute_modified_dietz:
        if denom <= ZERO:
            warnings.append("MODIFIED_DIETZ_UNDEFINED: weighted capital base <= 0")
        else:
            dietz = gain / denom * Decimal(100)

    twr_value: Decimal | None = None
    twr_steps: list[TWRStep] = []
    twr_annualized: Decimal | None = None
    if data.accounting_options.compute_true_twr:
        twr_value, twr_steps = _twr(data, warnings)
        if twr_value is not None and data.evaluation_period.calendar_days > data.accounting_options.annualize_threshold_days:
            base = ONE + twr_value
            if base > ZERO:
                # Approximation only at exponentiation/JSON boundary; all cash
                # and cost calculations above remain exact Decimals.
                years = 365.25 / data.evaluation_period.calendar_days
                twr_annualized = Decimal(str(math.expm1(years * math.log(float(base))))) * 100
            elif base == ZERO:
                twr_annualized = Decimal(-100)
            else:
                warnings.append("TRUE_TWR_ANNUALIZATION_UNDEFINED: cumulative factor below zero")
    elif data.accounting_options.compute_modified_dietz:
        warnings.append("TRUE_TWR_NOT_REQUESTED: Modified Dietz is an APPROXIMATION")

    xirr, status = (None, "NOT_REQUESTED")
    if data.accounting_options.compute_xirr:
        xirr, status = _xirr(data, warnings)

    pos_rows, audits, inventory_balanced = _reconstruct_inventory(data, supplementary, warnings)
    cash_gap, cash_negative = _cash_reconcile(data, supplementary, warnings)
    initial_identity = start - (data.initial_valuation.cash_balance + data.initial_valuation.positions_value)
    terminal_identity = end - (data.terminal_valuation.cash_balance + data.terminal_valuation.positions_value)
    if abs(initial_identity) > CASH_TOL:
        warnings.append(f"OPENING_EQUITY_GAP: total_equity - cash - positions = {initial_identity}")
    if abs(terminal_identity) > CASH_TOL:
        warnings.append(f"TERMINAL_EQUITY_GAP: total_equity - cash - positions = {terminal_identity}")
    if cash_negative:
        warnings.append("NEGATIVE_BALANCE_PROTECTION: verify broker overdraft/margin; no artificial offset posted")
    if not data.accounting_options.compute_modified_dietz and not data.accounting_options.compute_true_twr:
        warnings.append("NO_TIME_WEIGHTED_METRIC_REQUESTED")
    if (twr_value is None and data.accounting_options.compute_true_twr and
            dietz is not None):
        warnings.append("APPROXIMATION: Modified Dietz is not True TWR")

    is_balanced = (
        abs(cash_gap) <= CASH_TOL
        and abs(initial_identity) <= CASH_TOL
        and abs(terminal_identity) <= CASH_TOL
        and inventory_balanced
        and not cash_negative
    )
    output = PerformanceEngineOutput(
        engine_metadata=EngineMetadata(
            calculation_timestamp=datetime.now(timezone.utc),
            period_start=data.evaluation_period.start_date,
            period_end=data.evaluation_period.end_date,
            calendar_days=data.evaluation_period.calendar_days,
        ),
        returns_summary=ReturnsSummary(
            start_equity=start, end_equity=end, net_external_flow=net_flow,
            absolute_gain_loss=gain, modified_dietz_pct=dietz,
            dietz_capital_base=denom if data.accounting_options.compute_modified_dietz else None,
            true_twr_cumulative_pct=twr_value * 100 if twr_value is not None else None,
            true_twr_annualized_pct=twr_annualized,
            xirr_annualized_pct=xirr, xirr_convergence_status=status,
        ),
        cash_flow_ledger=ledger,
        position_cost_basis=pos_rows,
        subperiod_twr_steps=twr_steps,
        reconciliation_diagnostics=ReconciliationDiagnostics(
            unexplained_cash_gap=cash_gap,
            is_balanced=is_balanced,
            warnings=list(dict.fromkeys(warnings)),
        ),
    )
    return output, audits


def calculate_performance(
    payload: PerformanceEngineInput | Mapping[str, Any] | str | bytes,
    *,
    context: EngineContext | Mapping[str, Any] | str | bytes | None = None,
) -> PerformanceEngineOutput:
    """Pure and read-only strict-JSON spec engine; does not mutate input/state."""
    return _compute(payload, context)[0]


def audit_cost_basis(
    payload: PerformanceEngineInput | Mapping[str, Any] | str | bytes,
    *,
    context: EngineContext | Mapping[str, Any] | str | bytes | None = None,
) -> list[CostBasisAudit]:
    """Separate WAC/FIFO audit facts not representable in the locked output schema."""
    return _compute(payload, context)[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="strict PerformanceEngineInput JSON")
    parser.add_argument("--context", type=Path, help="optional separate EngineContext JSON")
    parser.add_argument("-o", "--output", type=Path, help="output path (otherwise stdout)")
    parser.add_argument("--audit", type=Path, help="optional WAC/FIFO audit JSON path")
    args = parser.parse_args(argv)
    try:
        input_data = args.input.read_text(encoding="utf-8")
        context_data = args.context.read_text(encoding="utf-8") if args.context else None
        result, audit = _compute(input_data, context_data)
        serialized = result.model_dump_json(indent=2)
        if args.output:
            args.output.write_text(serialized + "\n", encoding="utf-8")
        else:
            print(serialized)
        if args.audit:
            args.audit.write_text(
                json.dumps([row.model_dump(mode="json") for row in audit],
                           indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    except (OSError, ValidationError, PerformanceError, ValueError) as exc:
        parser.exit(2, f"performance_engine error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
