#!/usr/bin/env python3
"""Seed a cryptographically sealed demo database for FinanceCockpit.

Allows new open-source users to launch and explore all 6 sections of the
macOS FinanceCockpit application with realistic synthetic ETF portfolio data,
1-year price history, reconciled FIFO ledger, investment theses, and AI model
forecasts — without requiring a live Scalable Capital broker session.

Usage:
    ./masa/.venv/bin/python scripts/seed_demo_db.py [--db-path PATH] [--force]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "masa" / "src"))

from masa.calc.reconciliation import reconcile_ledger_with_broker
from masa.identity.registry import IdentityRegistry
from masa.ingestion.sc_reader import ScalableReader
from masa.pipeline import Pipeline, integrity_report
from masa.storage.db import DatabaseManager, default_db_path
from masa.thesis.manager import ThesisManager
from masa.thesis.models import ThesisCategory, ThesisHorizon, ThesisRecord

DEMO_HOLDINGS = {
    "IE00B3YLTY66": ("SPDR MSCI ACWI IMI UCITS ETF (Acc)", 200, 11.60),
    "IE00BKM4GZ66": ("iShares Core MSCI EM IMI UCITS ETF (Acc)", 50, 45.20),
    "IE00BP3QZ825": ("iShares Edge MSCI World Momentum Factor UCITS ETF (Acc)", 25, 97.00),
    "IE00BP3QZB59": ("iShares Edge MSCI World Value Factor UCITS ETF (Acc)", 20, 70.00),
}


def _envelope(cmd: str, data: dict) -> str:
    return json.dumps({"ok": True, "command": cmd, "data": data})


class SyntheticDemoBroker:
    """Deterministic read-only broker simulator producing valid schema v3 seals."""

    def __init__(self) -> None:
        fixture_path = REPO_ROOT / "masa" / "tests" / "fixtures" / "sample_chart_acwi_1y.json"
        base = json.loads(fixture_path.read_text(encoding="utf-8"))["data"]
        self.times = [p["timestamp_utc"] for p in base["data_points"]]
        acwi = np.array([p["mid_price"] for p in base["data_points"]])
        rng = np.random.default_rng(2026)

        self.paths: dict[str, np.ndarray] = {}
        extra_isins = {
            "IE00B4L5Y983": ("iShares Core MSCI World UCITS ETF", 0, 110.0),
            "US0378331005": ("Apple Inc.", 0, 230.0),
        }
        all_assets = {**DEMO_HOLDINGS, **extra_isins}
        for k, (isin, (_name, _qty, target_px)) in enumerate(all_assets.items()):
            noise = np.cumprod(1 + rng.normal(0.0002 * k, 0.006, len(acwi)))
            path = acwi / acwi[-1] * noise / noise[-1]
            self.paths[isin] = path * target_px

        buy_idx = 5
        t0 = datetime.fromisoformat(self.times[buy_idx].replace("Z", "+00:00")) + timedelta(hours=2)
        self.buys = []
        total_spent = 0.0
        for j, (isin, (name, qty, _)) in enumerate(DEMO_HOLDINGS.items()):
            px = round(float(self.paths[isin][buy_idx]) * 1.001, 4)
            amt = round(-qty * px, 3)
            total_spent += amt
            self.buys.append({
                "amount": amt,
                "currency": "EUR",
                "description": name,
                "id": f"DEMO_BUY_{j + 1}",
                "is_cancellation": False,
                "isin": isin,
                "last_event_datetime": (t0 + timedelta(minutes=j)).isoformat().replace("+00:00", "Z"),
                "limit_price": None,
                "quantity": qty,
                "security_transaction_type": "SINGLE",
                "side": "BUY",
                "status": "SETTLED",
                "type": "SECURITY_TRANSACTION",
            })

        self.cash_end = 250.00
        self.deposit = {
            "amount": round(-total_spent + self.cash_end, 3),
            "cash_transaction_type": "DEPOSIT",
            "currency": "EUR",
            "description": "Initial Demo Deposit",
            "id": "DEMO_DEP_1",
            "is_cancellation": False,
            "last_event_datetime": (t0 - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "status": "SETTLED",
            "type": "CASH_TRANSACTION",
        }

    def mid(self, isin: str) -> float:
        return round(float(self.paths[isin][-1]), 4)

    def __call__(self, cmd: list[str], timeout: float) -> tuple[int, str, str]:
        args = cmd[1:]
        meta = {"account_id": "ACC_DEMO_01", "portfolio_id": "PF_DEMO_01"}
        if args[0] == "whoami":
            return 0, _envelope("whoami", {
                "result": {
                    "personOverview": {
                        "id": "DEMO_USER",
                        "personalDetails": {"firstName": "Demo", "lastName": "Investor"},
                    }
                }
            }), ""
        if args[:2] == ["broker", "holdings"]:
            items = [
                {
                    "blocked_quantity": 0,
                    "fifo_price": round(abs(b["amount"]) / b["quantity"], 4),
                    "isin": b["isin"],
                    "name": DEMO_HOLDINGS[b["isin"]][0],
                    "pending_quantity": 0,
                    "quantity": b["quantity"],
                    "quote_currency": "EUR",
                    "quote_is_outdated": False,
                    "quote_mid_price": self.mid(b["isin"]),
                    "quote_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "security_type": "ETF",
                    "valuation": round(b["quantity"] * self.mid(b["isin"]), 2),
                    "valuation_currency": "EUR",
                }
                for b in self.buys
            ]
            return 0, _envelope("broker.holdings", {
                **meta,
                "result": {**meta, "count": len(items), "items": items},
            }), ""
        if args[:2] == ["broker", "cash-breakdown"]:
            return 0, _envelope("broker.cash-breakdown", {
                **meta,
                "result": {
                    **meta,
                    "cash_balance": self.cash_end,
                    "buying_power": self.cash_end,
                    "buying_power_without_credit": self.cash_end,
                    "available_credit_line": 0,
                    "derivatives_buying_power": 0,
                    "pending_buy_orders_amount": 0,
                    "possible_taxes": 0,
                },
            }), ""
        if args[:2] == ["broker", "quote"]:
            isin = args[args.index("--isin") + 1]
            if isin not in self.paths:
                return 10, json.dumps({"ok": False, "error": {"code": "not_found", "message": "unknown"}}), ""
            m = self.mid(isin)
            return 0, _envelope("broker.quote", {
                **meta,
                "result": {
                    "isin": isin,
                    "name": DEMO_HOLDINGS.get(isin, (f"Asset {isin}", 0, 0))[0],
                    "quote_bid_price": round(m * 0.999, 4),
                    "quote_ask_price": round(m * 1.001, 4),
                    "quote_mid_price": m,
                    "quote_currency": "EUR",
                    "quote_is_outdated": False,
                    "quote_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "quote_performances": [
                        {"timeframe": "SIX_MONTHS", "performance": float(self.paths[isin][-1] / self.paths[isin][-64] - 1)},
                        {"timeframe": "ONE_YEAR", "performance": float(self.paths[isin][-1] / self.paths[isin][0] - 1)},
                    ],
                    "security_type": "ETF",
                },
            }), ""
        if args[:2] == ["broker", "chart"]:
            isin = args[args.index("--isin") + 1]
            tf = args[args.index("--timeframe") + 1]
            pts = [{"mid_price": round(float(v), 4), "timestamp_utc": t} for v, t in zip(self.paths[isin], self.times)]
            return 0, _envelope("broker.chart", {
                "isin": isin,
                "currency": "EUR",
                "source": "CONSOLIDATED",
                "timeframe": tf,
                "data_points": pts,
                "point_count": len(pts),
            }), ""
        if args[:2] == ["broker", "transactions"]:
            txs = sorted([self.deposit] + self.buys, key=lambda x: x["last_event_datetime"], reverse=True)
            return 0, _envelope("broker.transactions", {
                **meta,
                "result": {**meta, "count": len(txs), "cursor": None, "items": txs, "total": len(txs)},
            }), ""
        return 1, "", "unsupported command"


def seed_demo_database(db_path: Path, force: bool = False) -> None:
    if db_path.exists():
        if not force:
            raise FileExistsError(
                f"Database already exists at {db_path}. Pass --force to recreate with demo data."
            )
        db_path.unlink()

    db = DatabaseManager(db_path)
    db.initialize_schema()

    registry = IdentityRegistry(db=db)
    registry.seed_from_configs()

    import os
    os.environ.setdefault("MASA_SC_BIN", "/usr/bin/true")
    broker = SyntheticDemoBroker()
    pipe = Pipeline(db=db, reader=ScalableReader(runner=broker))
    snap_res = pipe.collect_snapshot()
    if not snap_res.ok:
        raise RuntimeError(f"Demo snapshot collection failed: {snap_res.quote_failures}")

    pipe.collect_history(list(DEMO_HOLDINGS.keys()))
    reconcile_ledger_with_broker(db)

    tm = ThesisManager(db)
    demo_theses = [
        ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Global All-Cap Equity Core (MSCI ACWI IMI)",
            one_line_summary="Broad global equity exposure across developed and emerging markets including small caps.",
            economic_rationale="Captures ~99% of global investable equity market capitalization in a single physical UCITS vehicle.",
            falsification_triggers=[
                "Total Expense Ratio (TER) increases above 0.30% p.a.",
                "Tracking difference vs MSCI ACWI IMI exceeds 0.50% over rolling 24 months",
            ],
            evidence_pillars=["Physical optimised replication", "TER 0.17% p.a.", "9,000+ index constituents"],
            target_allocation_pct=Decimal("0.45"),
            author="demo_seeder",
        ),
        ThesisRecord(
            isin="IE00BKM4GZ66",
            category=ThesisCategory.SATELLITE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Emerging Markets All-Cap Tilt (MSCI EM IMI)",
            one_line_summary="Dedicated emerging market large, mid, and small-cap equity exposure.",
            economic_rationale="Provides demographic and valuation diversification relative to US-heavy developed market indices.",
            falsification_triggers=[
                "TER increases above 0.30% p.a.",
                "Index concentration in a single country exceeds 40% for two consecutive quarters",
            ],
            evidence_pillars=["Physical replication", "TER 0.18% p.a.", "3,000+ EM constituents"],
            target_allocation_pct=Decimal("0.25"),
            author="demo_seeder",
        ),
    ]
    for thesis in demo_theses:
        tm.create_thesis(thesis)

    integ = integrity_report(db)
    if not integ["ok"]:
        raise RuntimeError(f"Integrity check failed on seeded demo DB: {integ}")

    print(f"Demo database successfully created and sealed at: {db_path}")
    print(f"  Schema version : v{integ['schema_version']} ({integ['trigger_count']} immutability triggers)")
    print(f"  Chain tip      : {integ['chain_tip']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a synthetic demo database for FinanceCockpit.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db_path(),
        help="Target SQLite database path (defaults to MASA_DB_PATH or masa/var/private/masa.db).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing database at --db-path if present.",
    )
    args = parser.parse_args()
    seed_demo_database(args.db_path, force=args.force)


if __name__ == "__main__":
    main()
