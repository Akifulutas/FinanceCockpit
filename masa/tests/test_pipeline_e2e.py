"""End-to-end: fake `sc` (sc 1.0.0 output shapes) -> seals -> analysis -> report.

The fake broker holds the 4 ETFs bought from a single opening deposit, so the
whole account history is known and realized returns must reconcile exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from masa import analytics
from masa.advisor import assess
from masa.calendar.adapter import CalendarAdapter
from masa.config import Config, Policy, load_config
from masa.ingestion.sc_reader import ScalableReader
from masa.integrations import tradingagents as ta
from masa.pipeline import Pipeline, integrity_report, latest_run, latest_series, latest_transactions
from masa.report import build, critic_check
from masa.storage import DatabaseManager

FIX = Path(__file__).parent / "fixtures"
HELD = {"IE00B3YLTY66": 200, "IE00BKM4GZ66": 50, "IE00BP3QZ825": 25, "IE00BP3QZB59": 20}


def _env(cmd, data):
    return json.dumps({"ok": True, "command": cmd, "data": data})


class FakeSC:
    """Answers argv like sc 1.0.0; prices follow per-ISIN synthetic paths."""

    def __init__(self, shift: float = 0.0, fail_isin: str | None = None):
        base = json.loads((FIX / "sample_chart_acwi_1y.json").read_text())["data"]
        self.times = [p["timestamp_utc"] for p in base["data_points"]]
        acwi = np.array([p["mid_price"] for p in base["data_points"]])
        rng = np.random.default_rng(42)
        self.paths = {}
        for k, isin in enumerate(list(HELD) + ["IE00B4L5Y983", "US0378331005"]):
            noise = np.cumprod(1 + rng.normal(0.0002 * k, 0.006, len(acwi)))
            path = acwi / acwi[-1] * noise / noise[-1]
            self.paths[isin] = path * {"IE00B3YLTY66": 11.6, "IE00BKM4GZ66": 44.7, "IE00BP3QZ825": 97.0,
                                       "IE00BP3QZB59": 70.0, "IE00B4L5Y983": 110.0, "US0378331005": 230.0}[isin]
        self.shift = shift
        self.fail_isin = fail_isin
        self.calls = []
        buy_i = 5  # buys on the 6th chart point
        t0 = datetime.fromisoformat(self.times[buy_i].replace("Z", "+00:00")) + timedelta(hours=2)
        self.buys = []
        total = 0.0
        for j, (isin, q) in enumerate(HELD.items()):
            px = round(float(self.paths[isin][buy_i]) * 1.001, 4)
            amt = round(-q * px, 3)
            total += amt
            self.buys.append({"amount": amt, "currency": "EUR", "description": isin, "id": f"B{j}",
                              "is_cancellation": False, "isin": isin, "last_event_datetime": (t0 + timedelta(minutes=j)).isoformat().replace("+00:00", "Z"),
                              "limit_price": None, "quantity": q, "security_transaction_type": "SINGLE", "side": "BUY",
                              "status": "SETTLED", "type": "SECURITY_TRANSACTION"})
        self.fee = {"amount": -4.99, "cash_transaction_type": "FEE", "currency": "EUR", "description": "Prime",
                    "id": "F1", "is_cancellation": False, "last_event_datetime": (t0 + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                    "status": "SETTLED", "type": "CASH_TRANSACTION"}
        self.cash_end = 25.0
        self.deposit = {"amount": round(-total + 4.99 + self.cash_end, 3), "cash_transaction_type": "DEPOSIT",
                        "currency": "EUR", "description": "Einzahlung", "id": "D1", "is_cancellation": False,
                        "last_event_datetime": (t0 - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                        "status": "SETTLED", "type": "CASH_TRANSACTION"}

    def mid(self, isin):
        return round(float(self.paths[isin][-1]) * (1 + self.shift), 4)

    def __call__(self, cmd, timeout):
        a = cmd[1:]
        self.calls.append(a)
        res = {"account_id": "ACC_TEST_01", "portfolio_id": "PF_TEST_01"}
        if a[0] == "whoami":
            return 0, _env("whoami", {"result": {"personOverview": {"id": "X", "personalDetails": {
                "firstName": "Test", "lastName": "Kullanici"}}}}), ""
        if a[:2] == ["broker", "holdings"]:
            items = [{"blocked_quantity": 0, "fifo_price": abs(b["amount"]) / b["quantity"], "isin": b["isin"],
                      "name": f"Fund {b['isin']}", "pending_quantity": 0, "quantity": b["quantity"],
                      "quote_currency": "EUR", "quote_is_outdated": False, "quote_mid_price": self.mid(b["isin"]),
                      "quote_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                      "security_type": "ETF", "valuation": round(b["quantity"] * self.mid(b["isin"]), 2),
                      "valuation_currency": "EUR"} for b in self.buys]
            return 0, _env("broker.holdings", {**res, "result": {**res, "count": len(items), "items": items}}), ""
        if a[:2] == ["broker", "cash-breakdown"]:
            return 0, _env("broker.cash-breakdown", {**res, "result": {**res, "cash_balance": self.cash_end,
                           "buying_power": self.cash_end, "buying_power_without_credit": self.cash_end,
                           "available_credit_line": 0, "derivatives_buying_power": 0,
                           "pending_buy_orders_amount": 0, "possible_taxes": 0}}), ""
        if a[:2] == ["broker", "quote"]:
            isin = a[a.index("--isin") + 1]
            if isin == self.fail_isin or isin not in self.paths:
                return 10, json.dumps({"ok": False, "error": {"code": "not_found", "message": "unknown"}}), ""
            m = self.mid(isin)
            return 0, _env("broker.quote", {**res, "result": {
                "isin": isin, "name": f"Fund {isin}", "quote_bid_price": round(m * 0.999, 4),
                "quote_ask_price": round(m * 1.001, 4), "quote_mid_price": m, "quote_currency": "EUR",
                "quote_is_outdated": False, "quote_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "quote_performances": [{"timeframe": "SIX_MONTHS", "performance": float(self.paths[isin][-1] / self.paths[isin][-64] - 1)},
                                       {"timeframe": "ONE_YEAR", "performance": float(self.paths[isin][-1] / self.paths[isin][0] - 1)}],
                "security_type": "ETF"}}), ""
        if a[:2] == ["broker", "chart"]:
            isin = a[a.index("--isin") + 1]
            pts = [{"mid_price": round(float(v), 4), "timestamp_utc": t} for v, t in zip(self.paths[isin], self.times)]
            return 0, _env("broker.chart", {"isin": isin, "currency": "EUR", "source": "CONSOLIDATED",
                                            "timeframe": a[a.index("--timeframe") + 1], "data_points": pts,
                                            "point_count": len(pts)}), ""
        if a[:2] == ["broker", "transactions"]:
            newest_first = sorted([self.deposit, self.fee] + self.buys, key=lambda x: x["last_event_datetime"], reverse=True)
            page = newest_first[3:] if "--cursor" in a else newest_first[:3]
            cursor = None if "--cursor" in a else "1788164469710|nextPageToken"
            return 0, _env("broker.transactions", {**res, "result": {**res, "count": len(page), "cursor": cursor,
                                                                    "items": page, "total": len(page)}}), ""
        return 1, "", "unsupported"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MASA_SC_BIN", "/opt/homebrew/bin/sc")
    fake = FakeSC()
    db = DatabaseManager(tmp_path / "e2e.db")
    pipe = Pipeline(db=db, reader=ScalableReader(runner=fake))
    return pipe, fake


def _cfg():
    cfg = load_config()
    return cfg


def test_full_pipeline_seals_reconciles_and_reports(env):
    pipe, fake = env
    res = pipe.collect_snapshot()
    assert res.ok and res.quality == "VALID"
    assert all(s.created for s in res.snapshots.values())
    hist = pipe.collect_history(list(HELD))
    assert not hist["errors"]
    assert hist["transactions"][1] == 2 + len(HELD)          # both pages followed
    assert sum(1 for c in fake.calls if c[:2] == ["broker", "transactions"]) == 2

    run = latest_run(pipe.db)
    assert run.owner == "Test Kullanici"
    assert {p.isin for p in run.positions} == set(HELD)
    assert run.cash == Decimal("25.0")

    cfg = _cfg()
    series = {i: latest_series(pipe.db, i, "1y") for i in HELD}
    assert all(len(s) == len(fake.times) for s in series.values())
    metrics = {i: analytics.risk_metrics(s) for i, s in series.items()}
    assert all(m is not None and m.points == len(fake.times) for m in metrics.values())
    corr = analytics.correlation_matrix(series)
    assert corr.shape == (4, 4) and float(corr.values.min()) < 0.999

    realized = analytics.realized_returns(
        latest_transactions(pipe.db), {p.isin: p.quantity for p in run.positions},
        {p.isin: p.value for p in run.positions}, {p.isin: p.fifo_price for p in run.positions},
        run.cash, datetime.fromisoformat(run.completed_at), series)
    assert realized.available, realized.reason
    assert abs(realized.cash_gap) <= Decimal("0.01")
    assert realized.fees == Decimal("-4.99")
    expected_gain = run.total - realized.deposits
    assert abs(realized.gain - expected_gain) < Decimal("0.05")
    for isin, (ours, broker) in realized.fifo_check.items():
        assert abs(ours - broker) < Decimal("0.0001")         # our FIFO == broker FIFO

    assessments = assess(run, cfg, metrics)
    assert {a.label for a in assessments} <= {"TUT", "EKLE", "AZALT", "GÖZDEN GEÇİR", "VERİ YETERSİZ"}
    crit = critic_check(run, corr)
    assert crit.verdict.value == "APPROVE"
    integ = integrity_report(pipe.db)
    assert integ["ok"], integ
    md = build(run, cfg, integ, CalendarAdapter().is_market_open(datetime.now(timezone.utc)), metrics,
               None, corr, assessments, realized, None, None, {}, crit)
    assert "GEÇERLİ" in md and "Zaman ağırlıklı getiri" in md and ("S" + "aime") not in md
    for p in run.positions:
        assert f"{p.mid:.4f}" in md                            # every reported price is the sealed one


def test_second_run_with_new_prices_creates_new_seals(env):
    pipe, fake = env
    r1 = pipe.collect_snapshot()
    fake.shift = 0.01
    r2 = pipe.collect_snapshot()
    assert r1.run_id != r2.run_id
    assert r2.snapshots["quotes"].created and r2.snapshots["quotes"].snapshot_id != r1.snapshots["quotes"].snapshot_id
    assert not r2.snapshots["cash"].created                    # unchanged cash output re-uses the seal
    run = latest_run(pipe.db)
    assert run.run_id == r2.run_id
    assert next(p for p in run.positions if p.isin == "IE00B3YLTY66").mid == Decimal(str(fake.mid("IE00B3YLTY66")))
    assert integrity_report(pipe.db)["ok"]


def test_quote_failure_is_partial_not_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("MASA_SC_BIN", "/opt/homebrew/bin/sc")
    pipe = Pipeline(db=DatabaseManager(tmp_path / "p.db"),
                    reader=ScalableReader(runner=FakeSC(fail_isin="IE00BP3QZB59")))
    res = pipe.collect_snapshot()
    assert not res.ok and res.quality == "PARTIAL"
    assert any("IE00BP3QZB59" in f for f in res.quote_failures)
    run = latest_run(pipe.db)
    assert next(p for p in run.positions if p.isin == "IE00BP3QZB59").quality == "MISSING"
    labels = {a.isin: a.label for a in assess(run, _cfg(), {})}
    assert labels["IE00BP3QZB59"] == "VERİ YETERSİZ"


def test_scanner_ranks_and_records_unknown_isins(env):
    from masa.scanner import scan
    pipe, fake = env
    pipe.collect_snapshot()
    pipe.collect_history(list(HELD), timeframes=("1y",))
    cfg = _cfg()
    cfg.pool = {"etf": {"IE00B4L5Y983": {"ad": "World"}, "IE00BK5BQT80": {"ad": "unknown at broker"}},
                "hisse": {"US0378331005": {"ad": "Apple"}}}
    run = latest_run(pipe.db)
    port = analytics.static_portfolio_series({i: latest_series(pipe.db, i, "1y") for i in HELD},
                                             {p.isin: p.quantity for p in run.positions})
    out = scan(pipe, cfg, port, set(HELD))
    by = {c.isin: c for c in out["candidates"]}
    assert by["IE00BK5BQT80"].error and by["IE00BK5BQT80"].label == "ELENDİ"
    assert by["IE00B4L5Y983"].score is not None and by["IE00B4L5Y983"].corr_to_portfolio is not None
    assert by["US0378331005"].label in ("ARAŞTIRMAYA DEĞER", "İZLE")
    assert integrity_report(pipe.db)["ok"]


def test_tradingagents_bridge_contract(tmp_path, monkeypatch):
    """Runs the real bridge script against a stub `tradingagents` package."""
    ta_dir = tmp_path / "TradingAgents"
    pkg = ta_dir / "stub" / "tradingagents"
    (pkg / "graph").mkdir(parents=True)
    (ta_dir / ".venv" / "bin").mkdir(parents=True)
    (ta_dir / ".env").write_text("OPENAI_API_KEY=dummy\n")
    py = ta_dir / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n")
    py.chmod(0o755)
    (pkg / "__init__.py").write_text("__version__='0.7.1-stub'\n")
    (pkg / "default_config.py").write_text("DEFAULT_CONFIG={'llm_provider':'stub','deep_think_llm':'d','quick_think_llm':'q'}\n")
    (pkg / "portfolio.py").write_text(
        "from pydantic import BaseModel\n"
        "class Position(BaseModel):\n ticker:str\n quantity:float\n average_price:float|None=None\n"
        "class PortfolioContext(BaseModel):\n cash:float|None=None\n currency:str|None=None\n positions:list[Position]=[]\n")
    (pkg / "graph" / "__init__.py").write_text("")
    (pkg / "graph" / "trading_graph.py").write_text(
        "class TradingAgentsGraph:\n"
        " def __init__(self, selected_analysts=(), debug=False, config=None):\n  self.a=selected_analysts; print('noisy log')\n"
        " def propagate(self, t, d, asset_type='stock', portfolio=None):\n"
        "  assert portfolio.positions[0].ticker=='SPYI.DE'\n"
        "  return {'final_trade_decision': f'HOLD {t} {d} {list(self.a)}', 'market_report':'m'}, 'Hold'\n")
    monkeypatch.setenv("PYTHONPATH", str(ta_dir / "stub"))
    st = ta.status(ta_dir)
    assert st.available, st.detail
    book = {"cash": 25.0, "currency": "EUR", "positions": [{"ticker": "SPYI.DE", "quantity": 200, "average_price": 11.59}]}
    out = ta.run("SPYI.DE", asset_kind="ETF", portfolio=book, trade_date="2026-10-30", ta_dir=ta_dir, timeout=60)
    assert out["ok"], out
    assert out["rating"] == "Hold"
    assert "['market', 'news']" in out["reports"]["final_trade_decision"]   # ETF -> no fundamentals analyst
    assert "noisy log" in out["log_tail"]
    missing = ta.status(tmp_path / "nope")
    assert not missing.available


def test_model_router_balances_and_falls_back(tmp_path, monkeypatch):
    """Quick tier alternates google/chatgpt per symbol; a google 429 is retried on chatgpt."""
    ta_dir = tmp_path / "TA"
    pkg = ta_dir / "stub" / "tradingagents"
    (pkg / "graph").mkdir(parents=True)
    (ta_dir / ".venv" / "bin").mkdir(parents=True)
    (ta_dir / ".env").write_text("TRADINGAGENTS_QUICK_THINK_PROVIDER=google\n")
    py = ta_dir / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n"); py.chmod(0o755)
    (pkg / "__init__.py").write_text("")
    (pkg / "default_config.py").write_text(
        "import os\nDEFAULT_CONFIG={'quick_think_provider':os.getenv('TRADINGAGENTS_QUICK_THINK_PROVIDER'),"
        "'deep_think_llm':os.getenv('TRADINGAGENTS_DEEP_THINK_LLM')}\n")
    (pkg / "portfolio.py").write_text("class PortfolioContext:\n @staticmethod\n def model_validate(d): return d\n")
    (pkg / "graph" / "__init__.py").write_text("")
    (pkg / "graph" / "trading_graph.py").write_text(
        "import os\nclass TradingAgentsGraph:\n"
        " def __init__(self, selected_analysts=(), debug=False, config=None): self.c=config\n"
        " def propagate(self, t, d, asset_type='stock', portfolio=None):\n"
        "  if self.c['quick_think_provider']=='google' and t=='LIMIT': raise RuntimeError('429 RESOURCE_EXHAUSTED quota')\n"
        "  return {'final_trade_decision': self.c['quick_think_provider']}, 'Hold'\n")
    monkeypatch.setenv("PYTHONPATH", str(ta_dir / "stub"))
    router = ta.ModelRouter({"hizli_katman": [{"saglayici": "google", "model": "g", "agirlik": 1},
                                              {"saglayici": "chatgpt", "model": "c", "agirlik": 1}],
                             "derin_katman": {"saglayici": "chatgpt", "model": "c"}})
    used = [ta.run_routed(t, router, asset_kind="ETF", portfolio=None, trade_date="2026-10-30", ta_dir=ta_dir, timeout=60)
            ["reports"]["final_trade_decision"] for t in ("A", "B", "C", "D")]
    assert used == ["google", "chatgpt", "google", "chatgpt"]
    assert router.usage == {"google": 2, "chatgpt": 2}
    res = ta.run_routed("LIMIT", router, asset_kind="ETF", portfolio=None, trade_date="2026-10-30", ta_dir=ta_dir, timeout=60)
    assert res["ok"] and res["reports"]["final_trade_decision"] == "chatgpt" and "yedek" in res["route"]
    weighted = ta.ModelRouter({"hizli_katman": [{"saglayici": "google", "model": "g", "agirlik": 2},
                                                {"saglayici": "chatgpt", "model": "c", "agirlik": 1}],
                               "derin_katman": {"saglayici": "chatgpt", "model": "c"}})
    picks = [weighted.next().quick_provider for _ in range(6)]
    assert picks.count("google") == 4 and picks.count("chatgpt") == 2
