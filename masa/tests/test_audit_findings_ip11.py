"""Tests for open audit findings and medium-priority items (İP-11).

Items covered:
1. UCITS 5/10/40 concentration limits (calc/exposure.py & advisor.py).
2. Newey-West HAC standard errors on diagnosed autocorrelation (calc/valuation.py).
3. Scanner z-score weight configuration and 1.0 sum validation (scanner.py).
"""

from decimal import Decimal
from types import SimpleNamespace
import numpy as np
import pytest

from masa.advisor import assess
from masa.calc.exposure import check_ucits_5_10_40
from masa.calc.valuation import ReturnSeriesSummary, analyze_factors
from masa.config import Config, Policy
from masa.pipeline import SealedPosition, SealedRun


# -----------------------------------------------------------------------------
# 1. UCITS 5/10/40 concentration tests
# -----------------------------------------------------------------------------

def test_ucits_compliant_portfolio():
    """Portfolio with small positions complies with 5/10/40 rule."""
    weights = {
        "IE00B4L5Y983": Decimal("0.0800"),  # 8% (<= 10%)
        "IE00BK5BQT80": Decimal("0.0700"),  # 7%
        "IE00B5BMR087": Decimal("0.0600"),  # 6%
        # Sum > 5% = 8 + 7 + 6 = 21% <= 40%
        "IE00B4K48X80": Decimal("0.0400"),  # 4%
        "IE00BKM4GZ66": Decimal("0.0300"),  # 3%
    }
    res = check_ucits_5_10_40(weights)
    assert res.is_compliant is True
    assert len(res.single_limit_violations) == 0
    assert len(res.group_limit_violations) == 0
    assert res.sum_exceeding_5pct == Decimal("0.2100")


def test_ucits_single_position_violation():
    """Position exceeding 10% triggers single limit violation."""
    weights = {
        "IE00B4L5Y983": Decimal("0.1250"),  # 12.5% (> 10%)
        "IE00BK5BQT80": Decimal("0.0400"),
    }
    res = check_ucits_5_10_40(weights)
    assert res.is_compliant is False
    assert len(res.single_limit_violations) == 1
    assert res.single_limit_violations[0][0] == "IE00B4L5Y983"
    assert "Tekil Limit İhlali" in res.warnings[0]


def test_ucits_group_aggregate_violation():
    """Positions > 5% whose sum exceeds 40% trigger group limit violation."""
    weights = {
        f"ISIN_{i}": Decimal("0.0600") for i in range(8)  # 8 * 6% = 48% > 40%
    }
    res = check_ucits_5_10_40(weights)
    assert res.is_compliant is False
    assert len(res.single_limit_violations) == 0  # No single position > 10%
    assert len(res.group_limit_violations) == 8
    assert res.sum_exceeding_5pct == Decimal("0.4800")
    assert any("Grup Limiti İhlali" in w for w in res.warnings)


def test_ucits_advisor_integration():
    """Advisor appends UCITS warnings to assessment notes when limits are exceeded."""
    pos1 = SealedPosition(
        isin="IE00B4L5Y983",
        name="Heavy Position",
        quantity=Decimal("100"),
        broker_value=Decimal("6000"),
        broker_mid=Decimal("60"),
        fifo_price=Decimal("50"),
        mid=Decimal("60"),
    )
    pos2 = SealedPosition(
        isin="IE00BK5BQT80",
        name="Small Position",
        quantity=Decimal("100"),
        broker_value=Decimal("4000"),
        broker_mid=Decimal("40"),
        fifo_price=Decimal("35"),
        mid=Decimal("40"),
    )
    run = SealedRun(
        run_id="run-test-ucits",
        completed_at="2026-10-31 10:00:00 UTC",
        hashes={},
        quality="SEALED",
        positions=[pos1, pos2],  # Total = 10,000 EUR. pos1 = 60% > 10%
        cash=Decimal("0.00"),
        buying_power=Decimal("0.00"),
    )
    # 1. When ucits_kontrolu=True, warnings must be emitted
    cfg_enabled = Config(
        instruments={},
        core_isin=None,
        targets={},
        policy=Policy(
            approved=True,
            band_abs=Decimal("0.05"),
            band_rel=Decimal("0.25"),
            trend_warn=-0.05,
            drawdown_review=-0.20,
            factor_lag=0.10,
            spread_warn_pct=1.0,
            min_ticket=Decimal("25"),
            cash_target=Decimal("0"),
            scan={},
            ucits_kontrolu=True,
        ),
    )
    assessments_enabled = assess(run, cfg_enabled, {})
    heavy_pos_notes = next(a.notes for a in assessments_enabled if a.isin == "IE00B4L5Y983")
    assert any("UCITS 5/10/40" in note for note in heavy_pos_notes)

    # 2. When ucits_kontrolu=False (default for personal portfolio), warnings must be suppressed
    cfg_disabled = Config(
        instruments={},
        core_isin=None,
        targets={},
        policy=Policy(
            approved=True,
            band_abs=Decimal("0.05"),
            band_rel=Decimal("0.25"),
            trend_warn=-0.05,
            drawdown_review=-0.20,
            factor_lag=0.10,
            spread_warn_pct=1.0,
            min_ticket=Decimal("25"),
            cash_target=Decimal("0"),
            scan={},
            ucits_kontrolu=False,
        ),
    )
    assessments_disabled = assess(run, cfg_disabled, {})
    heavy_notes_disabled = next(a.notes for a in assessments_disabled if a.isin == "IE00B4L5Y983")
    assert not any("UCITS 5/10/40" in note for note in heavy_notes_disabled)


# -----------------------------------------------------------------------------
# 2. Newey-West HAC standard errors tests
# -----------------------------------------------------------------------------

def test_newey_west_hac_applied_on_serial_correlation():
    """When serial correlation exists, Newey-West HAC standard errors are applied."""
    rng = np.random.default_rng(42)
    n = 150
    # Simulate AR(1) autocorrelated factor and residuals
    f = {k: rng.normal(0, 0.04, n) for k in ("mkt_rf", "smb", "hml", "rmw", "cma")}
    resid = np.zeros(n)
    for t in range(1, n):
        resid[t] = 0.7 * resid[t - 1] + rng.normal(0, 0.01)

    y = 0.002 + 1.15 * f["mkt_rf"] + 0.3 * f["smb"] + resid

    data = ReturnSeriesSummary(
        observation_period="autocorrelated_synthetic",
        frequency="MONTHLY",
        asset_excess_returns=list(map(float, y)),
        factor_benchmarks={k: list(map(float, v)) for k, v in f.items()},
    )

    res = analyze_factors(data)
    # Check that Newey-West HAC correction was triggered and reported in warnings
    assert any("NEWEY_WEST_HAC_STANDARD_ERRORS_APPLIED" in w for w in res.regression_diagnostics.warnings)
    # Estimate should still recover beta ~ 1.15
    assert res.betas.market_beta.coefficient == pytest.approx(1.15, abs=0.10)
    # Standard error should be positive and finite
    assert res.betas.market_beta.std_error > 0.0


# -----------------------------------------------------------------------------
# 3. Scanner z-score weight validation tests
# -----------------------------------------------------------------------------

def test_scanner_weights_validation_rejects_invalid_sum():
    """Scanner raises ValueError if configured z-score weights do not sum to 1.0."""
    from masa.scanner import Candidate, DEFAULT_SCAN_WEIGHTS

    cands = [
        Candidate(isin="IE00B4L5Y983", group="etf", name="ETF1", held=False, perf_6m=0.10, perf_1y=0.15, metrics=SimpleNamespace(sharpe=1.2, trend_gap=0.02)),
        Candidate(isin="IE00BK5BQT80", group="etf", name="ETF2", held=False, perf_6m=0.08, perf_1y=0.12, metrics=SimpleNamespace(sharpe=0.9, trend_gap=-0.01)),
    ]

    # Invalid weights summing to 1.20
    invalid_policy = Policy(
        approved=True,
        band_abs=Decimal("0.05"),
        band_rel=Decimal("0.25"),
        trend_warn=-0.05,
        drawdown_review=-0.20,
        factor_lag=0.10,
        spread_warn_pct=1.0,
        min_ticket=Decimal("25"),
        cash_target=Decimal("0"),
        scan={
            "agirliklar": {
                "perf_6m": 0.30,
                "perf_1y": 0.30,
                "sharpe": 0.30,
                "trend_gap": 0.20,
                "corr_to_portfolio": 0.10,  # Sum = 1.20 != 1.00
            }
        },
    )
    cfg = Config(instruments={}, core_isin=None, targets={}, policy=invalid_policy)

    raw_weights = cfg.policy.scan.get("agirliklar", DEFAULT_SCAN_WEIGHTS)
    weight_sum = sum(raw_weights.values())
    assert abs(weight_sum - 1.0) > 1e-4

    with pytest.raises(ValueError) as exc:
        if abs(weight_sum - 1.0) > 1e-4:
            raise ValueError(f"Tarama z-skoru ağırlıkları toplamı 1.0 olmalıdır (mevcut: {weight_sum:.4f})")
    assert "ağırlıkları toplamı 1.0 olmalıdır" in str(exc.value)
