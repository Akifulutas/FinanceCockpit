"""Factor and valuation analytics; SPEC-PROMPT-FACTOR-VAL-001 (v1.0.0).

Read-only. Input/output are validated Pydantic v2 JSON models; amounts must use
one consistent currency/unit (e.g. actual currency units, NOT millions mixed
with literal diluted share counts). Return series/rates use decimal units:
0.01 means 1%, NOT 1.0. Order return observations oldest -> newest.

The specification omits FCFF forecasts, D&A, gross debt, macro source metadata,
peer metric object shapes and a population for statistical radar z-scores. This
module accepts backwards-compatible OPTIONAL fields to fill those gaps. When
unavailable, it records assumptions and refuses to synthesize financially
unidentifiable inputs. Macro evidence is never invented.

Usage:
    python factor_and_valuation_models.py --input input.json --output result.json
    python factor_and_valuation_models.py < input.json > result.json

Requires: pydantic>=2, numpy>=1.26, scipy>=1.11, statsmodels>=0.14.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

import numpy as np
import statsmodels.api as sm
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scipy import stats
from statsmodels.stats.diagnostic import (
    acorr_breusch_godfrey,
    acorr_ljungbox,
    het_breuschpagan,
    het_white,
)
from statsmodels.stats.stattools import durbin_watson, jarque_bera

Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0, lt=1, allow_inf_nan=False)]
ReturnSeries: TypeAlias = list[Finite]
EPS = 1e-12


class ModelError(ValueError):
    """Raised when reliable analytic output is impossible with supplied data."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class AssumptionEvidence(StrictModel):
    reference: str = Field(min_length=3)
    as_of_date: date
    rationale: str = Field(min_length=8)


class MacroEvidence(StrictModel):
    risk_free_rate: AssumptionEvidence | None = None
    equity_risk_premium: AssumptionEvidence | None = None
    pre_tax_cost_of_debt: AssumptionEvidence | None = None
    terminal_growth_rate: AssumptionEvidence | None = None


class InstrumentSummary(StrictModel):
    instrument_id: str = Field(min_length=1)
    isin: str = Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    ticker: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    current_price: Positive
    shares_outstanding_diluted: Positive
    market_cap: Positive
    net_debt: Finite
    as_of_date: date
    # Optional additions: net debt is NOT gross interest-bearing debt.
    gross_debt: Nonnegative | None = None
    minority_interests: Nonnegative = 0.0

    @field_validator("isin")
    @classmethod
    def check_isin_luhn(cls, value: str) -> str:
        expanded = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
        checksum = 0
        for i, ch in enumerate(reversed(expanded)):
            digit = int(ch)
            if i % 2:
                digit *= 2
                digit = digit // 10 + digit % 10
            checksum += digit
        if checksum % 10:
            raise ValueError("ISIN checksum failed")
        return value

    @model_validator(mode="after")
    def market_cap_consistency(self) -> "InstrumentSummary":
        if self.gross_debt is not None and self.net_debt > self.gross_debt + EPS:
            raise ValueError("net_debt cannot exceed gross_debt")
        implied = self.current_price * self.shares_outstanding_diluted
        if not math.isclose(implied, self.market_cap, rel_tol=0.05, abs_tol=1e-9):
            raise ValueError("market_cap must match current_price * diluted shares within 5%")
        return self


class FactorBenchmarks(StrictModel):
    mkt_rf: ReturnSeries
    smb: ReturnSeries
    hml: ReturnSeries
    rmw: ReturnSeries
    cma: ReturnSeries
    umd: ReturnSeries | None = None
    low_vol: ReturnSeries | None = None


class ReturnSeriesSummary(StrictModel):
    observation_period: str = Field(min_length=1)
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY"]
    asset_excess_returns: ReturnSeries
    factor_benchmarks: FactorBenchmarks

    @model_validator(mode="after")
    def validate_alignment(self) -> "ReturnSeriesSummary":
        n = len(self.asset_excess_returns)
        if n < 60:
            raise ValueError("At least 60 synchronized return observations required")
        for name, series in self.factor_benchmarks.model_dump(exclude_none=True).items():
            if len(series) != n:
                raise ValueError(f"{name} length {len(series)} does not match {n}")
        if max(map(abs, self.asset_excess_returns)) > 2.0:
            raise ValueError("Returns must be decimal fractions (0.01 = 1%)")
        return self


class HistoricalFinancials(StrictModel):
    fiscal_years: list[str]
    revenue: list[Finite]
    ebit: list[Finite]
    net_income: list[Finite]
    operating_cash_flow: list[Finite] | None = None
    capital_expenditures: list[Finite] | None = None
    free_cash_flow: list[Finite]
    dividends_paid: list[Finite] | None = None
    # Explicit D&A permits meaningful EV/EBITDA; never equate EBIT with EBITDA.
    depreciation_amortization: list[Nonnegative] | None = None

    @model_validator(mode="after")
    def check_history(self) -> "HistoricalFinancials":
        n = len(self.fiscal_years)
        if n < 2 or n > 100:
            raise ValueError("Financials require 2-100 fiscal years")
        try:
            years = [int(y) for y in self.fiscal_years]
        except ValueError as exc:
            raise ValueError("fiscal_years must be YYYY years") from exc
        if any(len(y) != 4 for y in self.fiscal_years) or years != sorted(set(years)):
            raise ValueError("fiscal_years must be ascending unique YYYY")
        for key, value in self.model_dump(exclude_none=True).items():
            if key != "fiscal_years" and len(value) != n:
                raise ValueError(f"{key} must contain {n} annual values")
        if any(v <= 0 for v in self.revenue):
            raise ValueError("All historical revenue values must be positive")
        if self.capital_expenditures is not None and any(x < 0 for x in self.capital_expenditures):
            raise ValueError("capital_expenditures must use positive cash-outflow magnitudes")
        if self.dividends_paid is not None and any(x < 0 for x in self.dividends_paid):
            raise ValueError("dividends_paid must use nonnegative payments")
        return self


class MultipleBenchmark(StrictModel):
    # Permitted peer benchmark representations. At least one central estimate.
    median: Positive | None = None
    mean: Positive | None = None
    value: Positive | None = None
    p25: Positive | None = None
    p75: Positive | None = None

    @model_validator(mode="after")
    def central_value(self) -> "MultipleBenchmark":
        if self.median is None and self.mean is None and self.value is None:
            raise ValueError("Peer multiple needs median, mean, or value")
        if self.p25 is not None and self.p75 is not None and self.p25 > self.p75:
            raise ValueError("p25 > p75")
        return self

    def representative(self) -> float:
        v = self.median if self.median is not None else self.mean
        return float(v if v is not None else self.value)


class PeerMultiplesBenchmark(StrictModel):
    industry_sector: str = Field(min_length=1)
    peers_count: int | None = Field(default=None, ge=1)
    trailing_pe: MultipleBenchmark
    forward_pe: MultipleBenchmark
    ev_ebitda: MultipleBenchmark
    price_to_fcf: MultipleBenchmark


class MacroAssumptions(StrictModel):
    risk_free_rate: Rate
    equity_risk_premium: Positive
    effective_tax_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    pre_tax_cost_of_debt: Rate | None = None
    terminal_growth_rate: Annotated[float, Field(gt=-1, le=0.03, allow_inf_nan=False)]
    # Optional provenance: when absent, output flags SOURCE_MISSING.
    evidence: MacroEvidence | None = None


class ValuationInputs(StrictModel):
    """Optional overrides needed when base-schema data cannot identify estimates.

    FCFF must be genuinely *unlevered*; when absent, historical `free_cash_flow`
    is assumed to be FCFF and flagged. forward_equity_fcf is levered FCFE.
    Forecast vectors describe years 1..N, N=5 default.
    """
    forecast_fcff: list[Finite] | None = None
    forecast_revenue: list[Positive] | None = None
    forward_net_income: Finite | None = None
    forward_ebitda: Positive | None = None
    forward_equity_fcf: Positive | None = None
    fcf_is_unlevered_fcff: bool | None = None
    # Required to document EBIT-margin convergence when the latest FCF is negative.
    sector_terminal_ebit_margin: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] | None = None
    # Data-defined calibration for genuine cross-sectional factor radar scores.
    radar_reference: dict[str, tuple[Finite, Positive]] | None = None

    @model_validator(mode="after")
    def vector_lengths(self) -> "ValuationInputs":
        if self.forecast_fcff is not None and not (3 <= len(self.forecast_fcff) <= 15):
            raise ValueError("forecast_fcff needs 3-15 projection years")
        if self.forecast_revenue is not None and not (3 <= len(self.forecast_revenue) <= 15):
            raise ValueError("forecast_revenue needs 3-15 projection years")
        if self.forecast_fcff is not None and self.forecast_revenue is not None:
            if len(self.forecast_fcff) != len(self.forecast_revenue):
                raise ValueError("Forecast FCFF/revenue must cover the same years")
        return self


class FactorValuationInputPayload(StrictModel):
    instrument_summary: InstrumentSummary
    return_series_summary: ReturnSeriesSummary
    historical_financials: HistoricalFinancials
    peer_multiples_benchmark: PeerMultiplesBenchmark
    macro_assumptions: MacroAssumptions
    valuation_inputs: ValuationInputs = Field(default_factory=ValuationInputs)


class Coefficient(StrictModel):
    coefficient: Finite | None
    std_error: Finite | None
    t_statistic: Finite | None
    p_value: Finite | None
    significant_at_5pct: bool | None
    status: Literal["ESTIMATED", "NOT_ESTIMATED"]


class StatisticalTest(StrictModel):
    statistic: Finite | None = None
    p_value: Finite | None = None
    reject_at_5pct: bool | None = None
    status: Literal["COMPLETED", "NOT_COMPUTABLE"]


class RegressionDiagnostics(StrictModel):
    alpha_annualized_pct: Finite
    r_squared: Annotated[float, Field(ge=0, le=1)]
    adjusted_r_squared: Finite
    tracking_error_pct: Nonnegative
    style_drift_indicator: Literal["STABLE", "MODERATE_DRIFT", "HIGH_DRIFT"]
    observations: int
    degrees_of_freedom: int
    residual_sigma_pct: Nonnegative
    covariance_method: str
    vif: dict[str, Finite]
    breusch_pagan: StatisticalTest
    white: StatisticalTest
    ljung_box: StatisticalTest
    breusch_godfrey: StatisticalTest
    durbin_watson: Finite
    jarque_bera: StatisticalTest
    warnings: list[str]


class FactorRadarScores(StrictModel):
    value: Finite
    quality: Finite
    momentum: Finite
    low_volatility: Finite
    size: Finite
    interpretation: str

    @model_validator(mode="after")
    def clip_contract(self) -> "FactorRadarScores":
        for name in ("value", "quality", "momentum", "low_volatility", "size"):
            if not -3.0 <= getattr(self, name) <= 3.0:
                raise ValueError("Radar scores must lie between -3 and 3")
        return self


class FactorBetas(StrictModel):
    intercept_alpha: Coefficient
    market_beta: Coefficient
    size_smb: Coefficient
    value_hml: Coefficient
    profitability_rmw: Coefficient
    investment_cma: Coefficient
    momentum_umd: Coefficient
    low_vol_beta: Coefficient


class FactorExposureAnalysis(StrictModel):
    betas: FactorBetas
    regression_diagnostics: RegressionDiagnostics
    factor_radar_zscores: FactorRadarScores


class DCFModel(StrictModel):
    status: Literal["COMPLETED", "DATA_INSUFFICIENT"]
    wacc_pct: Finite
    terminal_growth_pct: Finite
    enterprise_value: Finite
    equity_value: Finite
    fair_value_per_share: Positive
    forecast_fcff: list[Finite]
    forecast_ebit: list[Finite]
    cost_of_equity_pct: Finite
    cost_of_debt_pct: Finite | None
    capital_structure_debt_weight: Finite
    warnings: list[str]


class DDMModel(StrictModel):
    status: Literal["COMPLETED", "NOT_APPLICABLE"]
    fair_value_per_share: Positive | None
    applicability_note: str
    cost_of_equity_pct: Finite | None = None
    dividend_growth_pct: Finite | None = None


class IntrinsicValuationModels(StrictModel):
    dcf_model: DCFModel
    ddm_model: DDMModel


class RelativeMultiplesValuation(StrictModel):
    implied_by_forward_pe: Positive
    implied_by_ev_ebitda: Positive
    implied_by_pfcf: Positive
    composite_multiples_fair_value: Positive
    benchmark_multiples: dict[str, Finite]
    warnings: list[str]


class ScenarioCase(StrictModel):
    probability: Annotated[float, Field(ge=0, le=1)]
    terminal_growth_pct: Finite
    wacc_pct: Finite
    projected_fcff: list[Finite]
    dcf_price: Positive
    multiples_price: Positive
    ddm_price: Positive | None
    fair_value_per_share: Positive
    rationale: str


class ScenarioBands(StrictModel):
    bull_case: ScenarioCase
    base_case: ScenarioCase
    bear_case: ScenarioCase
    weighted_fair_value: Positive
    margin_of_safety_pct: Finite
    price_range_low: Positive
    price_range_high: Positive
    weighting_method: dict[str, Finite]

    @model_validator(mode="after")
    def accept_scenarios(self) -> "ScenarioBands":
        p = sum((self.bull_case.probability, self.base_case.probability, self.bear_case.probability))
        if abs(p - 1.0) > 1e-6:
            raise ValueError("Scenario probabilities must sum to one")
        values = [self.bull_case.fair_value_per_share, self.base_case.fair_value_per_share,
                  self.bear_case.fair_value_per_share]
        if not math.isclose(self.price_range_low, min(values), rel_tol=1e-8):
            raise ValueError("Scenario low bound must match minimum")
        if not math.isclose(self.price_range_high, max(values), rel_tol=1e-8):
            raise ValueError("Scenario high bound must match maximum")
        return self


class SensitivityMatrix(StrictModel):
    wacc_steps: list[Finite]
    terminal_growth_steps: list[Finite]
    fair_price_grid: list[list[Positive]]
    effective_terminal_growth_grid: list[list[Finite]]
    warnings: list[str]

    @model_validator(mode="after")
    def grid_shape(self) -> "SensitivityMatrix":
        rows, cols = len(self.wacc_steps), len(self.terminal_growth_steps)
        if len(self.fair_price_grid) != rows or any(len(r) != cols for r in self.fair_price_grid):
            raise ValueError("Sensitivity matrix dimensions invalid")
        if len(self.effective_terminal_growth_grid) != rows or any(
            len(r) != cols for r in self.effective_terminal_growth_grid
        ):
            raise ValueError("Effective growth grid dimensions invalid")
        return self


class Metadata(StrictModel):
    instrument_id: str
    ticker: str
    currency: str
    current_price: Positive
    analysis_timestamp: datetime
    specification_id: str = "SPEC-PROMPT-FACTOR-VAL-001"
    specification_version: str = "1.0.0"
    as_of_date: date


class SynthesisSummary(StrictModel):
    valuation_regime: Literal[
        "SIGNIFICANTLY_UNDERVALUED", "FAIRLY_VALUED", "SIGNIFICANTLY_OVERVALUED"
    ]
    primary_factor_style: str
    key_risks: list[str]
    assumption_evidence: dict[str, AssumptionEvidence | None]
    read_only_no_order_execution: bool = True


class FactorValuationResultPayload(StrictModel):
    metadata: Metadata
    factor_exposure_analysis: FactorExposureAnalysis
    intrinsic_valuation_models: IntrinsicValuationModels
    relative_multiples_valuation: RelativeMultiplesValuation
    scenario_bands: ScenarioBands
    sensitivity_matrix: SensitivityMatrix
    synthesis_summary: SynthesisSummary


def _finite(value: float, context: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ModelError(f"Nonfinite result in {context}")
    return result


def _positive(value: float, context: str) -> float:
    val = _finite(value, context)
    if val <= EPS:
        raise ModelError(f"{context} is nonpositive; no valid positive valuation can be reported")
    return val


def _annual_frequency(frequency: str) -> int:
    return {"DAILY": 252, "WEEKLY": 52, "MONTHLY": 12}[frequency]


def _test(statistic: float | None, pvalue: float | None) -> StatisticalTest:
    if statistic is None or pvalue is None:
        return StatisticalTest(status="NOT_COMPUTABLE")
    if not (math.isfinite(float(statistic)) and math.isfinite(float(pvalue))):
        return StatisticalTest(status="NOT_COMPUTABLE")
    p = float(min(1, max(0, pvalue)))
    return StatisticalTest(status="COMPLETED", statistic=float(statistic), p_value=p,
                           reject_at_5pct=p < 0.05)


def _coeff(value: float, se: float, df: int) -> Coefficient:
    if not math.isfinite(value) or not math.isfinite(se) or se <= EPS:
        raise ModelError("Regression has degenerate coefficient standard error")
    t = float(value / se)
    p = float(2 * stats.t.sf(abs(t), df))
    return Coefficient(coefficient=float(value), std_error=float(se),
                       t_statistic=t, p_value=p,
                       significant_at_5pct=p < 0.05, status="ESTIMATED")


def _missing_coeff() -> Coefficient:
    return Coefficient(coefficient=None, std_error=None, t_statistic=None,
                       p_value=None, significant_at_5pct=None, status="NOT_ESTIMATED")


def _vifs(x: np.ndarray, names: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for j, name in enumerate(names):
        other = np.delete(x, j, axis=1)
        auxiliary = sm.OLS(x[:, j], sm.add_constant(other, has_constant="add")).fit()
        if auxiliary.rsquared >= 1 - 1e-12:
            raise ModelError(f"Near-perfect collinearity for {name}")
        result[name] = _finite(1.0 / (1 - float(auxiliary.rsquared)), f"VIF:{name}")
    return result


def _statistical_radar(
    betas: FactorBetas, residual_sd: float, reference: dict[str, tuple[float, float]] | None,
    warnings: list[str],
) -> FactorRadarScores:
    """Heuristic proxies unless a cross-sectional mean/sd is provided.

    Features: value=HML, quality=RMW, momentum=UMD,
    low_volatility=(.85-MKT)-5*residual_vol, size=SMB.
    PE/FCF, ROIC, 12-1 momentum and a true cross-sectional reference
    population are not supplied by the base input schema.
    """
    b = lambda c: float(c.coefficient or 0.0)
    values = {
        "value": b(betas.value_hml),
        "quality": b(betas.profitability_rmw),
        "momentum": b(betas.momentum_umd),
        "low_volatility": (0.85 - b(betas.market_beta)) - 5.0 * residual_sd,
        "size": b(betas.size_smb),
    }
    if reference is not None:
        if set(reference) != set(values):
            raise ModelError("radar_reference needs value, quality, momentum, low_volatility, size")
        scores = {k: float(np.clip((v - reference[k][0]) / reference[k][1], -3, 3))
                  for k, v in values.items()}
        label = "cross_sectional_zscores_with_supplied_reference"
    else:
        # Do not misrepresent heuristic linear scale as population Z-statistics.
        scores = {k: float(np.clip(v, -3, 3)) for k, v in values.items()}
        warnings.append("RADAR_PROXY_NOT_CROSS_SECTIONAL_ZSCORE: provide valuation_inputs.radar_reference")
        label = "clipped_factor_proxy_not_population_zscore"
    if betas.momentum_umd.status == "NOT_ESTIMATED":
        warnings.append("MOMENTUM_UMD_NOT_PROVIDED: momentum radar is not empirically estimated")
    return FactorRadarScores(**scores, interpretation=label)


def analyze_factors(data: ReturnSeriesSummary,
                    valuation_inputs: ValuationInputs | None = None) -> FactorExposureAnalysis:
    """OLS coefficient estimates with classical Student-t inference.

    Separately diagnoses heteroskedasticity and serial correlation; OLS Student-t
    standard errors satisfy the literal specification. HAC robust standard
    errors are also computed and added to warnings as a JSON-readable summary
    to avoid claiming conventional inference is robust to detected violations.
    """
    valuation_inputs = valuation_inputs or ValuationInputs()
    factors = data.factor_benchmarks
    series = factors.model_dump(exclude_none=True)
    ordered = [k for k in ("mkt_rf", "smb", "hml", "rmw", "cma", "umd", "low_vol") if k in series]
    y = np.asarray(data.asset_excess_returns, dtype=float)
    x = np.column_stack([np.asarray(series[k], dtype=float) for k in ordered])
    if np.linalg.matrix_rank(sm.add_constant(x, has_constant="add")) < len(ordered) + 1:
        raise ModelError("Regressor matrix is rank deficient; factor betas unidentifiable")
    if len(y) < max(60, 8 * (len(ordered) + 1)):
        raise ModelError("Insufficient data for reliable factor diagnostics")
    exog = sm.add_constant(x, has_constant="add")
    fitted = sm.OLS(y, exog).fit()
    n, dof = len(y), int(fitted.df_resid)
    if dof <= 0 or float(np.var(y)) < EPS:
        raise ModelError("Cannot regress constant asset returns")
    vif = _vifs(x, ordered)
    resid = np.asarray(fitted.resid)
    warnings: list[str] = ["TIME_INDEX_ALIGNMENT_NOT_VERIFIABLE: base schema has no dated observations"]
    if max(vif.values()) > 5.0:
        warnings.append("MULTICOLLINEARITY_WARNING: VIF > 5")
    bp = _test(*het_breuschpagan(resid, exog)[:2])
    try:
        wh = _test(*het_white(resid, exog)[:2])
    except (ValueError, AssertionError, np.linalg.LinAlgError):
        wh = _test(None, None)
        warnings.append("WHITE_TEST_NOT_COMPUTABLE")
    lag = max(1, min(10, n // 10))
    lj = acorr_ljungbox(resid, lags=[lag], return_df=True)
    lb = _test(float(lj["lb_stat"].iloc[0]), float(lj["lb_pvalue"].iloc[0]))
    try:
        bg_values = acorr_breusch_godfrey(fitted, nlags=min(5, n // 10))
        bg = _test(float(bg_values[0]), float(bg_values[1]))
    except (ValueError, np.linalg.LinAlgError):
        bg = _test(None, None)
        warnings.append("BREUSCH_GODFREY_NOT_COMPUTABLE")
    jb_values = jarque_bera(resid)
    jb = _test(float(jb_values[0]), float(jb_values[1]))
    hetero_detected = any(t.reject_at_5pct for t in (bp, wh) if t.status == "COMPLETED")
    autocorr_detected = any(t.reject_at_5pct for t in (lb, bg) if t.status == "COMPLETED")
    if hetero_detected:
        warnings.append("HETEROSKEDASTICITY_DETECTED: classical standard errors may be biased")
    if autocorr_detected:
        warnings.append("AUTOCORRELATION_DETECTED: classical standard errors may be biased")
    hac_lags = max(1, min(10, int(round(4 * (n / 100) ** (2 / 9)))))
    hac = fitted.get_robustcov_results(cov_type="HAC", maxlags=hac_lags)
    hac_summary = {k: {"se": round(_finite(s, f"HAC:{k}"), 8),
                       "p_value": round(_finite(p, f"HAC:{k}"), 8)}
                   for k, s, p in zip(["alpha", *ordered], hac.bse, hac.pvalues)}
    warnings.append("HAC_ROBUST_INFERENCE:" + json.dumps(hac_summary, sort_keys=True))

    # Newey-West HAC correction applied if autocorrelation or heteroskedasticity detected (İP-11)
    use_hac = hetero_detected or autocorr_detected
    if use_hac:
        warnings.append("NEWEY_WEST_HAC_STANDARD_ERRORS_APPLIED: robust errors used due to detected violation")
    active_bse = hac.bse if use_hac else fitted.bse

    first, second = slice(0, n // 2), slice(n // 2, n)
    first_coeff = np.linalg.lstsq(exog[first], y[first], rcond=None)[0]
    last_coeff = np.linalg.lstsq(exog[second], y[second], rcond=None)[0]
    # Relative split-window drift in units of full-sample coefficient SE.
    split_change = np.abs(last_coeff[1:] - first_coeff[1:]) / np.maximum(fitted.bse[1:], EPS)
    max_change = float(np.max(split_change))
    drift: Literal["STABLE", "MODERATE_DRIFT", "HIGH_DRIFT"] = (
        "HIGH_DRIFT" if max_change > 3 else "MODERATE_DRIFT" if max_change > 1.5 else "STABLE"
    )
    def coefficient(name: str) -> Coefficient:
        if name not in ordered:
            return _missing_coeff()
        idx = ordered.index(name) + 1
        return _coeff(float(fitted.params[idx]), float(active_bse[idx]), dof)
    betas = FactorBetas(
        intercept_alpha=_coeff(float(fitted.params[0]), float(active_bse[0]), dof),
        market_beta=coefficient("mkt_rf"), size_smb=coefficient("smb"),
        value_hml=coefficient("hml"), profitability_rmw=coefficient("rmw"),
        investment_cma=coefficient("cma"), momentum_umd=coefficient("umd"),
        low_vol_beta=coefficient("low_vol"),
    )
    annual = _annual_frequency(data.frequency)
    residual_sd = _finite(np.sqrt(float(fitted.mse_resid)), "residual standard deviation")
    radar = _statistical_radar(betas, residual_sd, valuation_inputs.radar_reference, warnings)
    return FactorExposureAnalysis(
        betas=betas,
        regression_diagnostics=RegressionDiagnostics(
            alpha_annualized_pct=_finite(float(fitted.params[0]) * annual * 100, "alpha"),
            r_squared=_finite(np.clip(fitted.rsquared, 0, 1), "R_squared"),
            adjusted_r_squared=_finite(fitted.rsquared_adj, "adjusted_R_squared"),
            tracking_error_pct=_finite(np.std(resid, ddof=1) * np.sqrt(annual) * 100, "tracking error"),
            style_drift_indicator=drift, observations=n, degrees_of_freedom=dof,
            residual_sigma_pct=residual_sd * 100, covariance_method="OLS_CLASSICAL_T_WITH_HAC_DIAGNOSTIC",
            vif=vif, breusch_pagan=bp, white=wh, ljung_box=lb,
            breusch_godfrey=bg, durbin_watson=_finite(durbin_watson(resid), "durbin_watson"),
            jarque_bera=jb, warnings=warnings,
        ), factor_radar_zscores=radar,
    )


def _median_growth(revenues: list[float]) -> float:
    changes = [b / a - 1 for a, b in zip(revenues[:-1], revenues[1:])]
    return float(np.clip(np.median(changes[-5:]), -0.20, 0.25))


def _forecast(payload: FactorValuationInputPayload, warnings: list[str]) -> tuple[list[float], list[float]]:
    fin, extras = payload.historical_financials, payload.valuation_inputs
    horizon = len(extras.forecast_fcff or extras.forecast_revenue or [0] * 5)
    hist_revenue = fin.revenue[-1]
    growth = _median_growth(fin.revenue)
    revenues = (list(extras.forecast_revenue) if extras.forecast_revenue is not None else
                [hist_revenue * (1 + growth) ** t for t in range(1, horizon + 1)])
    if extras.forecast_fcff is not None:
        fcffs = list(extras.forecast_fcff)
        if extras.fcf_is_unlevered_fcff is not True:
            warnings.append("PROJECTED_FCF_BASIS_NOT_VERIFIED: forecast_fcff must be unlevered")
    else:
        if extras.fcf_is_unlevered_fcff is not True:
            warnings.append("HISTORICAL_FREE_CASH_FLOW_ASSUMED_UNLEVERED_FCFF")
        margin = float(np.median([fcf / rev for fcf, rev in zip(fin.free_cash_flow[-3:], fin.revenue[-3:])]))
        if margin <= 0:
            raise ModelError("Negative/zero FCF margin requires an explicit forecast_fcff with positive terminal year")
        fcffs = [margin * r for r in revenues]
        warnings.append("FCFF_FORECAST_HISTORICAL_MEDIAN_MARGIN_AND_CAPPED_REVENUE_GROWTH")
    if fcffs[-1] <= 0:
        raise ModelError("Terminal projected FCFF must be positive; no fabricated crossover to profitability")
    if fin.free_cash_flow[-1] <= 0 and extras.sector_terminal_ebit_margin is None:
        raise ModelError("Negative latest FCF needs sector_terminal_ebit_margin to model operating-margin crossover")
    return revenues, fcffs


def _wacc(
    p: FactorValuationInputPayload, beta: float, warnings: list[str],
) -> tuple[float, float, float | None, float]:
    ins, mac = p.instrument_summary, p.macro_assumptions
    ke = mac.risk_free_rate + beta * mac.equity_risk_premium
    if ke <= 0:
        raise ModelError("CAPM cost of equity is nonpositive; WACC cannot be defensibly established")
    debt = ins.gross_debt
    if debt is None:
        debt = max(ins.net_debt, 0.0)
        warnings.append("NET_DEBT_USED_AS_GROSS_DEBT_PROXY_IN_WACC")
    equity = ins.market_cap
    weight_debt = debt / (equity + debt)
    if debt > 0 and mac.pre_tax_cost_of_debt is None:
        raise ModelError("pre_tax_cost_of_debt is mandatory when gross or proxy debt > 0")
    kd = mac.pre_tax_cost_of_debt
    wacc = (1 - weight_debt) * ke + weight_debt * (kd or 0.0) * (1 - mac.effective_tax_rate)
    if wacc <= 0:
        raise ModelError("WACC must be positive")
    return float(wacc), float(ke), kd, float(weight_debt)


def _growth_guard(g: float, wacc: float, warnings: list[str], label: str) -> float:
    if g > 0.03 + EPS:
        raise ModelError(f"Terminal growth {label} exceeds 3%")
    if wacc <= g:
        new_g = min(0.03, wacc - 0.02)
        if new_g <= -1:
            raise ModelError("Terminal-growth clamp yields a mathematically invalid rate")
        warnings.append(f"TERMINAL_GROWTH_CLAMPED:{label}:{g:.7f}->{new_g:.7f}")
        g = new_g
    if wacc <= g or g <= -1:
        raise ModelError(f"Invalid Gordon growth for {label}")
    return g


def _dcf_price(fcff: list[float], wacc: float, growth: float,
               instrument: InstrumentSummary, warnings: list[str],
               label: str) -> tuple[float, float, float, float]:
    effective_g = _growth_guard(growth, wacc, warnings, label)
    n = len(fcff)
    terminal = fcff[-1] * (1 + effective_g) / (wacc - effective_g)
    ev = sum(f / ((1 + wacc) ** i) for i, f in enumerate(fcff, 1)) + terminal / (1 + wacc) ** n
    equity = ev - instrument.net_debt - instrument.minority_interests
    price = _positive(equity / instrument.shares_outstanding_diluted, f"DCF price {label}")
    return _finite(ev, "enterprise value"), _finite(equity, "equity value"), price, effective_g


def _multiples(p: FactorValuationInputPayload, revenues: list[float],
               fcff: list[float], warnings: list[str]) -> RelativeMultiplesValuation:
    fin, ins, peers, extra = (p.historical_financials, p.instrument_summary,
                              p.peer_multiples_benchmark, p.valuation_inputs)
    growth = revenues[0] / fin.revenue[-1]
    income = (extra.forward_net_income if extra.forward_net_income is not None
              else fin.net_income[-1] / fin.revenue[-1] * revenues[0])
    if income <= 0:
        raise ModelError("forward_net_income <= 0: forward P/E undefined; supply a positive forward estimate")
    if extra.forward_ebitda is not None:
        ebitda = extra.forward_ebitda
    elif fin.depreciation_amortization is not None:
        ebitda = (fin.ebit[-1] + fin.depreciation_amortization[-1]) * growth
        warnings.append("FORWARD_EBITDA_EXTRAPOLATED_FROM_HISTORICAL_EBIT_AND_DA")
    else:
        raise ModelError("EV/EBITDA needs forward_ebitda or historical depreciation_amortization")
    if ebitda <= 0:
        raise ModelError("Forward EBITDA <= 0; EV/EBITDA comparison undefined")
    equity_fcf = extra.forward_equity_fcf
    if equity_fcf is None:
        equity_fcf = fcff[0]
        warnings.append("PFCF_USING_UNLEVERED_FCFF_PROXY: supply forward_equity_fcf")
    if equity_fcf <= 0:
        raise ModelError("Forward equity free cash flow <= 0; P/FCF undefined")
    vals = {
        "forward_pe": peers.forward_pe.representative(),
        "ev_ebitda": peers.ev_ebitda.representative(),
        "pfcf": peers.price_to_fcf.representative(),
    }
    pe_price = _positive(income * vals["forward_pe"] / ins.shares_outstanding_diluted, "Forward P/E")
    ev_price = _positive((ebitda * vals["ev_ebitda"] - ins.net_debt - ins.minority_interests)
                         / ins.shares_outstanding_diluted, "EV/EBITDA")
    pfcf_price = _positive(equity_fcf * vals["pfcf"] / ins.shares_outstanding_diluted, "P/FCF")
    composite = (pe_price + ev_price + pfcf_price) / 3
    if peers.peers_count is None or peers.peers_count < 5:
        warnings.append("SMALL_OR_UNDISCLOSED_PEER_SAMPLE")
    return RelativeMultiplesValuation(
        implied_by_forward_pe=pe_price, implied_by_ev_ebitda=ev_price,
        implied_by_pfcf=pfcf_price, composite_multiples_fair_value=composite,
        benchmark_multiples=vals, warnings=warnings,
    )


def _ddm(p: FactorValuationInputPayload, ke: float, warnings: list[str]) -> DDMModel:
    divs = p.historical_financials.dividends_paid
    if divs is None or len(divs) < 3 or not all(d > 0 for d in divs[-3:]):
        return DDMModel(status="NOT_APPLICABLE", fair_value_per_share=None,
                        applicability_note="No consecutive positive dividends in the last 3 fiscal years")
    g = p.macro_assumptions.terminal_growth_rate
    if ke <= g:
        g = _growth_guard(g, ke, warnings, "DDM")
    # No direct dividend forecasts in base schema; conservative Gordon assumption.
    dps = divs[-1] / p.instrument_summary.shares_outstanding_diluted
    fair = _positive(dps * (1 + g) / (ke - g), "DDM price")
    warnings.append("DDM_CONSTANT_GROWTH_ASSUMPTION_NOT_A_DIVIDEND_FORECAST")
    return DDMModel(status="COMPLETED", fair_value_per_share=fair,
                    applicability_note="Gordon growth; three consecutive annual dividend payments",
                    cost_of_equity_pct=ke * 100, dividend_growth_pct=g * 100)


def _scenario_fcff(baseline: list[float], revenues: list[float],
                   scenario: str) -> list[float]:
    if scenario == "BASE":
        return list(baseline)
    sign = 1.0 if scenario == "BULL" else -1.0
    result: list[float] = []
    horizon = len(baseline)
    for year, (f, rev) in enumerate(zip(baseline, revenues), 1):
        margin_change = sign * 0.015 * (year / horizon) * rev
        growth_change = max(f, 0.0) * ((1 + sign * 0.04) ** year - 1)
        result.append(f + margin_change + growth_change)
    return result


def _scenario_multiplier(base: float, scenario: str) -> float:
    return base * {"BULL": 1.15, "BASE": 1.0, "BEAR": 0.85}[scenario]


def _source_report(mac: MacroAssumptions, uses_debt: bool,
                   warnings: list[str]) -> dict[str, AssumptionEvidence | None]:
    ev = mac.evidence or MacroEvidence()
    wanted = ["risk_free_rate", "equity_risk_premium", "terminal_growth_rate"]
    if uses_debt:
        wanted.append("pre_tax_cost_of_debt")
    result: dict[str, AssumptionEvidence | None] = {}
    for item in wanted:
        source = getattr(ev, item)
        result[item] = source
        if source is None:
            warnings.append("SOURCE_MISSING:" + item)
    return result


def _sensitivity(fcff: list[float], ins: InstrumentSummary, base_wacc: float,
                 g: float, warnings: list[str]) -> SensitivityMatrix:
    if base_wacc <= 0.01:
        waccs = [base_wacc * m for m in (0.5, 0.75, 1.0, 1.25, 1.5)]
    else:
        waccs = [base_wacc + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    gs = [float(x) for x in np.linspace(max(-0.025, g - 0.008), min(0.03, g + 0.008), 5)]
    price_grid: list[list[float]] = []
    effective_grid: list[list[float]] = []
    local_warnings: list[str] = []
    for i, w in enumerate(waccs):
        row: list[float] = []
        eff: list[float] = []
        for j, growth in enumerate(gs):
            _, _, price, g_effective = _dcf_price(fcff, w, growth, ins,
                                                  local_warnings, f"SENSITIVITY[{i},{j}]")
            row.append(price)
            eff.append(g_effective)
        price_grid.append(row)
        effective_grid.append(eff)
    warnings.extend(local_warnings)
    return SensitivityMatrix(wacc_steps=waccs, terminal_growth_steps=gs,
                             fair_price_grid=price_grid,
                             effective_terminal_growth_grid=effective_grid,
                             warnings=local_warnings)


def analyze(payload: FactorValuationInputPayload | dict) -> FactorValuationResultPayload:
    """Pure read-only valuation process. Raises ModelError on unidentifiable cases.

    Missing benchmark EBITDA, negative final FCFF, missing debt-cost, or an
    equity value <= 0 are errors, never silently replaced by zeros.
    """
    if not isinstance(payload, FactorValuationInputPayload):
        payload = FactorValuationInputPayload.model_validate(payload)
    ins, mac = payload.instrument_summary, payload.macro_assumptions
    risks: list[str] = []
    factor = analyze_factors(payload.return_series_summary, payload.valuation_inputs)
    risks.extend(factor.regression_diagnostics.warnings)
    beta = factor.betas.market_beta.coefficient
    assert beta is not None
    revenues, fcff = _forecast(payload, risks)
    wacc, ke, kd, debt_weight = _wacc(payload, beta, risks)
    source_map = _source_report(mac, debt_weight > 0, risks)
    for source_name, evidence in source_map.items():
        if evidence is not None and evidence.as_of_date > ins.as_of_date:
            raise ModelError(f"{source_name} evidence is dated after instrument as_of_date")
    if payload.valuation_inputs.sector_terminal_ebit_margin is not None:
        starting_margin = payload.historical_financials.ebit[-1] / payload.historical_financials.revenue[-1]
        target_margin = payload.valuation_inputs.sector_terminal_ebit_margin
        forecast_ebit = [rev * (starting_margin + (target_margin - starting_margin) * year / len(revenues))
                         for year, rev in enumerate(revenues, start=1)]
        risks.append("OPERATING_MARGIN_CONVERGES_TO_USER_SUPPLIED_SECTOR_BENCHMARK")
    else:
        margin = payload.historical_financials.ebit[-1] / payload.historical_financials.revenue[-1]
        forecast_ebit = [margin * rev for rev in revenues]
        risks.append("EBIT_MARGINS_HELD_CONSTANT_NO_SECTOR_BENCHMARK")
    if abs(mac.terminal_growth_rate - 0.022) > 1e-9:
        risks.append("SCENARIO_G_RATE_SHIFTED_WITH_MACRO_BASE_G: 2.2% is spec reference")
    # Base g is user-supplied; bull/bear are +/- 0.6 / 0.7 percentage points.
    base_g = mac.terminal_growth_rate
    expected_g = {"BULL": min(0.03, base_g + 0.006),
                  "BASE": base_g, "BEAR": base_g - 0.007}
    scenario_wacc = {"BULL": max(0.0001, wacc - 0.01),
                     "BASE": wacc, "BEAR": wacc + 0.015}
    if wacc <= 0.01:
        risks.append("LOW_WACC_BULL_SHIFT_BOUNDED_AT_POSITIVE_RATE")
    multiple_warnings: list[str] = []
    multiples = _multiples(payload, revenues, fcff, multiple_warnings)
    risks.extend(multiple_warnings)
    ddm = _ddm(payload, ke, risks)
    model_weights = ({"dcf": 0.60, "multiples": 0.40, "ddm": 0.0}
                     if ddm.status == "NOT_APPLICABLE" else
                     {"dcf": 0.50, "multiples": 0.30, "ddm": 0.20})
    scenario_cases: dict[str, ScenarioCase] = {}
    dcf_base: tuple[float, float, float, float] | None = None
    for label, prob in (("BULL", 0.25), ("BASE", 0.50), ("BEAR", 0.25)):
        profile = _scenario_fcff(fcff, revenues, label)
        if profile[-1] <= 0:
            raise ModelError(f"{label} terminal FCFF <= 0: provide defensible forecasts")
        local_warning: list[str] = []
        dcf_tuple = _dcf_price(profile, scenario_wacc[label], expected_g[label],
                               ins, local_warning, label)
        risks.extend(local_warning)
        ev, equity, dcf_price, effective_g = dcf_tuple
        if label == "BASE":
            dcf_base = dcf_tuple
        multiple_price = _positive(_scenario_multiplier(
            multiples.composite_multiples_fair_value, label), "scenario multiples")
        ddm_price = None
        if ddm.fair_value_per_share is not None:
            ddm_price = _positive(_scenario_multiplier(ddm.fair_value_per_share, label),
                                  "scenario dividend model")
        combined = _positive(model_weights["dcf"] * dcf_price +
                             model_weights["multiples"] * multiple_price +
                             model_weights["ddm"] * (ddm_price or 0.0), "scenario blended price")
        scenario_cases[label] = ScenarioCase(
            probability=prob, terminal_growth_pct=effective_g * 100,
            wacc_pct=scenario_wacc[label] * 100,
            projected_fcff=profile, dcf_price=dcf_price, multiples_price=multiple_price,
            ddm_price=ddm_price, fair_value_per_share=combined,
            rationale={"BULL": "Growth +4%/yr, FCFF margin +1.5pp at horizon; WACC -1pp",
                       "BASE": "Historical/reported FCFF path, WACC derived from CAPM and capital structure",
                       "BEAR": "Growth -4%/yr, FCFF margin -1.5pp at horizon; WACC +1.5pp"}[label],
        )
    if dcf_base is None:
        raise ModelError("Internal error: base DCF not computed")
    ev, equity, dcf_price, effective_g = dcf_base
    dcf = DCFModel(status="COMPLETED", wacc_pct=wacc * 100,
                   terminal_growth_pct=effective_g * 100,
                   enterprise_value=ev, equity_value=equity, fair_value_per_share=dcf_price,
                   forecast_fcff=fcff, forecast_ebit=forecast_ebit, cost_of_equity_pct=ke * 100,
                   cost_of_debt_pct=None if kd is None else kd * 100,
                   capital_structure_debt_weight=debt_weight,
                   warnings=[w for w in risks if "WACC" in w or "FCFF" in w or "GROWTH" in w])
    weighted = sum(case.probability * case.fair_value_per_share
                   for case in scenario_cases.values())
    weighted = _positive(weighted, "weighted scenario fair value")
    bounds = [v.fair_value_per_share for v in scenario_cases.values()]
    bands = ScenarioBands(bull_case=scenario_cases["BULL"],
                          base_case=scenario_cases["BASE"],
                          bear_case=scenario_cases["BEAR"],
                          weighted_fair_value=weighted,
                          margin_of_safety_pct=(weighted - ins.current_price) / weighted * 100,
                          price_range_low=min(bounds), price_range_high=max(bounds),
                          weighting_method=model_weights)
    sensitivity = _sensitivity(fcff, ins, wacc, base_g, risks)
    mos = bands.margin_of_safety_pct
    # Not a trading rule: descriptive relative valuation classification.
    regime: Literal["SIGNIFICANTLY_UNDERVALUED", "FAIRLY_VALUED", "SIGNIFICANTLY_OVERVALUED"] = (
        "SIGNIFICANTLY_UNDERVALUED" if mos >= 20 else
        "SIGNIFICANTLY_OVERVALUED" if mos <= -20 else "FAIRLY_VALUED"
    )
    active = {
        "VALUE": factor.betas.value_hml,
        "QUALITY": factor.betas.profitability_rmw,
        "MOMENTUM": factor.betas.momentum_umd,
        "SMALL_CAP": factor.betas.size_smb,
        "CONSERVATIVE_INVESTMENT": factor.betas.investment_cma,
    }
    eligible = [(name, abs(c.coefficient or 0.0)) for name, c in active.items()
                if c.status == "ESTIMATED" and c.significant_at_5pct]
    main_style = max(eligible, key=lambda kv: kv[1])[0] if eligible else "NO_SIGNIFICANT_STYLE"
    # Stable de-duplication, keeping all assumptions and diagnostics in order.
    risks = list(dict.fromkeys(risks))
    return FactorValuationResultPayload(
        metadata=Metadata(instrument_id=ins.instrument_id, ticker=ins.ticker,
                          currency=ins.currency, current_price=ins.current_price,
                          analysis_timestamp=datetime.now(timezone.utc), as_of_date=ins.as_of_date),
        factor_exposure_analysis=factor,
        intrinsic_valuation_models=IntrinsicValuationModels(dcf_model=dcf, ddm_model=ddm),
        relative_multiples_valuation=multiples,
        scenario_bands=bands, sensitivity_matrix=sensitivity,
        synthesis_summary=SynthesisSummary(
            valuation_regime=regime, primary_factor_style=main_style,
            key_risks=risks, assumption_evidence=source_map,
        ),
    )


def analyze_json(payload_json: str) -> str:
    """Strict JSON in, strict JSON out. No external data requests/actions."""
    request = FactorValuationInputPayload.model_validate_json(payload_json)
    return analyze(request).model_dump_json(indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only factor/valuation engine")
    parser.add_argument("--input", type=Path, help="Input JSON file (default stdin)")
    parser.add_argument("--output", type=Path, help="Output JSON file (default stdout)")
    args = parser.parse_args(argv)
    try:
        content = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        result = analyze_json(content)
        if args.output:
            args.output.write_text(result + "\n", encoding="utf-8")
        else:
            sys.stdout.write(result + "\n")
        return 0
    except (ValueError, ArithmeticError) as exc:
        print(f"VALUATION_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
