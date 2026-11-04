"""Known-answer tests for the calc modules (hand-checked expected values)."""

from decimal import Decimal

import numpy as np
import pytest

from masa.calc import lookthrough as L
from masa.calc import performance as P
from masa.calc import rebalancing as R
from masa.calc import valuation as V


# ----------------------------------------------------------------- performance
def _perf(iv, tv, flows=(), subs=(), txs=(), start="2025-01-01T00:00:00Z",
          end="2026-01-01T00:00:00Z", days=365, iv_pos=0, tv_pos=0):
    return {"evaluation_period": {"start_date": start, "end_date": end, "calendar_days": days},
            "initial_valuation": {"total_equity": iv, "cash_balance": iv - iv_pos, "positions_value": iv_pos},
            "terminal_valuation": {"total_equity": tv, "cash_balance": tv - tv_pos, "positions_value": tv_pos},
            "subperiod_valuations": list(subs), "cash_flows": list(flows),
            "transactions": list(txs), "accounting_options": {}}


def _flow(fid, ts, amount, typ):
    return {"flow_id": fid, "timestamp": ts, "amount": amount, "currency": "EUR",
            "raw_description": fid, "classified_type": typ}


def test_no_flow_year_returns_match_excel_xirr():
    s = P.calculate_performance(_perf(10000, 11000)).returns_summary
    assert s.modified_dietz_pct == Decimal("10")
    assert s.true_twr_cumulative_pct == Decimal("10")
    assert abs(float(s.xirr_annualized_pct) - 10.0) < 1e-6  # actual/365, as Excel XIRR


def test_mid_period_deposit_twr_and_dietz():
    f = [_flow("d", "2025-07-02T12:00:00Z", 5000, "EXTERNAL_DEPOSIT")]
    sub = [{"timestamp": "2025-07-02T12:00:00Z", "equity_before_flow": 10500}]
    s = P.calculate_performance(_perf(10000, 16500, f, sub)).returns_summary
    assert abs(float(s.true_twr_cumulative_pct) - (1.05 * 16500 / 15500 - 1) * 100) < 1e-9
    assert abs(float(s.modified_dietz_pct) - 12.0) < 1e-9


def test_broker_fee_reduces_return():
    f = [_flow("fee", "2025-07-02T12:00:00Z", -100, "BROKER_FEE")]
    sub = [{"timestamp": "2025-07-02T12:00:00Z", "equity_before_flow": 10000}]
    r = P.calculate_performance(_perf(10000, 9900, f, sub))
    assert abs(float(r.returns_summary.true_twr_cumulative_pct) + 1.0) < 1e-9
    assert abs(float(r.returns_summary.modified_dietz_pct) + 1.0) < 1e-9
    assert r.reconciliation_diagnostics.is_balanced is True


def test_fifo_vs_wac_realized_and_unrealized():
    isin = "IE00B3YLTY66"
    tx = [
        {"tx_id": "b1", "timestamp": "2025-02-01T10:00:00Z", "isin": isin, "side": "BUY", "shares": 10,
         "execution_price": 100, "fees": 1, "taxes": 0, "total_cash_impact": -1001},
        {"tx_id": "b2", "timestamp": "2025-03-01T10:00:00Z", "isin": isin, "side": "BUY", "shares": 10,
         "execution_price": 120, "fees": 1, "taxes": 0, "total_cash_impact": -1201},
        {"tx_id": "s1", "timestamp": "2025-04-01T10:00:00Z", "isin": isin, "side": "SELL", "shares": 10,
         "execution_price": 130, "fees": 1, "taxes": 0, "total_cash_impact": 1299},
    ]
    cash_end = 10000 - 1001 - 1201 + 1299
    audit = P.audit_cost_basis(_perf(10000, cash_end + 1400, txs=tx, tv_pos=1400))[0]
    assert audit.fifo_realized_pnl == Decimal("298")
    assert audit.wac_realized_pnl == Decimal("198")
    assert audit.fifo_remaining_basis == Decimal("1201")
    assert audit.wac_remaining_basis == Decimal("1101")
    assert audit.fifo_unrealized_pnl == Decimal("199")


# ----------------------------------------------------------------- lookthrough
def test_lookthrough_consolidation_and_overlap():
    def h(isin, name, w):
        return {"isin": isin, "ticker": name[:4], "company_name": name, "weight": w}
    pay = {"portfolio_snapshot": {
        "snapshot_id": "s", "retrieved_at": "2026-10-30T16:00:00Z", "base_currency": "EUR",
        "cash_balance_eur": 0, "total_equity_value_eur": 1000, "total_portfolio_value_eur": 1000,
        "positions": [
            {"instrument_id": "A", "isin": "IE00B3YLTY66", "ticker": "A", "instrument_type": "ETF",
             "name": "A", "valuation_eur": 600, "weight_in_portfolio": 0.6},
            {"instrument_id": "B", "isin": "IE00BKM4GZ66", "ticker": "B", "instrument_type": "ETF",
             "name": "B", "valuation_eur": 400, "weight_in_portfolio": 0.4}]},
        "etf_holdings_catalog": {
            "A": {"as_of_date": "2026-10-29", "replication_method": "PHYSICAL_FULL",
                  "reported_coverage_ratio": 1, "is_full_basket": True,
                  "holdings": [h("US0378331005", "Apple", 0.5), h("US5949181045", "Microsoft", 0.5)]},
            "B": {"as_of_date": "2026-10-29", "replication_method": "PHYSICAL_FULL",
                  "reported_coverage_ratio": 1, "is_full_basket": True,
                  "holdings": [h("US0378331005", "Apple", 0.2), h("US02079K3059", "Alphabet", 0.8)]}},
        "calculation_settings": {"denominator_mode": "TOTAL_PORTFOLIO_INCLUDING_CASH",
                                 "minimum_reporting_weight_bps": 0, "top_n_companies_limit": 50}}
    out = L.compute_lookthrough(pay)
    weights = {c.company_name: c.portfolio_weight_pct for c in out.consolidated_companies}
    assert weights["Apple"] == pytest.approx(38.0)
    assert weights["Microsoft"] == pytest.approx(30.0)
    assert weights["Alphabet Inc."] == pytest.approx(32.0)
    assert out.pairwise_fund_overlap[0].overlap_score == pytest.approx(0.2)


# ----------------------------------------------------------------- rebalancing
_PORT = [("IE00B3YLTY66", 158, 11.608), ("IE00BKM4GZ66", 22, 44.772),
         ("IE00BP3QZ825", 10, 96.98), ("IE00BP3QZB59", 8, 70.055)]


def _reb(inflow, mode="INFLOW_ONLY", targets=None, cash=0):
    total = sum(s * m for _, s, m in _PORT)
    pos = [{"isin": i, "ticker": i[-4:], "name": i, "shares": s, "quote_mid": m,
            "bid": round(m * 0.999, 4), "ask": round(m * 1.001, 4), "valuation": s * m,
            "current_weight": round(s * m / (total + cash), 6)} for i, s, m in _PORT]
    if targets is None:
        tw = {i: round(s * m / total, 4) for i, s, m in _PORT[1:]}
        tw[_PORT[0][0]] = round(1 - sum(tw.values()), 4)
    else:
        tw = targets
    return R.calculate_rebalancing({
        "as_of": "2026-10-30T15:00:00Z", "portfolio_id": "p", "base_currency": "EUR",
        "available_cash": cash, "new_cash_injection": inflow, "positions": pos, "target_weights": tw,
        "rebalance_policy": {"rebalance_mode": mode, "absolute_tolerance_band": 0.02,
                             "relative_tolerance_band": 0.10, "min_trade_ticket_eur": 25,
                             "target_cash_weight": 0.0}})


@pytest.mark.parametrize("mode", ["INFLOW_ONLY", "FULL_REBALANCE"])
def test_monthly_sparplan_cash_is_invested_even_inside_bands(mode):
    out = _reb(150, mode)
    bought = out.rebalance_summary.total_buy_volume
    assert out.ordered_execution_plan, "150 EUR inflow must produce at least one buy"
    assert bought > 100
    assert all(o.action == R.Action.BUY for o in out.ordered_execution_plan)
    # whatever is left cannot buy one more whole share of any underweight fund
    assert 150 - bought < min(p[2] for p in _PORT[1:])


def test_500_inflow_almost_fully_invested():
    out = _reb(500)
    assert 500 - out.rebalance_summary.total_buy_volume < 15
    assert {o.isin for o in out.ordered_execution_plan} == {p[0] for p in _PORT}


def test_inflow_only_never_sells_even_when_far_off_target():
    targets = {"IE00B3YLTY66": 0.10, "IE00BKM4GZ66": 0.30, "IE00BP3QZ825": 0.30, "IE00BP3QZB59": 0.30}
    out = _reb(300, "INFLOW_ONLY", targets)
    assert all(o.action == R.Action.BUY for o in out.ordered_execution_plan)
    assert "IE00B3YLTY66" not in {o.isin for o in out.ordered_execution_plan}


def test_full_rebalance_sells_before_buys_when_outside_band():
    targets = {"IE00B3YLTY66": 0.10, "IE00BKM4GZ66": 0.30, "IE00BP3QZ825": 0.30, "IE00BP3QZB59": 0.30}
    plan = _reb(0, "FULL_REBALANCE", targets).ordered_execution_plan
    actions = [o.action for o in plan]
    assert R.Action.SELL in actions and R.Action.BUY in actions
    assert actions.index(R.Action.BUY) > max(i for i, a in enumerate(actions) if a == R.Action.SELL)


# ----------------------------------------------------------------- factor model
def test_factor_regression_recovers_known_betas():
    rng = np.random.default_rng(7)
    n = 120
    f = {k: rng.normal(0, 0.04, n) for k in ("mkt_rf", "smb", "hml", "rmw", "cma")}
    y = 0.001 + 1.2 * f["mkt_rf"] + 0.3 * f["smb"] - 0.2 * f["hml"] + rng.normal(0, 0.002, n)
    data = V.ReturnSeriesSummary(observation_period="synthetic", frequency="MONTHLY",
                                 asset_excess_returns=list(map(float, y)),
                                 factor_benchmarks={k: list(map(float, v)) for k, v in f.items()})
    res = V.analyze_factors(data)
    assert res.betas.market_beta.coefficient == pytest.approx(1.2, abs=0.02)
    assert res.betas.size_smb.coefficient == pytest.approx(0.3, abs=0.02)
    assert res.betas.value_hml.coefficient == pytest.approx(-0.2, abs=0.02)
