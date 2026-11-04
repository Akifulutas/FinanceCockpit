"""Rule-based, broker-independent portfolio rebalancing engine.

Implements SPEC-PROMPT-REBAL-001 (v1.0.0). Python >=3.11, Pydantic >=2.
All internal monetary and quantity calculations use Decimal; JSON values are
numbers, never Decimal-encoded strings. The engine ONLY creates a plan.

Input:  RebalancingInput.model_validate_json(payload)
Output: output.model_dump_json(indent=2)
Convenience: rebalance_json(payload)
CLI: python rebalancing.py portfolio.json   (or pipe JSON to stdin)

Policy extensions (optional, backward compatible):
  - Position.quantity_step: executable share increment (1 by default; use
    0.001 etc. only for brokers permitting fractional ETF/Sparplan execution).
  - Position.trading_status / quote_as_of: freeze untradable or stale assets.
  - RebalancePolicy.estimated_fee_per_order_eur, max_quote_age_seconds,
    tax_enabled, tax_lock_portfolio_fraction: execution safeguards.

A trading plan is not a live broker order or a guarantee of fill/settlement.
When tax_enabled=False (default), no tax-basis data is needed and all estimated
TaxCost fields are zero. Enabled tax is a rough *reserve*, not German tax advice.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

D0 = Decimal("0")
D1 = Decimal("1")
CENT = Decimal("0.01")
EPS = Decimal("0.000000001")


def dec(value: Any) -> Decimal:
    """Convert numeric data without binary-floating-point arithmetic."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def number(value: Decimal, places: int = 10) -> float:
    quantum = D1.scaleb(-places)
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


def floor_step(amount: Decimal, step: Decimal) -> Decimal:
    if amount <= D0:
        return D0
    return (amount / step).to_integral_value(rounding=ROUND_DOWN) * step


def require_number(value: Any) -> Any:
    """Match JSON Schema type:number: reject numeric strings and booleans."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        raise ValueError("Expected a JSON number, not a string or boolean")
    return value


JsonNumber = Annotated[Decimal, BeforeValidator(require_number)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RebalanceMode(str, Enum):
    INFLOW_ONLY = "INFLOW_ONLY"
    FULL_REBALANCE = "FULL_REBALANCE"
    TAX_MINIMIZED = "TAX_MINIMIZED"


class TradingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    STALE = "STALE"


class Phase(str, Enum):
    PHASE_1_SELL = "PHASE_1_SELL"
    PHASE_2_BUY = "PHASE_2_BUY"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SuppressionReason(str, Enum):
    BELOW_MIN_TICKET_SIZE = "BELOW_MIN_TICKET_SIZE"
    WITHIN_TOLERANCE_BAND = "WITHIN_TOLERANCE_BAND"
    TURNOVER_CAPPED = "TURNOVER_CAPPED"
    SELLING_PROHIBITED = "SELLING_PROHIBITED"


class Position(StrictModel):
    isin: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    name: str = Field(min_length=1)
    shares: JsonNumber = Field(ge=0)
    quote_mid: JsonNumber = Field(gt=0)
    bid: JsonNumber = Field(gt=0)
    ask: JsonNumber = Field(gt=0)
    valuation: JsonNumber = Field(ge=0)
    current_weight: JsonNumber = Field(ge=0, le=1)
    unrealized_gain: JsonNumber | None = None
    cost_basis_per_share: JsonNumber | None = Field(default=None, ge=0)
    quantity_step: JsonNumber = Field(default=D1, gt=0)
    trading_status: TradingStatus = TradingStatus.ACTIVE
    quote_as_of: datetime | None = None

    @model_validator(mode="after")
    def validate_quote(self) -> Position:
        if not (self.bid <= self.quote_mid <= self.ask):
            raise ValueError(f"{self.isin}: require bid <= quote_mid <= ask")
        if self.quote_as_of is not None and self.quote_as_of.utcoffset() is None:
            raise ValueError(f"{self.isin}: quote_as_of must be timezone-aware")
        if self.shares == 0 and self.valuation != 0:
            raise ValueError(f"{self.isin}: nonzero valuation with zero shares")
        if self.shares > 0 and self.valuation == 0:
            raise ValueError(f"{self.isin}: zero valuation with positive shares")
        return self


class RebalancePolicy(StrictModel):
    rebalance_mode: RebalanceMode = RebalanceMode.FULL_REBALANCE
    absolute_tolerance_band: JsonNumber = Field(ge=0, le=1)
    relative_tolerance_band: JsonNumber = Field(ge=0, le=1)
    min_trade_ticket_eur: JsonNumber = Field(gt=0)
    max_portfolio_turnover: JsonNumber = Field(default=Decimal("0.20"), ge=0, le=1)
    allow_selling: bool = True
    target_cash_weight: JsonNumber = Field(default=Decimal("0.01"), ge=0, le=1)
    estimated_tax_rate: JsonNumber = Field(default=Decimal("0.26375"), ge=0, le=1)
    tax_enabled: bool = False
    tax_lock_portfolio_fraction: JsonNumber = Field(default=Decimal("0.05"), ge=0, le=1)
    estimated_fee_per_order_eur: JsonNumber = Field(default=D0, ge=0)
    max_quote_age_seconds: int = Field(default=900, ge=0)


class RebalancingInput(StrictModel):
    as_of: datetime
    portfolio_id: str = Field(min_length=1)
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    available_cash: JsonNumber = Field(ge=0)
    new_cash_injection: JsonNumber = Field(default=D0, ge=0)
    positions: list[Position]
    target_weights: dict[str, JsonNumber]
    rebalance_policy: RebalancePolicy

    @field_validator("target_weights")
    @classmethod
    def check_target_weights(cls, weights: dict[str, JsonNumber]) -> dict[str, JsonNumber]:
        if any(not key for key in weights):
            raise ValueError("Target ISIN must not be blank")
        if any(weight < 0 or weight > 1 for weight in weights.values()):
            raise ValueError("Target weights must lie in [0, 1]")
        if sum(weights.values(), D0) > D1 + EPS:
            raise ValueError("Sum of security target weights cannot exceed 1")
        return weights

    @model_validator(mode="after")
    def validate_snapshot(self) -> RebalancingInput:
        if self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset")
        if self.base_currency != "EUR":
            raise ValueError("Only EUR portfolios supported: min ticket, fee and taxes are EUR")
        isins = [p.isin for p in self.positions]
        if len(isins) != len(set(isins)):
            raise ValueError("Duplicate position ISINs")
        unknown = [isin for isin, w in self.target_weights.items() if w > 0 and isin not in set(isins)]
        if unknown:
            raise ValueError(f"Missing position+price quotes for target ISIN(s): {unknown}")
        return self


class RebalanceSummary(StrictModel):
    initial_portfolio_value: float
    projected_portfolio_value: float
    total_buy_volume: float
    total_sell_volume: float
    net_cash_impact: float
    projected_turnover_pct: float
    estimated_spread_drag_eur: float
    estimated_tax_impact_eur: float


class ExecutionOrder(StrictModel):
    execution_sequence: int = Field(ge=1)
    phase: Phase
    isin: str
    ticker: str
    action: Action
    shares_delta: float
    target_price: float
    estimated_amount: float
    spread_drag_eur: float
    tax_impact_eur: float
    rationale: str


class PostRebalanceDrift(StrictModel):
    isin: str
    ticker: str
    current_weight: float
    target_weight: float
    projected_weight: float
    remaining_drift: float


class SuppressedTrade(StrictModel):
    isin: str
    action: Action
    calculated_amount: float
    suppression_reason: SuppressionReason


class RebalancingOutput(StrictModel):
    plan_id: str
    timestamp_utc: datetime
    rebalance_triggered: bool
    trigger_rationale: str
    rebalance_summary: RebalanceSummary
    ordered_execution_plan: list[ExecutionOrder]
    post_rebalance_drift: list[PostRebalanceDrift]
    suppressed_trades: list[SuppressedTrade]


class _Candidate:
    __slots__ = ("position", "action", "mid_amount", "drift")

    def __init__(self, p: Position, action: Action, mid_amount: Decimal, drift: Decimal):
        self.position = p
        self.action = action
        self.mid_amount = mid_amount
        self.drift = drift


def _tax_reserve(p: Position, shares: Decimal, policy: RebalancePolicy) -> Decimal | None:
    """None means tax enabled but no basis available: selling is blocked."""
    if not policy.tax_enabled:
        return D0
    if p.unrealized_gain is not None:
        gain = max(D0, p.unrealized_gain) * shares / p.shares if p.shares else D0
    elif p.cost_basis_per_share is not None:
        gain = max(D0, (p.bid - p.cost_basis_per_share) * shares)
    else:
        return None
    return gain * policy.estimated_tax_rate


def _freeze_reason(p: Position, as_of: datetime, policy: RebalancePolicy) -> str | None:
    if p.trading_status != TradingStatus.ACTIVE:
        return p.trading_status.value
    if p.quote_as_of is not None:
        age = (as_of - p.quote_as_of).total_seconds()
        if age < 0 or age > policy.max_quote_age_seconds:
            return "STALE_QUOTE"
    return None


def _effective_targets(
    data: RebalancingInput, total: Decimal, frozen: set[str]
) -> dict[str, JsonNumber]:
    """Target values, normalized across liquid assets ONLY if some are frozen."""
    base = {p.isin: data.target_weights.get(p.isin, D0) * total for p in data.positions}
    if not frozen:
        return base
    frozen_value = sum((p.valuation for p in data.positions if p.isin in frozen), D0)
    reserve = total * data.rebalance_policy.target_cash_weight
    active_weight = sum(
        (data.target_weights.get(p.isin, D0) for p in data.positions if p.isin not in frozen), D0
    )
    # Frozen positions consume portfolio capital; no forced liquidation is possible.
    active_target_budget = max(D0, sum(data.target_weights.values(), D0) * total - frozen_value)
    active_target_budget = min(active_target_budget, max(D0, total - reserve - frozen_value))
    for p in data.positions:
        if p.isin in frozen:
            base[p.isin] = p.valuation
        else:
            base[p.isin] = (
                active_target_budget * data.target_weights.get(p.isin, D0) / active_weight
                if active_weight > 0 else D0
            )
    return base


def _suppress(
    items: list[SuppressedTrade], isin: str, action: Action,
    amount: Decimal, reason: SuppressionReason,
) -> None:
    if amount > EPS:
        items.append(SuppressedTrade(
            isin=isin, action=action, calculated_amount=money(amount), suppression_reason=reason
        ))


def _greedy_steps(cands: list["_Candidate"], budget: Decimal, policy: "RebalancePolicy") -> dict[str, Decimal]:
    """Integer-step allocation of a cash budget to underweight positions.

    Each round gives one quantity_step to the candidate with the largest remaining
    gap that is still affordable (ask price + one order fee for a new order). A
    position may overshoot its gap by at most one step. Positions whose final
    ticket stays below min_trade_ticket_eur are dropped and the budget re-spread.
    Returns desired mid-price amounts, which trade() converts back to whole steps.
    """
    active = [c for c in cands if c.mid_amount > EPS]
    while True:
        steps: dict[str, Decimal] = {c.position.isin: D0 for c in active}
        left = budget
        while True:
            best = None
            for c in active:
                p = c.position
                remaining = c.mid_amount - steps[p.isin] * p.quantity_step * p.quote_mid
                cost = p.quantity_step * p.ask + (policy.estimated_fee_per_order_eur if steps[p.isin] == 0 else D0)
                if remaining > EPS and cost <= left + EPS:
                    if best is None or remaining > best[0]:
                        best = (remaining, c, cost)
            if best is None:
                break
            _, c, cost = best
            steps[c.position.isin] += 1
            left -= cost
        too_small = [c for c in active if D0 < steps[c.position.isin] * c.position.quantity_step * c.position.ask
                     < policy.min_trade_ticket_eur]
        if not too_small:
            return {c.position.isin: steps[c.position.isin] * c.position.quantity_step * c.position.quote_mid
                    for c in active}
        active = [c for c in active if c not in too_small]


def _calculate(data: RebalancingInput) -> RebalancingOutput:
    policy = data.rebalance_policy
    initial = sum((p.valuation for p in data.positions), D0) + data.available_cash
    total = initial + data.new_cash_injection
    start_cash = data.available_cash + data.new_cash_injection
    frozen = {p.isin: _freeze_reason(p, data.as_of, policy)
              for p in data.positions if _freeze_reason(p, data.as_of, policy) is not None}
    frozen_ids = set(frozen)
    targets = _effective_targets(data, total, frozen_ids)
    reserve = total * policy.target_cash_weight
    suppressed: list[SuppressedTrade] = []
    notes: list[str] = []
    if frozen:
        notes.append("İşleme kapalı / güncel olmayan: " + ", ".join(
            f"{isin} ({why})" for isin, why in sorted(frozen.items())) +
            "; pozisyonlar sabit tutuldu, işlem yapılabilir hedefler normalize edildi.")
    if not data.positions:
        notes.append("Pozisyon verisi bulunmuyor.")
    if total <= 0:
        notes.append("Toplam portföy değeri sıfır; emir üretilemez.")

    triggered: list[_Candidate] = []
    cash_buys: list[_Candidate] = []  # within band, but funded only by idle cash / new inflow
    deployable = max(D0, start_cash - reserve)
    for p in data.positions:
        if p.isin in frozen_ids or total <= 0:
            continue
        target = targets[p.isin]
        gap = target - p.valuation
        drift = abs(gap) / total
        target_weight = target / total
        relative = drift / target_weight if target_weight > 0 else Decimal("Infinity")
        action = Action.BUY if gap > 0 else Action.SELL
        if abs(gap) <= EPS:
            continue
        if not (drift > policy.absolute_tolerance_band and
                relative > policy.relative_tolerance_band):
            # Tolerance bands discipline trades that must be FUNDED BY SALES. New money
            # (and idle cash above the reserve) is always steered toward underweights.
            if action == Action.BUY and deployable > EPS:
                cash_buys.append(_Candidate(p, action, abs(gap), drift))
            else:
                _suppress(suppressed, p.isin, action, abs(gap), SuppressionReason.WITHIN_TOLERANCE_BAND)
            continue
        if action == Action.SELL and (not policy.allow_selling or
                                      policy.rebalance_mode == RebalanceMode.INFLOW_ONLY):
            _suppress(suppressed, p.isin, action, abs(gap), SuppressionReason.SELLING_PROHIBITED)
            continue
        triggered.append(_Candidate(p, action, abs(gap), drift))

    buys = sorted((c for c in triggered if c.action == Action.BUY),
                  key=lambda c: (-c.drift, c.position.isin))
    sells = sorted((c for c in triggered if c.action == Action.SELL),
                   key=lambda c: (-c.drift, c.position.isin))
    requested: dict[str, JsonNumber] = {}
    if policy.rebalance_mode == RebalanceMode.INFLOW_ONLY or not policy.allow_selling:
        # SPEC 4.5: use *new* inflow, not old cash, allocating proportionally to gaps.
        buys = sorted(buys + cash_buys, key=lambda c: (-c.drift, c.position.isin))
        inflow = min(data.new_cash_injection, max(D0, start_cash - reserve))
        requested.update(_greedy_steps(buys, inflow, policy))
        if buys and inflow <= 0:
            notes.append("Yeni nakit girişi / korunacak nakit rezervi nedeniyle alım bütçesi yok.")
    else:
        requested = {c.position.isin: c.mid_amount for c in buys + sells}
        if policy.rebalance_mode == RebalanceMode.TAX_MINIMIZED:
            # Prioritize all cash already available and new inflows before any sale.
            liquid_cash = max(D0, start_cash - reserve)
            buy_need = sum((c.mid_amount * c.position.ask / c.position.quote_mid
                            + policy.estimated_fee_per_order_eur for c in buys), D0)
            sale_shortfall = max(D0, buy_need - liquid_cash)
            sold = D0

            def tax_per_eur(c: _Candidate) -> Decimal:
                shares = min(c.position.shares, c.mid_amount / c.position.quote_mid)
                estimate = _tax_reserve(c.position, shares, policy)
                if estimate is None:
                    return Decimal("Infinity")
                proceeds = shares * c.position.bid
                return estimate / proceeds if proceeds > 0 else Decimal("Infinity")

            sells.sort(key=lambda c: (tax_per_eur(c), -c.drift, c.position.isin))
            for c in sells:
                p = c.position
                full_shares = min(p.shares, c.mid_amount / p.quote_mid)
                expected_tax = _tax_reserve(p, full_shares, policy)
                if expected_tax is None or expected_tax > total * policy.tax_lock_portfolio_fraction:
                    _suppress(suppressed, p.isin, Action.SELL, c.mid_amount,
                              SuppressionReason.SELLING_PROHIBITED)
                    requested[p.isin] = D0
                    notes.append(f"{p.isin}: tax-lock veya vergi matrahı eksik; satış atlandı.")
                    continue
                # Estimate liquidity net of executable bid, tax and order fee.
                per_mid = p.bid / p.quote_mid - (expected_tax / c.mid_amount)
                if per_mid <= 0:
                    requested[p.isin] = D0
                    continue
                allocation = min(c.mid_amount, max(D0,
                    (sale_shortfall - sold + policy.estimated_fee_per_order_eur) / per_mid))
                requested[p.isin] = allocation
                sold += max(D0, allocation * per_mid - policy.estimated_fee_per_order_eur)
            if sale_shortfall <= 0:
                notes.append("TAX_MINIMIZED: nakit yeterli; kârlı pozisyonlar satılmadı.")

    if cash_buys and not (policy.rebalance_mode == RebalanceMode.INFLOW_ONLY or not policy.allow_selling):
        triggered_need = D0
        for c in buys:
            q = floor_step(requested.get(c.position.isin, D0) / c.position.quote_mid, c.position.quantity_step)
            if q > 0:
                triggered_need += q * c.position.ask + policy.estimated_fee_per_order_eur
        leftover = max(D0, deployable - triggered_need)
        requested.update(_greedy_steps(cash_buys, leftover, policy))
        buys = sorted(buys + cash_buys, key=lambda c: (-c.drift, c.position.isin))
    for c in cash_buys:
        if requested.get(c.position.isin, D0) <= EPS:
            _suppress(suppressed, c.position.isin, Action.BUY, c.mid_amount,
                      SuppressionReason.BELOW_MIN_TICKET_SIZE)

    # The formal turnover denominator is 2 * portfolio value (SPEC 4.4).
    gross_mid = sum(requested.values(), D0)
    max_mid = 2 * total * policy.max_portfolio_turnover
    if gross_mid > max_mid and gross_mid > 0:
        kappa = max_mid / gross_mid
        for isin, before in list(requested.items()):
            after = before * kappa
            _suppress(suppressed, isin,
                      Action.BUY if any(c.position.isin == isin for c in buys) else Action.SELL,
                      before - after, SuppressionReason.TURNOVER_CAPPED)
            requested[isin] = after
        notes.append(f"Ciro üst sınırı: ölçekleme katsayısı {number(kappa, 8):.8f}.")

    orders: list[ExecutionOrder] = []
    changes: dict[str, JsonNumber] = {p.isin: D0 for p in data.positions}
    running_cash = start_cash
    total_buy = total_sell = total_spread = total_tax = total_fees = mid_turnover = D0
    spread_warning = Decimal("0.015")

    def trade(c: _Candidate) -> None:
        nonlocal running_cash, total_buy, total_sell, total_spread, total_tax, total_fees, mid_turnover
        p = c.position
        desired = requested.get(p.isin, D0)
        if desired <= EPS:
            return
        px = p.bid if c.action == Action.SELL else p.ask
        qty = floor_step(desired / p.quote_mid, p.quantity_step)
        if c.action == Action.SELL:
            qty = min(qty, floor_step(p.shares, p.quantity_step))
        else:
            # Protect cash, target cash reserve and fees before emitting BUY.
            budget = max(D0, running_cash - reserve - policy.estimated_fee_per_order_eur)
            qty = min(qty, floor_step(budget / px, p.quantity_step))
        if qty <= 0 or qty * px < policy.min_trade_ticket_eur:
            _suppress(suppressed, p.isin, c.action, desired, SuppressionReason.BELOW_MIN_TICKET_SIZE)
            return
        estimate_tax = _tax_reserve(p, qty, policy) if c.action == Action.SELL else D0
        if estimate_tax is None:
            _suppress(suppressed, p.isin, c.action, qty * px, SuppressionReason.SELLING_PROHIBITED)
            notes.append(f"{p.isin}: vergi matrahı olmadan satış güvenli değil.")
            return
        if (c.action == Action.SELL and policy.rebalance_mode == RebalanceMode.TAX_MINIMIZED
                and estimate_tax > total * policy.tax_lock_portfolio_fraction):
            _suppress(suppressed, p.isin, c.action, qty * px, SuppressionReason.SELLING_PROHIBITED)
            notes.append(f"{p.isin}: tahmini vergi %5 vergi kilidi sınırını aşıyor.")
            return
        gross = qty * px
        spread = qty * ((p.quote_mid - p.bid) if c.action == Action.SELL
                        else (p.ask - p.quote_mid))
        fee = policy.estimated_fee_per_order_eur
        net = gross - fee - estimate_tax if c.action == Action.SELL else -gross - fee
        if running_cash + net < -EPS:
            _suppress(suppressed, p.isin, c.action, desired, SuppressionReason.BELOW_MIN_TICKET_SIZE)
            return
        if c.action == Action.SELL and net <= 0:
            _suppress(suppressed, p.isin, c.action, desired, SuppressionReason.SELLING_PROHIBITED)
            return
        running_cash += net
        changes[p.isin] += qty if c.action == Action.BUY else -qty
        if c.action == Action.SELL:
            total_sell += gross
        else:
            total_buy += gross
        total_spread += spread
        total_tax += estimate_tax
        total_fees += fee
        mid_turnover += qty * p.quote_mid
        spread_pct = (p.ask - p.bid) / p.quote_mid
        if c.action == Action.BUY:
            explanation = "Hedef altı; mutlak VE göreceli tolerans aşıldı; yüksek drift önceliği. "
            if any(o.action == Action.SELL for o in orders):
                explanation += "Satışın fiilen gerçekleşmesi ve fonların kullanılabilir hale gelmesi şarttır. "
            explanation += "Alım yalnızca nakit/rezerv ve tahmini ücret sınırları içinde planlandı."
        else:
            explanation = "Hedef üstü; önce satış (PHASE_1_SELL) ile likidite üretimi."
        if spread_pct > spread_warning:
            explanation += " Spread >%1,5: XETR 13:00–17:00 CET/CEST likidite penceresinde limit emir değerlendir; piyasa emri kullanma."
        orders.append(ExecutionOrder(
            execution_sequence=len(orders) + 1,
            phase=Phase.PHASE_1_SELL if c.action == Action.SELL else Phase.PHASE_2_BUY,
            isin=p.isin, ticker=p.ticker, action=c.action,
            shares_delta=number(qty if c.action == Action.BUY else -qty, 10),
            target_price=number(px, 8), estimated_amount=money(gross),
            spread_drag_eur=money(spread), tax_impact_eur=money(estimate_tax),
            rationale=explanation,
        ))

    # Mandatory ordering invariant: all sales before all purchases.
    for c in sells:
        trade(c)
    for c in buys:
        trade(c)

    # A smaller market value after spread, fee and tax costs is accounted for.
    def projection(active_orders: list[ExecutionOrder],
                   share_changes: dict[str, JsonNumber], cash: Decimal) -> tuple[Decimal, list[PostRebalanceDrift]]:
        future_equity = {p.isin: p.valuation + share_changes[p.isin] * p.quote_mid
                         for p in data.positions}
        future_total = sum(future_equity.values(), D0) + cash
        details: list[PostRebalanceDrift] = []
        for p in data.positions:
            tgt_w = targets[p.isin] / total if total > 0 else D0
            future_w = future_equity[p.isin] / future_total if future_total > 0 else D0
            details.append(PostRebalanceDrift(
                isin=p.isin, ticker=p.ticker, current_weight=number(p.current_weight),
                target_weight=number(tgt_w), projected_weight=number(future_w),
                remaining_drift=number(future_w - tgt_w),
            ))
        return future_total, details

    projected_value, post = projection(orders, changes, running_cash)
    if total > 0 and orders:
        starting_max = max((abs(p.valuation / total - targets[p.isin] / total)
                            for p in data.positions), default=D0)
        final_max = max((abs(dec(x.remaining_drift)) for x in post), default=D0)
        # Safety invariant: never increase the worst absolute portfolio drift.
        if final_max > starting_max + Decimal("0.00000001"):
            notes.append("Güvenlik denetimi: beklenen en büyük ağırlık sapması artacağı için emirler iptal edildi.")
            orders.clear()
            changes = {p.isin: D0 for p in data.positions}
            running_cash = start_cash
            total_buy = total_sell = total_spread = total_tax = total_fees = mid_turnover = D0
            projected_value, post = projection(orders, changes, running_cash)

    if running_cash < -EPS:
        raise ArithmeticError("Internal safety failure: negative planned cash")
    if total > 0 and mid_turnover > max_mid + EPS:
        raise ArithmeticError("Internal safety failure: turnover cap breached")
    if any(o.estimated_amount < money(policy.min_trade_ticket_eur) for o in orders):
        raise ArithmeticError("Internal safety failure: below minimum ticket")
    if any(o.action == Action.SELL for o in orders) and any(o.action == Action.BUY for o in orders):
        assert max(o.execution_sequence for o in orders if o.action == Action.SELL) < min(
            o.execution_sequence for o in orders if o.action == Action.BUY)
    if projected_value < -EPS:
        raise ArithmeticError("Internal safety failure: projected negative portfolio value")

    if orders:
        notes.insert(0, f"{len(orders)} emir oluşturuldu: önce satış, sonra alış; yalnızca yürütme planı.")
    else:
        notes.insert(0, "Tolerans, nakit, lot, vergi, ciro veya asgari bilet kuralları nedeniyle icra edilebilir emir yok.")
    if policy.tax_enabled:
        notes.append("Vergi hesabı aktif: yaklaşık oransal kazanç vergisi rezervi; istisna/mahsup/Teilfreistellung kapsanmaz.")
    else:
        notes.append("Vergi defteri pasif: estimated_tax_impact_eur = 0; harici vergi modülü gerekmez.")
    notes.append(f"Tahmini işlem ücretleri: €{money(total_fees):.2f}; işlem sonrası planlanan nakit: €{money(running_cash):.2f}.")

    return RebalancingOutput(
        plan_id=f"REBAL-{uuid4().hex.upper()}",
        timestamp_utc=datetime.now(timezone.utc),
        rebalance_triggered=bool(orders),
        trigger_rationale=" ".join(notes),
        rebalance_summary=RebalanceSummary(
            initial_portfolio_value=money(initial),
            projected_portfolio_value=money(projected_value),
            total_buy_volume=money(total_buy),
            total_sell_volume=money(total_sell),
            net_cash_impact=money(running_cash - data.available_cash),
            projected_turnover_pct=number((mid_turnover / (2 * total) * 100) if total > 0 else D0, 6),
            estimated_spread_drag_eur=money(total_spread),
            estimated_tax_impact_eur=money(total_tax),
        ),
        ordered_execution_plan=orders,
        post_rebalance_drift=post,
        suppressed_trades=suppressed,
    )


def calculate_rebalancing(input_data: RebalancingInput | Mapping[str, Any]) -> RebalancingOutput:
    """Validate a portfolio snapshot and calculate a non-executing plan."""
    data = input_data if isinstance(input_data, RebalancingInput) else RebalancingInput.model_validate(input_data)
    return _calculate(data)


def rebalance_json(payload: str | bytes) -> str:
    """Read strict input JSON and return strict output JSON (numeric values)."""
    return _calculate(RebalancingInput.model_validate_json(payload)).model_dump_json(indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebalancing planner (no broker access)")
    parser.add_argument("input", nargs="?", help="JSON input file, or stdin if omitted")
    args = parser.parse_args()
    try:
        raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
        print(rebalance_json(raw))
    except (OSError, ValueError, ArithmeticError) as exc:
        print(f"Rebalancing failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
