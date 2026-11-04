"""Adversarial and Empirical Challenge Test Suite for Work Package 4 (İP-4).

Author: challenger_ip4_2 (Empirical Adversarial Testing Specialist)
Target: masa.calc.overlap, masa.holdings.loader, masa.holdings.ishares_parser, masa.holdings.spdr_parser

Covers:
1. Overlap Symmetry & Boundedness:
   - For any two funds A and B, Overlap(A, B) == Overlap(B, A).
   - 0.0 <= Overlap(A, B) <= 1.0.
   - Overlap(A, A) == Coverage(A).
   - Symmetric N x N matrix.
2. Non-Inflation & Uncovered Holdings:
   - 40% and 70% coverage funds preserve weights without artificial inflation.
   - Uncovered share is preserved exactly as UNCOVERED_ETF_HOLDINGS.
3. Top 25 Accounting Identity:
   - Top 25 + OTHER_STOCKS + UNCOVERED_ETF_HOLDINGS + CASH == 1.0000 +/- 0.0001 (100.0%).
   - Stress tested across arbitrary portfolio configurations via 100-run Monte Carlo generator.
4. 3-Tier Constituent Matching Stress:
   - Tier 1: Alphabet Class A vs C (ENTITY:US_ALPHABET)
   - Tier 1: TSMC ADR vs Ordinary (ENTITY:TW_TSMC)
   - Tier 1: Distinct ISINs with identical names never match.
   - Tier 2: Ticker collision resistance and ticker fallback when ISIN missing.
   - Tier 3: Company name normalization edge cases.
   - Vulnerability: Cross-tier static key mismatch between ISIN and Ticker items.
   - Edge case: Short name normalization (< 3 chars, e.g. '3M').
5. Staleness Detection Boundaries:
   - Day 44 (fresh, False)
   - Day 45 (threshold boundary, False)
   - Day 46 (stale boundary, True)
   - Negative age / future dates.
6. Extreme Boundary Conditions:
   - 0 Cash portfolio.
   - Single ETF portfolio (1x1 matrix).
   - 100% Cash portfolio.
   - Zero-valuation EUR (0.00 EUR).
   - None EUR valuation.
   - Empty fund basket (0 holdings).
7. Empirical Vulnerabilities in Worker IP-4 Draft:
   - BUG-1: Positive derivative / non-equity double counting in calculate_consolidated_exposure.
   - BUG-2: Live run cash inflation in run_portfolio_overlap_analysis (ETF weights normalized to 1.0 then cash added -> 1.20).
   - BUG-3: Unloaded ETF weight inflation in run_portfolio_overlap_analysis.
   - BUG-4: Multiple comma thousands separators in clean_decimal ('1,234,567' -> None).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import random
from typing import List
from unittest.mock import MagicMock, patch
import pytest

from masa.calc.overlap import (
    ConstituentHolding,
    FundHoldings,
    build_overlap_matrix,
    calculate_consolidated_exposure,
    calculate_pairwise_overlap,
    check_staleness,
    get_constituent_match_key,
    match_constituents,
    normalize_constituent_name,
    run_portfolio_overlap_analysis,
)
from masa.holdings.ishares_parser import clean_decimal
from masa.holdings.models import AssetClass
from masa.storage.db import DatabaseManager


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

def build_test_fund(
    isin: str,
    name: str,
    holdings: List[ConstituentHolding],
    as_of: date = date(2026, 10, 20),
) -> FundHoldings:
    """Helper to construct a FundHoldings instance with accurately summed weights."""
    total_w = sum((h.weight for h in holdings), Decimal("0"))
    eq_w = sum((h.weight for h in holdings if h.asset_class == AssetClass.EQUITY.value), Decimal("0"))
    cash_w = sum((h.weight for h in holdings if h.asset_class == AssetClass.CASH.value), Decimal("0"))
    deriv_w = sum((h.weight for h in holdings if h.asset_class == AssetClass.DERIVATIVE.value), Decimal("0"))
    return FundHoldings(
        isin=isin,
        fund_name=name,
        as_of_date=as_of,
        total_weight=total_w,
        equity_weight=eq_w,
        cash_weight=cash_w,
        derivative_weight=deriv_w,
        holdings=holdings,
    )


# =============================================================================
# 1. Overlap Symmetry & Boundedness
# =============================================================================

def test_overlap_mathematical_symmetry():
    """Verify Overlap(A, B) == Overlap(B, A) across distinct asymmetric fund holdings."""
    fund_a = build_test_fund(
        isin="FUND_AAA",
        name="Alpha ETF",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.45")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.35")),
            ConstituentHolding(holding_isin="US0231351067", ticker="AMZN", name="Amazon.com Inc.", weight=Decimal("0.20")),
        ],
    )
    fund_b = build_test_fund(
        isin="FUND_BBB",
        name="Beta ETF",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.15")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.55")),
            ConstituentHolding(holding_isin="US67066G1040", ticker="NVDA", name="NVIDIA Corp.", weight=Decimal("0.30")),
        ],
    )

    # Expected: min(0.45, 0.15) + min(0.35, 0.55) = 0.15 + 0.35 = 0.50
    res_ab = calculate_pairwise_overlap(fund_a, fund_b)
    res_ba = calculate_pairwise_overlap(fund_b, fund_a)

    assert res_ab.overlap_score == Decimal("0.50")
    assert res_ba.overlap_score == Decimal("0.50")
    assert res_ab.overlap_score == res_ba.overlap_score
    assert res_ab.shared_count == 2
    assert res_ba.shared_count == 2


def test_overlap_boundedness_zero_and_one():
    """Verify 0.0 <= Overlap(A, B) <= 1.0 for completely disjoint and identical funds."""
    # Disjoint funds
    fund_x = build_test_fund(
        isin="FUND_XXX",
        name="Fund X",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("1.00")),
        ],
    )
    fund_y = build_test_fund(
        isin="FUND_YYY",
        name="Fund Y",
        holdings=[
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("1.00")),
        ],
    )

    res_disjoint = calculate_pairwise_overlap(fund_x, fund_y)
    assert res_disjoint.overlap_score == Decimal("0.0")
    assert res_disjoint.shared_count == 0

    # Identical clone funds (different ISINs)
    fund_clone = build_test_fund(
        isin="FUND_X_CLONE",
        name="Fund X Clone",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("1.00")),
        ],
    )
    res_clone = calculate_pairwise_overlap(fund_x, fund_clone)
    assert res_clone.overlap_score == Decimal("1.00")
    assert res_clone.shared_count == 1


def test_overlap_self_coverage_identity():
    """Verify Overlap(A, A) == Coverage(A) (equity_weight)."""
    # 75% equity coverage, 25% cash
    fund_partial = build_test_fund(
        isin="FUND_PARTIAL",
        name="Partial Fund",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.40")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.35")),
            ConstituentHolding(holding_isin=None, ticker="CASH", name="USD Cash", weight=Decimal("0.25"), asset_class=AssetClass.CASH.value),
        ],
    )
    res_self = calculate_pairwise_overlap(fund_partial, fund_partial)
    assert res_self.overlap_score == Decimal("0.75")
    assert res_self.overlap_score == fund_partial.equity_weight


def test_overlap_matrix_symmetry():
    """Verify N x N matrix symmetry: M[i][j] == M[j][i] and M[i][i] == Coverage(i)."""
    f1 = build_test_fund("F1", "Fund 1", [
        ConstituentHolding(holding_isin="US1", name="S1", weight=Decimal("0.60")),
        ConstituentHolding(holding_isin="US2", name="S2", weight=Decimal("0.40")),
    ])
    f2 = build_test_fund("F2", "Fund 2", [
        ConstituentHolding(holding_isin="US1", name="S1", weight=Decimal("0.30")),
        ConstituentHolding(holding_isin="US3", name="S3", weight=Decimal("0.70")),
    ])
    f3 = build_test_fund("F3", "Fund 3", [
        ConstituentHolding(holding_isin="US2", name="S2", weight=Decimal("0.50")),
        ConstituentHolding(holding_isin="US3", name="S3", weight=Decimal("0.50")),
    ])

    matrix = build_overlap_matrix([f1, f2, f3])
    n = 3
    for i in range(n):
        for j in range(n):
            assert matrix.matrix[i][j] == matrix.matrix[j][i]
        assert matrix.matrix[i][i] == [f1, f2, f3][i].equity_weight


# =============================================================================
# 2. Non-Inflation & Uncovered Holdings Invariant
# =============================================================================

def test_non_inflation_40_pct_coverage():
    """For a fund with 40% coverage, weights MUST NOT be normalized to 100%, and uncovered share is 60%."""
    fund_40 = build_test_fund(
        isin="IE00B40COV01",
        name="40 Percent Coverage Fund",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.25")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.15")),
        ],
    )
    assert fund_40.equity_weight == Decimal("0.40")

    summary, bd = calculate_consolidated_exposure(
        funds=[fund_40],
        fund_weights={"IE00B40COV01": Decimal("1.00")},
    )

    # Weights must NOT be scaled up (AAPL must remain 0.25, MSFT 0.15)
    assert summary.top_stocks[0].portfolio_weight == Decimal("0.25")
    assert summary.top_stocks[1].portfolio_weight == Decimal("0.15")
    assert summary.top25_weight == Decimal("0.40")
    assert summary.uncovered_etf_weight == Decimal("0.60")
    assert summary.cash_weight == Decimal("0.00")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


def test_non_inflation_70_pct_coverage_with_portfolio_cash():
    """For fund with 70% equity + 10% fund cash (20% uncovered) in a portfolio with 20% direct cash."""
    fund_70 = build_test_fund(
        isin="IE00B70COV02",
        name="70 Percent Coverage Fund",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.50")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.20")),
            ConstituentHolding(holding_isin=None, ticker="CASH", name="Fund Cash", weight=Decimal("0.10"), asset_class=AssetClass.CASH.value),
        ],
    )
    # Portfolio: 80% fund_70, 20% direct cash
    summary, bd = calculate_consolidated_exposure(
        funds=[fund_70],
        fund_weights={"IE00B70COV02": Decimal("0.80")},
        portfolio_cash_weight=Decimal("0.20"),
    )

    # Expected:
    # AAPL: 0.80 * 0.50 = 0.40 (40%)
    # MSFT: 0.80 * 0.20 = 0.16 (16%)
    # Total stocks = 0.56 (56%)
    # Cash: direct 0.20 + fund (0.80 * 0.10) = 0.28 (28%)
    # Uncovered ETF: 0.80 * (1 - 0.70 - 0.10) = 0.80 * 0.20 = 0.16 (16%)
    # Total = 0.56 + 0.28 + 0.16 = 1.00 (100.0%)
    assert summary.top_stocks[0].portfolio_weight == Decimal("0.40")
    assert summary.top_stocks[1].portfolio_weight == Decimal("0.16")
    assert summary.top25_weight == Decimal("0.56")
    assert summary.cash_weight == Decimal("0.28")
    assert summary.uncovered_etf_weight == Decimal("0.16")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


# =============================================================================
# 3. Top 25 Accounting Identity Stress
# =============================================================================

def test_top25_accounting_identity_exactly_25_stocks():
    """Verify Top 25 accounting identity when fund has exactly 25 stocks."""
    stocks = [
        ConstituentHolding(holding_isin=f"US{i:010d}", ticker=f"T{i}", name=f"Company {i}", weight=Decimal("0.038"))
        for i in range(1, 26)
    ]
    # 25 * 0.038 = 0.950, remaining 0.05 is cash
    stocks.append(
        ConstituentHolding(holding_isin=None, ticker="CASH", name="USD Cash", weight=Decimal("0.05"), asset_class=AssetClass.CASH.value)
    )
    fund = build_test_fund("IE00EXACT25", "Exact 25 Fund", stocks)

    summary, _ = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"IE00EXACT25": Decimal("1.00")},
    )

    assert len(summary.top_stocks) == 25
    assert summary.top25_weight == Decimal("0.95")
    assert summary.other_stocks_weight == Decimal("0.00")
    assert summary.cash_weight == Decimal("0.05")
    assert summary.uncovered_etf_weight == Decimal("0.00")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


def test_top25_accounting_identity_with_direct_stocks():
    """Verify accounting identity holds with combination of ETF + direct stock holdings + cash."""
    fund = build_test_fund(
        isin="IE00COREETF",
        name="Core Index ETF",
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.50")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.40")),
            ConstituentHolding(holding_isin=None, ticker="CASH", name="Cash", weight=Decimal("0.10"), asset_class=AssetClass.CASH.value),
        ],
    )
    direct_holdings = [
        ConstituentHolding(holding_isin="US67066G1040", ticker="NVDA", name="NVIDIA Corp.", weight=Decimal("0.20")),
        ConstituentHolding(holding_isin="US0231351067", ticker="AMZN", name="Amazon.com Inc.", weight=Decimal("0.10")),
    ]

    # Portfolio: 60% ETF, 30% direct stocks (20% + 10%), 10% direct cash
    summary, _ = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"IE00COREETF": Decimal("0.60")},
        direct_holdings=direct_holdings,
        portfolio_cash_weight=Decimal("0.10"),
    )

    # AAPL: 0.60 * 0.50 = 0.30
    # MSFT: 0.60 * 0.40 = 0.24
    # NVDA: 0.20
    # AMZN: 0.10
    # Cash: 0.10 + 0.60 * 0.10 = 0.16
    # Total: 0.30 + 0.24 + 0.20 + 0.10 + 0.16 = 1.00
    assert summary.cash_weight == Decimal("0.16")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


def test_top25_accounting_identity_monte_carlo_generator():
    """100-iteration randomized Monte Carlo stress test for Top 25 accounting identity."""
    random.seed(20261030)

    for iteration in range(100):
        num_funds = random.randint(1, 4)
        direct_cash = Decimal(str(round(random.uniform(0.0, 0.30), 4)))
        remaining_etf_weight = Decimal("1.0000") - direct_cash

        # Distribute remaining between funds
        raw_cuts = sorted([random.uniform(0, float(remaining_etf_weight)) for _ in range(num_funds - 1)])
        cuts = [0.0] + raw_cuts + [float(remaining_etf_weight)]
        f_weights = [Decimal(str(round(cuts[i+1] - cuts[i], 4))) for i in range(num_funds)]
        diff = remaining_etf_weight - sum(f_weights)
        f_weights[0] += diff

        funds = []
        fund_weights_map = {}

        for i in range(num_funds):
            isin = f"IE{i:010d}"
            fund_weights_map[isin] = f_weights[i]

            coverage = Decimal(str(round(random.uniform(0.35, 0.95), 4)))
            fund_cash = Decimal(str(round(random.uniform(0.00, 0.05), 4)))
            if coverage + fund_cash > Decimal("1.0"):
                fund_cash = Decimal("1.0") - coverage

            num_stocks = random.randint(5, 30)
            raw_s = sorted([random.uniform(0, float(coverage)) for _ in range(num_stocks - 1)])
            s_cuts = [0.0] + raw_s + [float(coverage)]
            stk_weights = [Decimal(str(round(s_cuts[k+1] - s_cuts[k], 6))) for k in range(num_stocks)]
            stk_diff = coverage - sum(stk_weights)
            stk_weights[0] += stk_diff

            holdings = []
            for k, sw in enumerate(stk_weights):
                holdings.append(
                    ConstituentHolding(
                        holding_isin=f"US{k:010d}",
                        ticker=f"STK{k}",
                        name=f"Stock Company {k}",
                        weight=sw,
                        asset_class=AssetClass.EQUITY.value,
                    )
                )
            if fund_cash > Decimal("0"):
                holdings.append(
                    ConstituentHolding(
                        holding_isin=None,
                        ticker="CASH",
                        name="USD Cash",
                        weight=fund_cash,
                        asset_class=AssetClass.CASH.value,
                    )
                )

            funds.append(
                FundHoldings(
                    isin=isin,
                    fund_name=f"Random Fund {i}",
                    as_of_date=date(2026, 10, 20),
                    total_weight=coverage + fund_cash,
                    equity_weight=coverage,
                    cash_weight=fund_cash,
                    derivative_weight=Decimal("0"),
                    holdings=holdings,
                )
            )

        summary, _ = calculate_consolidated_exposure(
            funds=funds,
            fund_weights=fund_weights_map,
            portfolio_cash_weight=direct_cash,
        )

        assert abs(summary.total_reconciled_weight - Decimal("1.0")) <= Decimal("0.0001"), (
            f"Monte Carlo Iteration {iteration} failed: total_reconciled = {summary.total_reconciled_weight}"
        )
        assert summary.is_fully_reconciled is True


# =============================================================================
# 4. 3-Tier Constituent Matching Stress
# =============================================================================

def test_matching_tier1_alphabet_dual_class():
    """Alphabet Class A (US02079K3059) and Class C (US02079K1079) must map to ENTITY:US_ALPHABET."""
    item_a = ConstituentHolding(holding_isin="US02079K3059", name="Alphabet Inc. Class A", weight=Decimal("0.05"))
    item_c = ConstituentHolding(holding_isin="US02079K1079", name="Alphabet Inc. Class C", weight=Decimal("0.05"))

    assert get_constituent_match_key(item_a) == "ENTITY:US_ALPHABET"
    assert get_constituent_match_key(item_c) == "ENTITY:US_ALPHABET"
    assert match_constituents(item_a, item_c) == "ENTITY:US_ALPHABET"


def test_matching_tier1_tsmc_adr_vs_ordinary():
    """TSMC ADR (US8740391003) and Ordinary (TW0002330008) must map to ENTITY:TW_TSMC."""
    tsmc_adr = ConstituentHolding(holding_isin="US8740391003", name="TSMC ADR", weight=Decimal("0.08"))
    tsmc_ord = ConstituentHolding(holding_isin="TW0002330008", name="Taiwan Semiconductor Mfg", weight=Decimal("0.08"))

    assert get_constituent_match_key(tsmc_adr) == "ENTITY:TW_TSMC"
    assert get_constituent_match_key(tsmc_ord) == "ENTITY:TW_TSMC"
    assert match_constituents(tsmc_adr, tsmc_ord) == "ENTITY:TW_TSMC"


def test_matching_tier1_distinct_isins_never_match():
    """Two different securities with valid ISINs must never match, even with identical names."""
    sec1 = ConstituentHolding(holding_isin="US0378331005", name="Apple Inc.", weight=Decimal("0.05"))
    sec2 = ConstituentHolding(holding_isin="US5949181045", name="Apple Inc.", weight=Decimal("0.05"))  # Microsoft ISIN
    assert match_constituents(sec1, sec2) is None


def test_matching_tier2_ticker_collision_handling():
    """Ticker matching applies only when at least one security lacks an ISIN."""
    # When both have ISINs, different ISINs with same ticker must NOT match
    with_isin_a = ConstituentHolding(holding_isin="NL0000235190", ticker="AIR", name="Airbus SE", weight=Decimal("0.02"))
    with_isin_b = ConstituentHolding(holding_isin="US0003611052", ticker="AIR", name="AAR Corp", weight=Decimal("0.02"))
    assert match_constituents(with_isin_a, with_isin_b) is None

    # When both lack ISIN, same ticker matches on Tier 2
    no_isin_a = ConstituentHolding(holding_isin=None, ticker="AIR", name="Airbus SE", weight=Decimal("0.02"))
    no_isin_b = ConstituentHolding(holding_isin=None, ticker="AIR", name="Airbus Company", weight=Decimal("0.02"))
    assert match_constituents(no_isin_a, no_isin_b) == "TICKER:AIR"


def test_matching_tier3_name_normalization():
    """Company name normalization strips corporate suffixes, punctuation, and extra whitespace."""
    assert normalize_constituent_name("Apple Inc.") == "apple"
    assert normalize_constituent_name("Apple Corporation") == "apple"
    assert normalize_constituent_name("Apple Corp.") == "apple"
    assert normalize_constituent_name("SAP SE") == "sap"
    assert normalize_constituent_name("SAP AG") == "sap"
    assert normalize_constituent_name("Novo Nordisk A/S") == "novo nordisk"
    assert normalize_constituent_name("Tencent Holdings Ltd.") == "tencent"


def test_edge_case_short_name_normalization_limit():
    """Empirical limitation: Company names with normalized length < 3 chars (e.g. '3M') fail Tier 3 matching."""
    # '3M Company' -> '3m' (length 2 < 3) falls back to RAW key
    c1 = ConstituentHolding(name="3M Company", weight=Decimal("0.02"))
    c2 = ConstituentHolding(name="3M Co", weight=Decimal("0.02"))
    assert get_constituent_match_key(c1) == "RAW:3M COMPANY"
    assert get_constituent_match_key(c2) == "RAW:3M CO"
    assert match_constituents(c1, c2) is None


# =============================================================================
# 5. Staleness Detection Boundaries
# =============================================================================

def test_staleness_exact_day_boundaries():
    """Test boundary conditions for 45-day staleness threshold: Day 44, 45, and 46."""
    ref_date = date(2026, 10, 30)

    # Day 44: Not stale
    d44 = ref_date - timedelta(days=44)
    is_stale_44, age_44 = check_staleness(d44, ref_date=ref_date, threshold_days=45)
    assert is_stale_44 is False
    assert age_44 == 44

    # Day 45: Exactly at threshold (not stale)
    d45 = ref_date - timedelta(days=45)
    is_stale_45, age_45 = check_staleness(d45, ref_date=ref_date, threshold_days=45)
    assert is_stale_45 is False
    assert age_45 == 45

    # Day 46: Exceeds threshold (stale)
    d46 = ref_date - timedelta(days=46)
    is_stale_46, age_46 = check_staleness(d46, ref_date=ref_date, threshold_days=45)
    assert is_stale_46 is True
    assert age_46 == 46


def test_staleness_future_date_handling():
    """Future dates (clock skew) produce age 0 and is_stale = False."""
    ref_date = date(2026, 10, 30)
    future_date = ref_date + timedelta(days=5)
    is_stale, age = check_staleness(future_date, ref_date=ref_date, threshold_days=45)
    assert is_stale is False
    assert age == 0


def test_staleness_warnings_in_portfolio_summary():
    """Stale funds produce explicit human-readable warnings in PortfolioExposureSummary."""
    stale_fund = FundHoldings(
        isin="IE00STALE001",
        fund_name="Stale Index Fund",
        as_of_date=date(2026, 1, 1),
        total_weight=Decimal("1.0"),
        equity_weight=Decimal("1.0"),
        cash_weight=Decimal("0.0"),
        derivative_weight=Decimal("0.0"),
        holdings=[ConstituentHolding(name="Apple", weight=Decimal("1.0"))],
        is_stale=True,
        age_days=300,
    )
    summary, _ = calculate_consolidated_exposure(
        funds=[stale_fund],
        fund_weights={"IE00STALE001": Decimal("1.0")},
    )
    assert len(summary.staleness_warnings) == 1
    assert "IE00STALE001" in summary.staleness_warnings[0]
    assert "45 günden eski" in summary.staleness_warnings[0]


# =============================================================================
# 6. Extreme Boundary Conditions
# =============================================================================

def test_boundary_zero_cash_portfolio():
    """Portfolio with 0 cash reconciles cleanly."""
    fund = build_test_fund("F_Z_CASH", "Zero Cash Fund", [
        ConstituentHolding(name="Stock A", weight=Decimal("1.00")),
    ])
    summary, _ = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"F_Z_CASH": Decimal("1.00")},
        portfolio_cash_weight=Decimal("0.00"),
    )
    assert summary.cash_weight == Decimal("0.00")
    assert summary.is_fully_reconciled is True
    assert summary.total_reconciled_weight == Decimal("1.0000")


def test_boundary_single_etf_portfolio():
    """Portfolio with a single ETF produces a 1x1 matrix and valid lookthrough."""
    fund = build_test_fund("F_SINGLE", "Single Fund", [
        ConstituentHolding(name="Apple", weight=Decimal("0.60")),
        ConstituentHolding(name="Microsoft", weight=Decimal("0.40")),
    ])
    matrix = build_overlap_matrix([fund])
    assert len(matrix.matrix) == 1
    assert matrix.matrix[0][0] == Decimal("1.00")

    summary, _ = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"F_SINGLE": Decimal("1.00")},
    )
    assert len(summary.top_stocks) == 2
    assert summary.total_reconciled_weight == Decimal("1.0000")


def test_boundary_zero_valuation_eur():
    """Zero EUR valuation portfolio produces Decimal('0.00') valuations without ZeroDivisionError."""
    fund = build_test_fund("F_ZERO_EUR", "Zero EUR Fund", [
        ConstituentHolding(name="Apple", weight=Decimal("1.00")),
    ])
    summary, bd = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"F_ZERO_EUR": Decimal("1.00")},
        portfolio_total_eur=Decimal("0.00"),
    )
    assert summary.top_stocks[0].valuation_eur == Decimal("0.00")
    assert summary.is_fully_reconciled is True


def test_boundary_none_valuation_eur():
    """None EUR valuation produces None valuation_eur fields."""
    fund = build_test_fund("F_NONE_EUR", "None EUR Fund", [
        ConstituentHolding(name="Apple", weight=Decimal("1.00")),
    ])
    summary, bd = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"F_NONE_EUR": Decimal("1.00")},
        portfolio_total_eur=None,
    )
    assert summary.top_stocks[0].valuation_eur is None


def test_boundary_empty_fund_holdings():
    """Fund with 0 holdings (empty basket) is treated as 100% uncovered without crashing."""
    empty_fund = build_test_fund("F_EMPTY", "Empty Fund", [])
    summary, _ = calculate_consolidated_exposure(
        funds=[empty_fund],
        fund_weights={"F_EMPTY": Decimal("1.00")},
    )
    assert len(summary.top_stocks) == 0
    assert summary.uncovered_etf_weight == Decimal("1.00")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


def test_boundary_100_percent_cash_portfolio():
    """Portfolio with 0 ETF holdings and 100% cash."""
    fund = build_test_fund("F_CASH_ONLY", "Fund", [])
    summary, _ = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"F_CASH_ONLY": Decimal("0.00")},
        portfolio_cash_weight=Decimal("1.00"),
    )
    assert summary.cash_weight == Decimal("1.00")
    assert summary.top25_weight == Decimal("0.00")
    assert summary.uncovered_etf_weight == Decimal("0.00")
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


# =============================================================================
# 7. Empirical Vulnerability & Defect Assertions (Worker IP-4 Bugs)
# =============================================================================

def test_vulnerability_reproduce_positive_derivative_violates_accounting_identity():
    """BUG-1 EMPIRICAL REPRODUCTION:
    When a fund contains a positive derivative holding, calculate_consolidated_exposure
    treats the derivative as an individual stock because line 406 only filters CASH.
    Simultaneously, uncovered_ratio = 1 - (equity + cash) includes the derivative as uncovered.
    Result: The derivative is double counted, causing total_reconciled_weight > 1.0 (e.g. 1.10).
    """
    fund_with_derivative = FundHoldings(
        isin="F_DERIV_BUG",
        fund_name="Fund With Futures",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("0.80"),
        cash_weight=Decimal("0.10"),
        derivative_weight=Decimal("0.10"),
        holdings=[
            ConstituentHolding(name="Apple Inc.", weight=Decimal("0.80"), asset_class=AssetClass.EQUITY.value),
            ConstituentHolding(name="USD Cash", weight=Decimal("0.10"), asset_class=AssetClass.CASH.value),
            ConstituentHolding(name="S&P 500 Future", weight=Decimal("0.10"), asset_class=AssetClass.DERIVATIVE.value),
        ],
    )

    summary, _ = calculate_consolidated_exposure(
        funds=[fund_with_derivative],
        fund_weights={"F_DERIV_BUG": Decimal("1.00")},
    )

    # Verify derivative is not double counted: total reconciles to 1.0000
    assert summary.total_reconciled_weight == Decimal("1.0000")
    assert summary.is_fully_reconciled is True


def test_invariant_derivative_must_reconcile_to_100_percent():
    """BUG-1 INVARIANT: Funds with derivatives MUST reconcile to exactly 1.0000 (100.0%)."""
    fund_with_derivative = FundHoldings(
        isin="F_DERIV_BUG",
        fund_name="Fund With Futures",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("0.80"),
        cash_weight=Decimal("0.10"),
        derivative_weight=Decimal("0.10"),
        holdings=[
            ConstituentHolding(name="Apple Inc.", weight=Decimal("0.80"), asset_class=AssetClass.EQUITY.value),
            ConstituentHolding(name="USD Cash", weight=Decimal("0.10"), asset_class=AssetClass.CASH.value),
            ConstituentHolding(name="S&P 500 Future", weight=Decimal("0.10"), asset_class=AssetClass.DERIVATIVE.value),
        ],
    )

    summary, _ = calculate_consolidated_exposure(
        funds=[fund_with_derivative],
        fund_weights={"F_DERIV_BUG": Decimal("1.00")},
    )
    assert summary.is_fully_reconciled is True, f"Failed: total is {summary.total_reconciled_weight}"
    assert summary.total_reconciled_weight == Decimal("1.0000")


def test_vulnerability_reproduce_live_run_cash_inflation(tmp_path):
    """BUG-2 EMPIRICAL REPRODUCTION:
    In run_portfolio_overlap_analysis, when latest_run has positions (e.g. 80%) and cash (e.g. 20%),
    line 737 normalizes ETF weights to 1.0 by dividing by sum_w, and then line 745 passes
    portfolio_cash_weight=0.20.
    Result: total_reconciled_weight is 1.20 (120%), violating the 100% accounting identity.
    """
    db_file = tmp_path / "bug2.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    # Load 1 fund with 100% equity into DB
    from masa.holdings.loader import HoldingsLoader
    loader = HoldingsLoader(db, base_dir=tmp_path)
    csv_file = tmp_path / "IE00B3YLTY66_sample.csv"
    csv_file.write_text("Ticker;Name;ISIN;Weight (%)\nAAPL;Apple Inc.;US0378331005;100,00\n")
    loader.ingest_file(csv_file, isin="IE00B3YLTY66")

    # Mock latest_run with 8,000 EUR in ETF and 2,000 EUR in cash (total: 10,000 EUR)
    mock_run = MagicMock()
    mock_pos = MagicMock()
    mock_pos.broker_value = Decimal("8000.00")
    mock_run.positions = {"IE00B3YLTY66": mock_pos}
    mock_run.cash = Decimal("2000.00")
    mock_run.total.return_value = Decimal("10000.00")

    with patch("masa.pipeline.latest_run", return_value=mock_run):
        _, summary, _ = run_portfolio_overlap_analysis(db, use_targets=False)
        assert summary.total_reconciled_weight == Decimal("1.0000")
        assert summary.is_fully_reconciled is True


def test_invariant_live_run_cash_must_reconcile_to_100_percent(tmp_path):
    """BUG-2 INVARIANT: run_portfolio_overlap_analysis MUST reconcile to 1.0000 with live cash."""
    db_file = tmp_path / "bug2_inv.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    from masa.holdings.loader import HoldingsLoader
    loader = HoldingsLoader(db, base_dir=tmp_path)
    csv_file = tmp_path / "IE00B3YLTY66_sample.csv"
    csv_file.write_text("Ticker;Name;ISIN;Weight (%)\nAAPL;Apple Inc.;US0378331005;100,00\n")
    loader.ingest_file(csv_file, isin="IE00B3YLTY66")

    mock_run = MagicMock()
    mock_pos = MagicMock()
    mock_pos.broker_value = Decimal("8000.00")
    mock_run.positions = {"IE00B3YLTY66": mock_pos}
    mock_run.cash = Decimal("2000.00")
    mock_run.total.return_value = Decimal("10000.00")

    with patch("masa.pipeline.latest_run", return_value=mock_run):
        _, summary, _ = run_portfolio_overlap_analysis(db, use_targets=False)
        assert summary.is_fully_reconciled is True
        assert summary.total_reconciled_weight == Decimal("1.0000")


def test_vulnerability_reproduce_unloaded_etf_weight_inflation(tmp_path):
    """BUG-3 EMPIRICAL REPRODUCTION:
    When a portfolio contains 2 ETFs (50% each), and only 1 ETF has holdings loaded in DB,
    run_portfolio_overlap_analysis scales the loaded ETF up to 100%, instead of preserving
    the unloaded ETF as UNCOVERED_ETF_HOLDINGS (50%).
    """
    db_file = tmp_path / "bug3.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    from masa.holdings.loader import HoldingsLoader
    loader = HoldingsLoader(db, base_dir=tmp_path)
    csv_file = tmp_path / "IE00B3YLTY66_sample.csv"
    csv_file.write_text("Ticker;Name;ISIN;Weight (%)\nAAPL;Apple Inc.;US0378331005;100,00\n")
    loader.ingest_file(csv_file, isin="IE00B3YLTY66")

    # Portfolio: 50% IE00B3YLTY66 (loaded) and 50% IE00BKM4GZ66 (unloaded)
    mock_run = MagicMock()
    pos1 = MagicMock(); pos1.broker_value = Decimal("5000.00")
    pos2 = MagicMock(); pos2.broker_value = Decimal("5000.00")
    mock_run.positions = {"IE00B3YLTY66": pos1, "IE00BKM4GZ66": pos2}
    mock_run.cash = Decimal("0.00")
    mock_run.total.return_value = Decimal("10000.00")

    with patch("masa.pipeline.latest_run", return_value=mock_run):
        _, summary, _ = run_portfolio_overlap_analysis(db, use_targets=False)
        assert summary.top_stocks[0].portfolio_weight == Decimal("0.50")
        assert summary.uncovered_etf_weight == Decimal("0.50")


def test_invariant_unloaded_etf_must_be_preserved_as_uncovered(tmp_path):
    """BUG-3 INVARIANT: Unloaded portfolio ETFs must be counted as UNCOVERED_ETF_HOLDINGS without inflating loaded ETFs."""
    db_file = tmp_path / "bug3_inv.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    from masa.holdings.loader import HoldingsLoader
    loader = HoldingsLoader(db, base_dir=tmp_path)
    csv_file = tmp_path / "IE00B3YLTY66_sample.csv"
    csv_file.write_text("Ticker;Name;ISIN;Weight (%)\nAAPL;Apple Inc.;US0378331005;100,00\n")
    loader.ingest_file(csv_file, isin="IE00B3YLTY66")

    mock_run = MagicMock()
    pos1 = MagicMock(); pos1.broker_value = Decimal("5000.00")
    pos2 = MagicMock(); pos2.broker_value = Decimal("5000.00")
    mock_run.positions = {"IE00B3YLTY66": pos1, "IE00BKM4GZ66": pos2}
    mock_run.cash = Decimal("0.00")
    mock_run.total.return_value = Decimal("10000.00")

    with patch("masa.pipeline.latest_run", return_value=mock_run):
        _, summary, _ = run_portfolio_overlap_analysis(db, use_targets=False)
        # Invariant: AAPL should be 50%, unloaded ETF should be 50%
        assert summary.top_stocks[0].portfolio_weight == Decimal("0.50")
        assert summary.uncovered_etf_weight == Decimal("0.50")


def test_vulnerability_reproduce_cross_tier_matching_blindspot():
    """BUG-4 EMPIRICAL REPRODUCTION:
    calculate_pairwise_overlap and calculate_consolidated_exposure use static keys from
    get_constituent_match_key. If Fund A has Apple with ISIN (US0378331005) and Fund B
    has Apple with NO ISIN and Ticker AAPL, match_constituents says they match ('TICKER:AAPL'),
    but calculate_pairwise_overlap finds 0 overlap and calculate_consolidated_exposure creates
    two duplicate Apple entries.
    """
    h_a = ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.10"))
    h_b = ConstituentHolding(holding_isin=None, ticker="AAPL", name="Apple Inc.", weight=Decimal("0.10"))

    # Direct match_constituents works:
    assert match_constituents(h_a, h_b) == "TICKER:AAPL"

    f_a = build_test_fund("F_A", "Fund A", [h_a])
    f_b = build_test_fund("F_B", "Fund B", [h_b])

    # Cross-tier matching: calculate_pairwise_overlap intersects on resolved key
    res = calculate_pairwise_overlap(f_a, f_b)
    assert res.overlap_score == Decimal("0.10")

    # And calculate_consolidated_exposure unifies Apple into a single consolidated entry
    summary, _ = calculate_consolidated_exposure(
        funds=[f_a, f_b],
        fund_weights={"F_A": Decimal("0.50"), "F_B": Decimal("0.50")},
    )
    assert len(summary.top_stocks) == 1
    assert summary.top_stocks[0].portfolio_weight == Decimal("0.10")


def test_vulnerability_clean_decimal_multiple_thousands_commas():
    """BUG-5 EMPIRICAL REPRODUCTION:
    clean_decimal fails on strings with multiple commas (e.g. '1,234,567' shares),
    converting to '1.234.567' which is invalid Decimal and returning None.
    """
    # Standard European single comma works:
    assert clean_decimal("3,84") == Decimal("3.84")
    # Standard US comma + dot works:
    assert clean_decimal("1,234.56") == Decimal("1234.56")
    # Multiple commas without a dot: treated as thousands separators
    assert clean_decimal("1,234,567") == Decimal("1234567")
