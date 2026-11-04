#!/usr/bin/env python3
"""SPEC-PROMPT-OPT-001 v1.0.0: read-only portfolio optimization.

Dependencies: numpy>=1.24, scipy>=1.11, pydantic>=2.6.
Usage: python portfolio_optimization.py input.json > output.json
       python portfolio_optimization.py --input input.json --output result.json

Fields ending in _pct use percentage units (e.g. 12.5 means 12.5%).
Prices, valuations and cash MUST use the base currency (no FX conversion
fields exist in the input contract). All monetary computations use the
mid-price portfolio value BEFORE estimated spread friction. Spread is
explicitly reported and must be funded from the target cash reserve.
The module never creates, submits or changes broker orders or Sparplans.
UCITS checks implement exactly the security-level 5/10/40 proxy in the
supplied contract; legal issuer aggregation cannot be verified without
look-through/issuer identifiers and is NOT represented as legal certification.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from scipy.optimize import Bounds, LinearConstraint, linprog, milp, minimize

Array = NDArray[np.float64]
F = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NN = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
POS = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
UNIT = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
ISIN = Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")]
EPS = 1e-9
TOL = 2e-7


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CashEventType(str, Enum):
    EXISTING_CASH = "EXISTING_CASH"
    EXTERNAL_INFLOW = "EXTERNAL_INFLOW"
    EXTERNAL_OUTFLOW = "EXTERNAL_OUTFLOW"


class ModelType(str, Enum):
    MEAN_VARIANCE = "MEAN_VARIANCE"
    RISK_PARITY = "RISK_PARITY"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"
    MINIMUM_VARIANCE = "MINIMUM_VARIANCE"


class CashEvent(StrictModel):
    event_type: CashEventType
    amount: NN


class Holding(StrictModel):
    isin: ISIN
    ticker: str
    name: str
    shares: NN
    quote_mid: POS
    bid: POS
    ask: POS
    valuation: NN
    current_weight: UNIT
    is_ucits: bool = False
    min_weight: UNIT = 0.0
    max_weight: UNIT = 1.0

    @model_validator(mode="after")
    def coherent(self) -> "Holding":
        if self.min_weight > self.max_weight:
            raise ValueError(f"{self.isin}: min_weight > max_weight")
        if not (self.bid <= self.quote_mid <= self.ask):
            raise ValueError(f"{self.isin}: require bid <= quote_mid <= ask")
        expected = self.shares * self.quote_mid
        if not math.isclose(expected, self.valuation, rel_tol=1e-4, abs_tol=0.015):
            raise ValueError(f"{self.isin}: valuation must equal shares * quote_mid in base currency")
        return self


class CovarianceMatrix(StrictModel):
    asset_isins: list[ISIN]
    matrix: list[list[F]]


class ExpectedReturns(StrictModel):
    asset_isins: list[ISIN]
    returns: list[F]


class BlackLittermanParams(StrictModel):
    tau: POS = 0.025
    market_weights: list[UNIT] | None = None
    views_P: list[list[F]] = Field(default_factory=list)
    views_Q: list[F] = Field(default_factory=list)
    omega_diagonal: list[POS] = Field(default_factory=list)


class OptimizationConfig(StrictModel):
    model_type: ModelType
    risk_aversion_lambda: POS = 2.5
    target_cash_weight: UNIT = 0.01
    enforce_ucits_5_10_40: bool = False
    penalize_spread_costs: bool = True


class PortfolioOptimizationInput(StrictModel):
    as_of: datetime
    base_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    portfolio_equity: NN
    cash_balance: NN
    cash_event: CashEvent | None = None
    holdings: list[Holding]
    optimization_config: OptimizationConfig
    covariance_matrix: CovarianceMatrix
    expected_returns: ExpectedReturns | None = None
    black_litterman_params: BlackLittermanParams | None = None

    @field_validator("as_of")
    @classmethod
    def require_timestamp_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        return v

    @model_validator(mode="after")
    def validate_portfolio(self) -> "PortfolioOptimizationInput":
        ids = [h.isin for h in self.holdings]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate holdings ISINs")
        n = len(ids)
        if set(self.covariance_matrix.asset_isins) != set(ids) or len(self.covariance_matrix.asset_isins) != n:
            raise ValueError("covariance asset_isins must match holdings ISINs exactly")
        if len(self.covariance_matrix.matrix) != n or any(len(row) != n for row in self.covariance_matrix.matrix):
            raise ValueError("covariance matrix must be square N x N")
        if self.expected_returns is not None:
            er = self.expected_returns
            if len(er.returns) != n or len(er.asset_isins) != n or set(er.asset_isins) != set(ids):
                raise ValueError("expected return ISINs and values must match holdings")
        equity = sum(h.valuation for h in self.holdings)
        if not math.isclose(equity, self.portfolio_equity, rel_tol=1e-5, abs_tol=0.02):
            raise ValueError("portfolio_equity must equal sum of holding valuations (cash excluded)")
        total = self.portfolio_equity + self.cash_balance
        if total > EPS:
            for h in self.holdings:
                actual = h.valuation / total
                if not math.isclose(actual, h.current_weight, rel_tol=1e-4, abs_tol=1e-5):
                    raise ValueError(f"{h.isin}: current_weight does not match valuation / total value")
        elif any(h.current_weight > 0 for h in self.holdings):
            raise ValueError("zero-valued portfolio must have zero current weights")
        if self.cash_event is not None and self.cash_event.event_type == CashEventType.EXISTING_CASH:
            if self.cash_event.amount > self.cash_balance + 1e-7:
                raise ValueError("EXISTING_CASH amount exceeds existing cash_balance")
        if self.optimization_config.model_type == ModelType.MEAN_VARIANCE and self.expected_returns is None:
            raise ValueError("MEAN_VARIANCE requires expected_returns")
        if self.optimization_config.model_type == ModelType.BLACK_LITTERMAN:
            params = self.black_litterman_params
            if params is None or params.market_weights is None or len(params.market_weights) != n:
                raise ValueError("BLACK_LITTERMAN requires market_weights aligned with holdings")
            if n == 0 or abs(sum(params.market_weights)-1.0) > 1e-7:
                raise ValueError("BLACK_LITTERMAN market_weights must sum to one")
            k = len(params.views_P)
            if k != len(params.views_Q) or k != len(params.omega_diagonal):
                raise ValueError("views_P, views_Q, omega_diagonal must have identical view count")
            if any(len(row) != n for row in params.views_P):
                raise ValueError("each Black-Litterman P row must contain N elements")
        return self


class PortfolioMetrics(StrictModel):
    initial_total_value: F
    target_total_value: F
    expected_return_annualized: F
    expected_volatility_annualized: F
    expected_sharpe_ratio: F
    total_estimated_spread_cost: F
    net_turnover_pct: F


class Allocation(StrictModel):
    isin: str
    ticker: str
    current_weight: F
    target_weight: F
    weight_delta: F
    current_shares: F
    target_shares: F
    delta_shares: F
    target_value: F
    delta_value: F
    action: Literal["BUY", "SELL", "HOLD"]
    single_leg_spread_cost: F
    risk_contribution_pct: F


class CashAllocation(StrictModel):
    initial_cash: F
    target_cash: F
    target_cash_weight: F
    net_cash_delta: F


class Diagnostics(StrictModel):
    status: Literal["OPTIMAL", "CONVERGED", "FALLBACK_APPLIED"]
    sum_of_weights: F
    is_psd_matrix: bool
    ucits_compliance: bool | None = None
    warnings: list[str]


class PortfolioOptimizationOutput(StrictModel):
    model_id: str
    timestamp_utc: datetime
    objective_used: str
    portfolio_metrics: PortfolioMetrics
    allocations: list[Allocation]
    cash_allocation: CashAllocation
    diagnostics: Diagnostics


class OptimizationError(ValueError):
    """Input is internally inconsistent or no feasible allocation exists."""


def _aligned_matrix(data: PortfolioOptimizationInput) -> Array:
    source = {code: i for i, code in enumerate(data.covariance_matrix.asset_isins)}
    order = [source[h.isin] for h in data.holdings]
    matrix = np.asarray(data.covariance_matrix.matrix, dtype=float).reshape((len(order),len(order)))
    return matrix[np.ix_(order, order)]


def _aligned_returns(data: PortfolioOptimizationInput) -> Array:
    if data.expected_returns is None:
        return np.zeros(len(data.holdings), dtype=float)
    by_isin = dict(zip(data.expected_returns.asset_isins, data.expected_returns.returns))
    return np.array([by_isin[h.isin] for h in data.holdings], dtype=float)


def _covariance_psd(cov: Array, warnings: list[str]) -> tuple[Array, bool]:
    if not np.allclose(cov, cov.T, atol=1e-10, rtol=1e-8):
        warnings.append("Covariance matrix symmetrized before PSD validation")
    cov = (cov + cov.T) / 2
    if cov.size == 0:
        return cov, True
    if np.any(np.diag(cov) < -1e-10):
        warnings.append("Covariance contains negative diagonal entries")
    eigen_min = float(np.linalg.eigvalsh(cov)[0])
    initial_psd = eigen_min >= -1e-10
    if not initial_psd:
        cov = cov + max(0.0, 1e-6-eigen_min) * np.eye(cov.shape[0])
        warnings.append("Covariance matrix regularized to enforce positive semi-definiteness")
    return cov, initial_psd


def _black_litterman(data: PortfolioOptimizationInput, cov: Array, warnings: list[str]) -> tuple[Array, Array]:
    params = data.black_litterman_params
    assert params is not None and params.market_weights is not None
    n = len(data.holdings)
    mkt = np.asarray(params.market_weights)
    lam = data.optimization_config.risk_aversion_lambda
    pi = lam * cov @ mkt
    prior_cov = params.tau * cov
    eig_min = float(np.linalg.eigvalsh(prior_cov)[0])
    if eig_min <= 1e-12:
        prior_cov = prior_cov + (1e-10-eig_min) * np.eye(n)
        warnings.append("Black-Litterman prior covariance ridge regularized for numerical stability")
    if not params.views_P:
        posterior_mu, posterior_cov = pi, cov + prior_cov
    else:
        p = np.asarray(params.views_P, dtype=float)
        q = np.asarray(params.views_Q, dtype=float)
        omega = np.diag(params.omega_diagonal)
        # Woodbury form avoids explicit inversion of Sigma and Omega.
        a = p @ prior_cov @ p.T + omega
        gain = np.linalg.solve(a, q-p @ pi)
        posterior_mu = pi + prior_cov @ p.T @ gain
        posterior_uncertainty = prior_cov - prior_cov @ p.T @ np.linalg.solve(a, p @ prior_cov)
        posterior_cov = cov + (posterior_uncertainty+posterior_uncertainty.T)/2
    return np.asarray(posterior_mu, dtype=float), (posterior_cov+posterior_cov.T)/2


def _ucits_ok(w: Array) -> bool:
    return bool(np.all(w <= 0.10+1e-7) and np.sum(w[w > 0.05+1e-8]) <= 0.40+1e-7)


def _ucits_milp(
    n: int, lower: Array, upper: Array, desired: Array, exposure: float | None,
) -> tuple[Array, float] | None:
    """Mixed-integer linear feasible UCITS allocation; optionally maximize exposure.

    Variables [w(N), z(N) binary, y(N), deviation(N)]. z_i marks the
    securities allowed to exceed 5%; y_i is the exact activated holding
    weight; sum(y) <= 40%. Strict '>5%' is represented conservatively.
    """
    length = 4*n
    if n == 0:
        return np.empty(0), 0.0
    lo = np.zeros(length)
    hi = np.full(length, np.inf)
    lo[:n], hi[:n] = lower, np.minimum(upper, .10)
    hi[n:2*n] = 1
    hi[2*n:3*n] = .10
    hi[3*n:] = 1
    integrality = np.zeros(length)
    integrality[n:2*n] = 1
    rows: list[Array] = []
    lows: list[float] = []
    highs: list[float] = []
    def row(entries: list[tuple[int,float]], lb: float=-np.inf, ub: float=np.inf) -> None:
        r = np.zeros(length)
        for index, coef in entries:
            r[index] = coef
        rows.append(r); lows.append(lb); highs.append(ub)
    for i in range(n):
        row([(i,1),(n+i,-.05)], ub=.05)                 # w<=.05+.05*z
        row([(2*n+i,1),(i,-1)], ub=0)                   # y<=w
        row([(2*n+i,1),(n+i,-.10)], ub=0)              # y<=.10*z
        row([(i,1),(2*n+i,-1),(n+i,.10)], ub=.10)      # y>=w-.10*(1-z)
        row([(i,1),(3*n+i,-1)], ub=desired[i])          # d>=w-desired
        row([(i,-1),(3*n+i,-1)], ub=-desired[i])        # d>=desired-w
    row([(2*n+i,1) for i in range(n)], ub=.40)
    if exposure is not None:
        row([(i,1) for i in range(n)], lb=exposure, ub=exposure)
    objective = np.zeros(length)
    objective[3*n:] = 1.0
    if exposure is None:
        # Lexicographic: maximize invested fraction, then remain close to desired.
        objective[:n] = -1e4
    try:
        solution = milp(
            c=objective, integrality=integrality, bounds=Bounds(lo,hi),
            constraints=LinearConstraint(np.array(rows),np.array(lows),np.array(highs)),
            options={"time_limit": 15.0, "mip_rel_gap": 1e-9},
        )
    except (ValueError, RuntimeError):
        return None
    if solution.x is None or solution.status not in (0, 1):
        return None
    weights = np.asarray(solution.x[:n], dtype=float)
    if not _ucits_ok(weights) or np.any(weights < lower-1e-6) or np.any(weights > upper+1e-6):
        return None
    invested = float(weights.sum())
    if exposure is not None and abs(invested-exposure) > 2e-6:
        return None
    return weights, invested


def _linprog_seed(lower: Array, upper: Array, exposure: float, preferred: Array) -> Array | None:
    n = len(lower)
    # Auxiliary deviation variables return the feasible allocation nearest
    # the desired holdings, useful for minimizing unnecessary spread.
    objective = np.r_[np.zeros(n), np.ones(n)]
    a_ub = np.zeros((2*n, 2*n))
    b_ub = np.r_[preferred, -preferred]
    for i in range(n):
        a_ub[i,i], a_ub[i,n+i] = 1, -1
        a_ub[n+i,i], a_ub[n+i,n+i] = -1, -1
    a_eq = np.zeros((1,2*n)); a_eq[0,:n] = 1
    sol = linprog(objective, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq,
                  b_eq=[exposure], bounds=list(zip(lower,upper))+[(0,None)]*n,
                  method="highs")
    return np.asarray(sol.x[:n], dtype=float) if sol.success else None



def _liquidity_plan(
    lower: Array, upper: Array, w0: Array, buy: Array, sell: Array,
    requested_cash: float, ucits: bool, relax_cash: bool,
) -> tuple[Array, float] | None:
    """LP/MILP feasibility with actual single-leg spread and funded cash.

    A cash relaxation, when authorized, is *minimized* subject to long-only,
    all position bounds and full UCITS constraints. No discrete search grid.
    """
    n=len(w0)
    # [w (n), buys (n), sells (n), cash (1), z (n), y (n)]
    size=3*n+1+(2*n if ucits else 0)
    cidx=3*n
    z0=cidx+1
    y0=z0+n
    objective=np.zeros(size)
    objective[n:2*n]=buy*1e-4+1e-7
    objective[2*n:3*n]=sell*1e-4+1e-7
    if relax_cash:
        objective[cidx]=1.0
    lo=np.zeros(size);hi=np.full(size,np.inf)
    lo[:n]=lower;hi[:n]=np.minimum(upper,.10) if ucits else upper
    if relax_cash:
        lo[cidx]=requested_cash
        hi[cidx]=1.0
    else:
        lo[cidx]=hi[cidx]=requested_cash
    integer=np.zeros(size)
    if ucits:
        hi[z0:z0+n]=1.0
        hi[y0:y0+n]=.10
        integer[z0:z0+n]=1
    rows: list[Array]=[]
    lb: list[float]=[]
    ub: list[float]=[]
    def add(values: list[tuple[int,float]], low:float=-np.inf, high:float=np.inf)->None:
        r=np.zeros(size)
        for i,val in values:
            r[i]=val
        rows.append(r);lb.append(low);ub.append(high)
    for i in range(n):
        add([(i,1),(n+i,-1),(2*n+i,1)],w0[i],w0[i])
    add([(i,1) for i in range(n)]+[(cidx,1)],1.0,1.0)
    add([(n+i,float(buy[i])) for i in range(n)] +
        [(2*n+i,float(sell[i])) for i in range(n)]+[(cidx,-1)],high=0.0)
    if ucits:
        for i in range(n):
            add([(i,1),(z0+i,-.05)],high=.05)
            add([(y0+i,1),(i,-1)],high=0)
            add([(y0+i,1),(z0+i,-.10)],high=0)
            add([(i,1),(y0+i,-1),(z0+i,.10)],high=.10)
        add([(y0+i,1) for i in range(n)],high=.40)
    constraints=LinearConstraint(np.asarray(rows),np.asarray(lb),np.asarray(ub))
    try:
        if ucits:
            res=milp(c=objective,integrality=integer,bounds=Bounds(lo,hi),
                     constraints=constraints,options={"time_limit":25.0,"mip_rel_gap":1e-9})
        else:
            # Explicit bounds and LP; unlike the nonlinear solver this gives
            # a globally feasible seed whenever one exists.
            mat=np.asarray(rows)
            l=np.asarray(lb);u=np.asarray(ub)
            eq=np.isclose(l,u,rtol=0,atol=1e-13)
            aeq=mat[eq];beq=u[eq]
            upper_mask=~eq & np.isfinite(u)
            lower_mask=~eq & np.isfinite(l)
            aub=np.vstack([mat[upper_mask],-mat[lower_mask]])
            bub=np.r_[u[upper_mask],-l[lower_mask]]
            res=linprog(objective,A_ub=aub,b_ub=bub,A_eq=aeq,b_eq=beq,
                        bounds=list(zip(lo,hi)),method="highs")
    except (ValueError,RuntimeError):
        return None
    if res.x is None or not res.success:
        return None
    w=np.asarray(res.x[:n],dtype=float)
    cash=float(res.x[cidx])
    if (np.any(w<lower-2e-6) or np.any(w>upper+2e-6) or
        abs(sum(w)+cash-1)>2e-6 or
        _spread_fraction(w,w0,buy,sell)>cash+2e-6 or
        (ucits and not _ucits_ok(w))):
        return None
    return w,cash


def _risk_parity_seed(cov: Array, total_weight: float) -> Array:
    n = cov.shape[0]
    if n == 0:
        return np.empty(0)
    if n == 1:
        return np.array([total_weight])
    # Convex unnormalized log-risk formulation; normalize after solution.
    scale = max(float(np.trace(cov))/n, 1e-8)
    normalized_cov = cov/scale
    budget = np.full(n,1/n)
    def objective(x: Array) -> tuple[float, Array]:
        return (float(.5*x @ normalized_cov @ x - budget @ np.log(x)),
                normalized_cov @ x-budget/x)
    s = minimize(objective, np.full(n,1.0/n), jac=True, method="L-BFGS-B",
                 bounds=[(1e-9,None)]*n, options={"maxiter":3000,"ftol":1e-13})
    x = s.x if s.success and np.all(s.x > 0) else np.ones(n)
    return total_weight*x/x.sum()


def _spread_rates(holdings: list[Holding]) -> tuple[Array,Array]:
    buy = np.array([(h.ask-h.quote_mid)/h.quote_mid for h in holdings])
    sell = np.array([(h.quote_mid-h.bid)/h.quote_mid for h in holdings])
    return np.maximum(buy,0), np.maximum(sell,0)


def _spread_fraction(w: Array, w0: Array, buy: Array, sell: Array) -> float:
    delta = w-w0
    return float(np.maximum(delta,0)@buy + np.maximum(-delta,0)@sell)


def _qp_optimize(
    cov: Array, mu: Array, w0: Array, lower: Array, upper: Array,
    exposure: float, cash: float, buy: Array, sell: Array,
    model: ModelType, lam: float, initial: Array, large_set: Array | None,
    actual_buy: Array, actual_sell: Array,
) -> Array | None:
    """Exact convex auxiliary-variables formulation of piecewise spread drag."""
    n=len(w0)
    matrix = np.zeros((n+1, 3*n))
    matrix[:n,:n]=np.eye(n)
    matrix[:n,n:2*n]=-np.eye(n)
    matrix[:n,2*n:]=np.eye(n)  # equation w-b+s=w0
    matrix[n,:n]=1
    if model == ModelType.MINIMUM_VARIANCE:
        multiplier, expected = 1.0, np.zeros(n)
    else:
        multiplier, expected = lam, mu
    def fun(x: Array) -> tuple[float,Array]:
        w=x[:n]
        value=.5*multiplier*w@cov@w-expected@w+buy@x[n:2*n]+sell@x[2*n:]
        gradient=np.r_[multiplier*cov@w-expected,buy,sell]
        return float(value),gradient
    constraints: list[LinearConstraint]=[
        LinearConstraint(matrix,np.r_[w0,exposure],np.r_[w0,exposure]),
    ]
    if large_set is not None:
        extra=np.zeros((1,3*n)); extra[0,:n]=large_set.astype(float)
        constraints.append(LinearConstraint(extra,-np.inf,.40))
    cost=np.r_[np.zeros(n),actual_buy,actual_sell][None,:]
    constraints.append(LinearConstraint(cost,-np.inf,max(0,cash)))
    x0=np.r_[initial,np.maximum(initial-w0,0),np.maximum(w0-initial,0)]
    xlb=np.r_[lower,np.zeros(2*n)]
    xub=np.r_[upper,np.full(2*n,np.inf)]
    res=minimize(fun,x0,jac=True,method="SLSQP",bounds=Bounds(xlb,xub),
                 constraints=constraints,options={"maxiter":2000,"ftol":1e-12})
    if res.success and np.all(np.isfinite(res.x)):
        w=res.x[:n]
        if (np.max(np.maximum(lower-w,0)) < 3e-6 and
            np.max(np.maximum(w-upper,0)) < 3e-6 and
            abs(w.sum()-exposure)<3e-6 and
            _spread_fraction(w,w0,actual_buy,actual_sell)<=cash+3e-6 and
            (large_set is None or sum(w[large_set])<=.4+3e-6)):
            return np.asarray(w,dtype=float)
    return None


def _risk_optimize(
    cov: Array,w0: Array,lower: Array,upper: Array,exposure: float,cash: float,
    buy: Array,sell: Array, initial: Array,large_set: Array | None,
    locked: Array, actual_buy: Array, actual_sell: Array,
) -> Array | None:
    n=len(w0)
    if n == 0:
        return np.empty(0)
    risky=np.flatnonzero(~locked)
    def obj(w: Array) -> float:
        if len(risky)==0:
            return _spread_fraction(w,w0,buy,sell)
        sigma2=float(w@cov@w)
        if sigma2<=1e-20:
            return 1e7+_spread_fraction(w,w0,buy,sell)
        contributions=w[risky]*(cov@w)[risky]
        budgets=np.full(len(risky),1/len(risky))
        mismatch=np.sum((contributions/sigma2-budgets)**2)
        return float(mismatch + (0.01*_spread_fraction(w,w0,buy,sell)))
    constraints=[{"type":"eq","fun":lambda w: float(w.sum()-exposure)},
                 {"type":"ineq","fun":lambda w: float(cash-_spread_fraction(w,w0,actual_buy,actual_sell))}]
    if large_set is not None:
        constraints.append({"type":"ineq","fun":lambda w: float(.40-np.sum(w[large_set]))})
    candidates=[initial]
    if len(risky)>0:
        seed=np.zeros(n)
        seed[risky]=_risk_parity_seed(cov[np.ix_(risky,risky)],max(0,exposure-sum(lower[locked])))
        seed[locked]=lower[locked]
        candidates.append(seed)
    best: Array | None=None
    bestval=float("inf")
    for start in candidates:
        if np.any(start<lower-1e-6) or np.any(start>upper+1e-6) or abs(start.sum()-exposure)>1e-5:
            start=initial
        sol=minimize(obj,start,method="SLSQP",bounds=list(zip(lower,upper)),
                     constraints=constraints,options={"maxiter":2000,"ftol":1e-11})
        for w in (sol.x, start):
            if (np.all(np.isfinite(w)) and np.all(w>=lower-2e-6) and
                np.all(w<=upper+2e-6) and abs(w.sum()-exposure)<2e-6 and
                _spread_fraction(w,w0,actual_buy,actual_sell)<=cash+2e-6 and
                (large_set is None or sum(w[large_set])<=.4+2e-6)):
                if obj(w)<bestval:
                    best,bestval=np.asarray(w,dtype=float).copy(),obj(w)
    return best


def _solve(
    model: ModelType,cov: Array,mu: Array,w0: Array,lower: Array,upper: Array,
    invest: float,cash: float,buy: Array,sell: Array,lam:float,ucits:bool,
    warnings:list[str],locked: Array,actual_buy:Array,actual_sell:Array,
) -> tuple[Array,float,str]:
    n=len(w0)
    if n==0:
        return np.empty(0),1.0,"OPTIMAL"
    if ucits:
        upper=np.minimum(upper,.10)
    if np.any(lower>upper+TOL):
        raise OptimizationError("incompatible min/max limits (possibly due to UCITS 10% cap)")
    fallback=False
    requested_cash=cash
    plan=_liquidity_plan(lower,upper,w0,actual_buy,actual_sell,cash,ucits,False)
    if plan is None:
        plan=_liquidity_plan(lower,upper,w0,actual_buy,actual_sell,cash,ucits,True)
        if plan is None:
            raise OptimizationError("No feasible long-only allocation, even after relaxing cash target")
        fallback=True
        warnings.append(
            "Requested cash target infeasible under limits, UCITS or spread funding; "
            "cash adjusted to minimum feasible reserve"
        )
    initial,cash=plan
    invest=1-cash
    if abs(cash-requested_cash)>1e-6:
        fallback=True
    large_candidates: list[Array | None]
    if ucits:
        # Each fixed set creates a genuinely UCITS-compliant convex subproblem.
        # The disjunction of all sets is non-convex; sample several sets and
        # never claim proof of global optimality in this case.
        chosen=initial>0.05+1e-8
        large_candidates=[chosen]
        if sum(chosen)>0:
            large_candidates.append(chosen.copy())
        # Additional candidate large sets favor the unconstrained high-conviction assets.
        ordering=np.argsort(-mu if model in (ModelType.MEAN_VARIANCE,ModelType.BLACK_LITTERMAN)
                            else -np.diag(cov))
        for count in (0,1,2,3,4,5,8):
            mask=np.zeros(n,dtype=bool)
            mask[ordering[:count]]=True
            large_candidates.append(mask)
        large_candidates.append(w0>0.05+1e-8)
    else:
        large_candidates=[None]
    solutions: list[Array]=[]
    for mask in large_candidates:
        current_upper=upper.copy()
        if mask is not None:
            current_upper[~mask]=np.minimum(current_upper[~mask],.05)
            if sum(lower[mask])>.4+TOL or sum(current_upper)<invest-TOL:
                continue
        # Obtain a feasible seed for this exact UCITS partition.
        if mask is not None:
            candidate=_linprog_seed(lower,current_upper,invest,initial)
            if candidate is None or candidate[mask].sum()>.4+TOL:
                # linear programming with the group cap
                A=np.zeros((1,n)); A[0,mask]=1
                result=linprog(np.zeros(n), A_ub=A, b_ub=[.4],
                              A_eq=np.ones((1,n)),b_eq=[invest],
                              bounds=list(zip(lower,current_upper)),method="highs")
                candidate=result.x if result.success else None
        else:
            candidate=initial
        if candidate is None:
            continue
        if model==ModelType.RISK_PARITY:
            solution=_risk_optimize(cov,w0,lower,current_upper,invest,cash,buy,sell,
                                    candidate,mask,locked,actual_buy,actual_sell)
        else:
            solution=_qp_optimize(cov,mu,w0,lower,current_upper,invest,cash,buy,sell,
                                  model,lam,candidate,mask,actual_buy,actual_sell)
        if solution is not None and (not ucits or _ucits_ok(solution)):
            solutions.append(solution)
    if not solutions:
        if _spread_fraction(initial,w0,actual_buy,actual_sell)>cash+TOL:
            raise OptimizationError("no feasible spread-funded allocation")
        warnings.append("Numerical solver fallback: feasible (not necessarily optimal) seed retained")
        return initial,cash,"FALLBACK_APPLIED"
    def score(w: Array) -> float:
        spread=_spread_fraction(w,w0,buy,sell)
        if model==ModelType.RISK_PARITY:
            risky=np.where(~locked)[0]
            if len(risky)==0: return spread
            variance=float(w@cov@w)
            if variance<=1e-20: return 1e10
            fractions=w[risky]*(cov@w)[risky]/variance
            return float(sum((fractions-1/len(risky))**2)+.01*spread)
        if model==ModelType.MINIMUM_VARIANCE:
            return float(.5*w@cov@w+spread)
        return float(.5*lam*w@cov@w-mu@w+spread)
    winner=min(solutions,key=score)
    return winner,cash,("FALLBACK_APPLIED" if fallback else
                         "CONVERGED" if ucits or model==ModelType.RISK_PARITY else "OPTIMAL")


def _build_output(
    data: PortfolioOptimizationInput,cov: Array,mu: Array,w: Array,
    cash_weight: float,initial_total:float,target_total:float,
    buy: Array,sell: Array,status:str,psd:bool,warnings:list[str],
    *,withdrawal_shortfall:bool=False,
) -> PortfolioOptimizationOutput:
    n=len(w)
    w0=np.array([h.valuation/target_total if target_total>EPS else 0 for h in data.holdings])
    # zero-target liquidation: w0=0 in the zero-denominator limit; absolute
    # notional differences remain faithfully computed below.
    risk_variance=max(0.0,float(w@cov@w)) if n else 0.0
    volatility=math.sqrt(risk_variance)
    ret=float(mu@w) if n else 0.0
    sharpe=ret/volatility if volatility>1e-12 else 0.0  # 0% assumed risk free
    if volatility<=1e-12:
        warnings.append("Sharpe ratio set to 0 because portfolio volatility is zero")
    elif n:
        warnings.append("Sharpe ratio assumes 0% risk-free rate (not supplied in schema)")
    if data.expected_returns is None and data.optimization_config.model_type!=ModelType.BLACK_LITTERMAN:
        warnings.append("Expected returns unavailable; reported annual expected return set to 0")
    allocations=[]
    total_cost=0.0; absolute_turnover=0.0
    for i,h in enumerate(data.holdings):
        target_value=float(w[i]*target_total)
        delta=target_value-h.valuation
        # Action reflects actual trade notional, not post-cash-event weight drift.
        if abs(delta)<=1e-8:
            delta=0.0
        action="BUY" if delta>0 else "SELL" if delta<0 else "HOLD"
        price=h.quote_mid
        target_shares=target_value/price
        cost=max(delta,0)*buy[i]+max(-delta,0)*sell[i]
        total_cost+=cost
        absolute_turnover+=abs(delta)
        rc=float(100*w[i]*(cov@w)[i]/risk_variance) if risk_variance>1e-18 else 0.0
        allocations.append(Allocation(
            isin=h.isin,ticker=h.ticker,current_weight=float(h.current_weight),
            target_weight=float(w[i]),weight_delta=float(w[i]-h.current_weight),
            current_shares=float(h.shares),target_shares=float(target_shares),
            delta_shares=float(target_shares-h.shares),target_value=target_value,
            delta_value=float(delta),action=action,single_leg_spread_cost=float(cost),
            risk_contribution_pct=rc,
        ))
    target_cash=target_total*cash_weight
    # The weights and target cash are explicitly pre-spread and remain a
    # simplex on the contractual target notional denominator.
    if total_cost>target_cash+0.015 and not withdrawal_shortfall:
        raise OptimizationError("post-spread cash would be negative")
    if total_cost>EPS:
        warnings.append("Target cash and weights are pre-spread; actual cash and NAV decrease by estimated spread cost")
    if withdrawal_shortfall:
        warnings.append("Excess withdrawal refused; positions assumed fully liquidated at bid for maximum-withdrawable estimate")
    ucits=_ucits_ok(w)
    if not ucits:
        warnings.append("UCITS 5/10/40 security-level exposure thresholds breached")
    if data.optimization_config.enforce_ucits_5_10_40:
        warnings.append("UCITS check is a security-level proxy; legal issuer/look-through aggregation cannot be verified from input")
        warnings.append("UCITS feasible target is enforced by MILP; global optimality of the mixed-integer nonlinear objective is not certified")
        if not ucits: raise OptimizationError("UCITS enforcement verification failed")
    sum_weights=float(sum(float(x) for x in w)+cash_weight)
    if abs(sum_weights-1)>1e-5: raise OptimizationError("simplex invariant violated")
    return PortfolioOptimizationOutput(
        model_id=f"SPEC-PROMPT-OPT-001:1.0.0:{data.optimization_config.model_type.value}",
        timestamp_utc=datetime.now(timezone.utc),
        objective_used={
          ModelType.MEAN_VARIANCE:"MAX expected return - lambda/2 variance - one-leg spread drag",
          ModelType.MINIMUM_VARIANCE:"MIN 1/2 variance + one-leg spread drag",
          ModelType.RISK_PARITY:"Equal risk contribution - constrained least squares with spread penalty",
          ModelType.BLACK_LITTERMAN:"Black-Litterman posterior mean-variance with one-leg spread drag",
        }[data.optimization_config.model_type],
        portfolio_metrics=PortfolioMetrics(
            initial_total_value=float(initial_total),target_total_value=float(target_total),
            expected_return_annualized=ret,expected_volatility_annualized=volatility,
            expected_sharpe_ratio=float(sharpe),total_estimated_spread_cost=float(total_cost),
            net_turnover_pct=float(100*absolute_turnover/(target_total if target_total>EPS else initial_total)
                                   if initial_total>EPS else 0),
        ),
        allocations=allocations,
        cash_allocation=CashAllocation(
            initial_cash=float(data.cash_balance),target_cash=float(target_cash),
            target_cash_weight=float(cash_weight),net_cash_delta=float(target_cash-data.cash_balance),
        ),
        diagnostics=Diagnostics(status=status,sum_of_weights=sum_weights,
                                is_psd_matrix=psd,ucits_compliance=ucits,warnings=list(dict.fromkeys(warnings))),
    )


def optimize_portfolio(value: PortfolioOptimizationInput | dict) -> PortfolioOptimizationOutput:
    """Validate, optimize and return a *read-only* strict-schema target.

    The target NAV and target weights are pre-execution-mid-value; friction is
    shown separately, not silently deducted from portfolio weights. Outflow
    shortage triggers a liquidation fallback with explicit warnings.
    """
    data=value if isinstance(value,PortfolioOptimizationInput) else PortfolioOptimizationInput.model_validate_json(json.dumps(value))
    warnings: list[str]=[]
    initial_total=float(data.portfolio_equity+data.cash_balance)
    cov,psd=_covariance_psd(_aligned_matrix(data),warnings)
    mu=_aligned_returns(data)
    model=data.optimization_config.model_type
    if model==ModelType.BLACK_LITTERMAN:
        mu,cov=_black_litterman(data,cov,warnings)
    buy,sell=_spread_rates(data.holdings)
    if not data.optimization_config.penalize_spread_costs:
        warnings.append("Spread penalty disabled in objective, but execution cost still reported and cash-funded")
    objective_buy=buy if data.optimization_config.penalize_spread_costs else np.zeros_like(buy)
    objective_sell=sell if data.optimization_config.penalize_spread_costs else np.zeros_like(sell)
    event=data.cash_event or CashEvent(event_type=CashEventType.EXISTING_CASH,amount=0)
    amount=event.amount
    if event.event_type==CashEventType.EXTERNAL_INFLOW:
        target_total=initial_total+amount
    elif event.event_type==CashEventType.EXTERNAL_OUTFLOW:
        max_withdrawal=float(data.cash_balance+sum(h.shares*h.bid for h in data.holdings))
        if amount>max_withdrawal+1e-7:
            # Actual post-liquidation NAV is zero. Nominal target_total cannot
            # equal V - requested amount if impossible; expose refusal.
            warnings.append(f"Liquidity shortfall: requested {amount:.2f}; maximum withdrawable at bid {max_withdrawal:.2f}")
            w=np.zeros(len(data.holdings))
            return _build_output(data,cov,mu,w,1.0,initial_total,0.0,buy,sell,
                                 "FALLBACK_APPLIED",psd,warnings,withdrawal_shortfall=True)
        target_total=initial_total-amount
    else:
        target_total=initial_total
    if target_total < -EPS:
        raise OptimizationError("cash withdrawal would create negative portfolio")
    if target_total <= EPS:
        return _build_output(data,cov,mu,np.zeros(len(data.holdings)),1.0,
                             initial_total,0.0,buy,sell,"FALLBACK_APPLIED",psd,warnings)
    n=len(data.holdings)
    if n==0:
        return _build_output(data,cov,mu,np.zeros(0),1.0,
                             initial_total,target_total,buy,sell,"OPTIMAL",psd,warnings)
    w0=np.array([h.valuation/target_total for h in data.holdings])
    minimum=np.array([h.min_weight for h in data.holdings])
    maximum=np.array([h.max_weight for h in data.holdings])
    requested_cash=data.optimization_config.target_cash_weight
    locked=np.zeros(n,dtype=bool)
    if model==ModelType.RISK_PARITY:
        # True zero-variance securities are excluded from the ERC logarithm.
        # Freeze their holdings at their post-flow weight (cash-like reserve).
        locked=np.diag(_aligned_matrix(data))<=1e-14
        if np.any(locked):
            warnings.append("Zero-volatility assets excluded from Risk Parity and locked as cash-like reserve")
            minimum[locked]=np.maximum(minimum[locked],w0[locked])
            maximum[locked]=np.minimum(maximum[locked],w0[locked])
            if np.any(minimum>maximum+TOL):
                raise OptimizationError("zero-variance locked holdings conflict with position limits")
    weights,cash_weight,status=_solve(
        model,cov,mu,w0,minimum,maximum,1-requested_cash,requested_cash,
        objective_buy,objective_sell,data.optimization_config.risk_aversion_lambda,
        data.optimization_config.enforce_ucits_5_10_40,warnings,locked,buy,sell,
    )
    # Re-evaluate liquidity at actual spreads, even if objective spread penalty off.
    if _spread_fraction(weights,w0,buy,sell)>cash_weight+TOL:
        raise OptimizationError("optimized allocation cannot pay real bid/ask spreads from cash")
    return _build_output(data,cov,mu,weights,cash_weight,initial_total,
                         target_total,buy,sell,status,psd,warnings)


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description="Strict JSON read-only portfolio optimizer")
    parser.add_argument("input",nargs="?",help="Input JSON filename; default stdin")
    parser.add_argument("--input",dest="input_flag",help="Input JSON filename")
    parser.add_argument("--output",help="Output JSON filename; default stdout")
    args=parser.parse_args(argv)
    try:
        filename=args.input_flag or args.input
        source=Path(filename).read_text(encoding="utf-8") if filename else sys.stdin.read()
        obj=PortfolioOptimizationInput.model_validate_json(source)
        result=optimize_portfolio(obj)
        payload=result.model_dump_json(indent=2,exclude_none=True)
        if args.output:
            Path(args.output).write_text(payload+"\n",encoding="utf-8")
        else:
            sys.stdout.write(payload+"\n")
        return 0
    except (ValidationError,OptimizationError,ValueError,json.JSONDecodeError) as e:
        # stdout remains strictly a successful PortfolioOptimizationOutput JSON;
        # failures are sent to stderr and have nonzero process exit status.
        sys.stderr.write(f"portfolio_optimization: {e}\n")
        return 2


if __name__=="__main__":
    raise SystemExit(main())
