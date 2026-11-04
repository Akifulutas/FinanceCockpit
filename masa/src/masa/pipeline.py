"""Broker -> ham kayit -> muhur -> okuma hatti.

Tek yazma yolu masa.db'dir; broker'a yazma yolu yoktur (ScalableReader salt okur).
Bir `veri` calismasi (run) ayni run_id ile uc muhur uretir: portfolio, cash, quotes.
`gecmis` calismasi her ISIN icin fiyat serisi ve tum islem gecmisini muhurler.
Raporlar YALNIZ bu muhurlerden okunur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from masa.audit.events import AuditLogger
from masa.calendar.adapter import CalendarAdapter
from masa.identity.isin import validate_isin
from masa.ingestion.models import ChartSeries, QuoteData, RawBrokerPayload
from masa.ingestion.sc_reader import ScalableReader
from masa.storage.db import DatabaseManager
from masa.storage.snapshot_store import SnapshotResult, SnapshotStore

ACTOR = "masa.pipeline"
FRESH_MAX_AGE_SECONDS = 900


def mask_id(value: Optional[str]) -> str:
    if not value:
        return "—"
    return value[:3] + "…" + value[-2:] if len(value) > 6 else "***"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(v: Any) -> Optional[Decimal]:
    return None if v is None else Decimal(str(v))


def classify_quote(q: QuoteData, snapshot_time: datetime, calendar: CalendarAdapter) -> Tuple[str, float]:
    """Quality without assuming a venue: broker flag + absolute age.

    OUTDATED  broker says the quote is outdated
    UNKNOWN   broker gives no outdated flag
    FRESH     broker flag false and age <= 15 min
    AGED      broker flag false but older than 15 min (e.g. weekend / night)
    """
    assessment = calendar.assess_quote_freshness(q.timestamp_utc, max(snapshot_time, q.timestamp_utc), venue_mic=None)
    age = assessment.age_seconds
    if q.is_outdated is True:
        return "OUTDATED", age
    if q.is_outdated is None:
        return "UNKNOWN", age
    return ("FRESH" if age <= FRESH_MAX_AGE_SECONDS else "AGED"), age


@dataclass
class CollectResult:
    run_id: str
    snapshots: Dict[str, SnapshotResult]
    quote_failures: List[str]
    quality: str
    total_positions_value: Decimal
    cash_balance: Decimal
    quotes_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.quote_failures

    @property
    def quotes(self) -> List[Any]:
        """Backward-compatible helper returning placeholder list of length quotes_count."""
        return [None] * self.quotes_count


class Pipeline:
    def __init__(self, db: Optional[DatabaseManager] = None, reader: Optional[ScalableReader] = None,
                 calendar: Optional[CalendarAdapter] = None) -> None:
        self.db = db or DatabaseManager()
        self.db.initialize_schema()
        if not self.db._is_memory:
            try:
                from masa.security import ensure_secure_permissions
                ensure_secure_permissions(self.db.db_path.parent)
            except Exception:
                pass
        self.store = SnapshotStore(self.db)
        self.audit = AuditLogger(self.db)
        self.reader = reader or ScalableReader()
        self.calendar = calendar or CalendarAdapter()

    # -------------------------------------------------------------- helpers
    def _store_raw(self, raw: RawBrokerPayload, count: int = 0) -> int:
        rid, _ = self.store.store_raw_object(f"sc.{raw.command}", raw.stdout_raw, raw.retrieved_at,
                                             record_count=count, command=" ".join(raw.args))
        return rid

    # -------------------------------------------------------------- veri
    def collect_snapshot(self, now: Optional[datetime] = None, extra_isins: Optional[Sequence[str]] = None) -> CollectResult:
        started = now or _now()
        run_id = f"run_{started.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
        self.audit.log_event(ACTOR, "RUN_STARTED", "run", run_id, {"kind": "snapshot"})

        whoami = self.reader.get_whoami()
        rid_who = self._store_raw(whoami)
        positions = self.reader.get_positions()
        raw_pos = self.reader.last_raw
        cash = self.reader.get_cash()
        raw_cash = self.reader.last_raw

        target_isins = list(dict.fromkeys([item.isin for item in positions.items] + list(extra_isins or [])))
        quotes: List[Tuple[QuoteData, RawBrokerPayload]] = []
        failures: List[str] = []
        for target_isin in target_isins:
            try:
                validate_isin(target_isin)
                q = self.reader.get_quote(target_isin)
                quotes.append((q, self.reader.last_raw))
            except Exception as exc:  # recorded, never silently dropped
                failures.append(f"{target_isin}: {exc}")
        completed = _now()

        rid_pos = self._store_raw(raw_pos, positions.count)
        rid_cash = self._store_raw(raw_cash, 1)
        quote_parts: List[Tuple[int, str]] = []
        quote_rows: List[Dict[str, Any]] = []
        statuses: List[str] = []
        for q, raw in quotes:
            rid = self._store_raw(raw, 1)
            quote_parts.append((rid, raw.payload_sha256))
            status, age = classify_quote(q, completed, self.calendar)
            statuses.append(status)
            quote_rows.append({
                "raw_object_id": rid, "isin": q.isin, "alias": q.name, "currency": q.currency,
                "bid": q.bid, "ask": q.ask, "provider_mid": q.mid, "computed_mid": q.computed_mid,
                "spread": q.spread, "spread_pct": q.spread_pct, "quote_timestamp": q.timestamp_utc,
                "retrieved_at": raw.retrieved_at, "quote_age_seconds": round(age, 3),
                "source": "sc.broker.quote", "exchange": None,
                "provider_outdated": q.is_outdated, "quality_status": status,
            })
        pos_rows = [{
            "isin": p.isin, "display_name": p.name, "security_type": p.security_type,
            "quantity": p.quantity, "blocked_quantity": p.blocked_quantity,
            "pending_quantity": p.pending_quantity, "unit_price_displayed": p.quote_mid_price,
            "value_eur": p.valuation, "currency": p.valuation_currency,
            "broker_cost_basis": p.fifo_price, "quote_timestamp": p.quote_timestamp_utc,
            "observed_at": positions.retrieved_at,
        } for p in positions.items]
        cash_rows = [{
            "account_id_masked": mask_id(cash.account_id), "currency": "EUR",
            "settled_cash": cash.cash_balance, "total_cash": cash.cash_balance,
            "buying_power": cash.buying_power, "pending_buy_orders_amount": cash.pending_buy_orders_amount,
            "possible_taxes": cash.possible_taxes, "observed_at": cash.retrieved_at,
        }]
        if failures:
            quality = "PARTIAL"
        elif all(s == "FRESH" for s in statuses):
            quality = "VALID"
        else:
            quality = "DEGRADED"
        # Unchanged broker output (e.g. same cash) re-uses the earlier seal; the run
        # binds whichever seals it used through the quote manifest below.
        snaps = {
            "portfolio": self.store.save_snapshot("portfolio", f"{run_id}_portfolio", rid_pos, "sc.broker.holdings",
                                                  started, completed, pos_rows, run_id=run_id),
            "cash": self.store.save_snapshot("cash", f"{run_id}_cash", rid_cash, "sc.broker.cash-breakdown",
                                             started, completed, cash_rows, run_id=run_id),
        }
        rid_manifest, _ = self.store.store_manifest(
            "sc.broker.quote", quote_parts, completed,
            extra={"run_id": run_id, "failures": failures, "whoami_raw_id": rid_who,
                   "binds": {k: {"snapshot_id": v.snapshot_id, "curr_hash": v.curr_hash} for k, v in snaps.items()}})
        snaps["quotes"] = self.store.save_snapshot("quotes", f"{run_id}_quotes", rid_manifest, "sc.broker.quote",
                                                   started, completed, quote_rows, run_id=run_id,
                                                   quality_status=quality)
        self.audit.log_event(ACTOR, "RUN_SEALED" if not failures else "RUN_PARTIAL", "run", run_id, {
            "snapshots": {k: {"id": v.snapshot_id, "hash": v.curr_hash, "new": v.created} for k, v in snaps.items()},
            "quote_failures": failures, "quality": quality,
        })
        total = sum((p.valuation for p in positions.items), Decimal("0"))
        return CollectResult(run_id, snaps, failures, quality, total, cash.cash_balance, quotes_count=len(quote_rows))

    # -------------------------------------------------------------- gecmis
    def collect_history(self, isins: Sequence[str], timeframes: Sequence[str] = ("1y", "max"),
                        now: Optional[datetime] = None, from_time: Optional[str] = None,
                        force_full: bool = False, include_transactions: bool = True) -> Dict[str, Any]:
        started = now or _now()
        run_id = f"hist_{started.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
        self.audit.log_event(ACTOR, "RUN_STARTED", "run", run_id, {"kind": "history", "isins": list(isins)})
        results: Dict[str, Any] = {"run_id": run_id, "series": {}, "errors": []}
        for isin in isins:
            for tf in timeframes:
                try:
                    series = self.reader.get_chart(isin, tf)
                    raw = self.reader.last_raw
                    rid = self._store_raw(raw, len(series.points))
                    rows = [{"raw_object_id": rid, "series_key": f"{isin}:{tf}", "series_kind": "mid_price",
                             "point_time": pt.timestamp_utc, "value": pt.mid_price} for pt in series.points]
                    res = self.store.save_snapshot("series", f"{run_id}_{isin}_{tf}", rid, f"sc.broker.chart:{series.source}",
                                                   started, _now(), rows, run_id=run_id)
                    results["series"][f"{isin}:{tf}"] = (res, len(rows))
                except Exception as exc:
                    results["errors"].append(f"chart {isin} {tf}: {exc}")
        if include_transactions:
            try:
                from masa.ingestion.transaction_ledger import calculate_incremental_from_time, ingest_transaction_versions
                conn = self.db.get_connection()
                try:
                    calc_from_time = calculate_incremental_from_time(conn, overlap_days=7, force_full=force_full)
                finally:
                    conn.close()
                effective_from_time = from_time or calc_from_time
                items, raws = self.reader.get_all_transactions(from_time=effective_from_time)
                parts = [(self._store_raw(r), r.payload_sha256) for r in raws]
                rid_manifest, _ = self.store.store_manifest("sc.broker.transactions", parts, _now(), extra={"run_id": run_id})
                rows = [{
                    "broker_tx_id": t.id, "tx_type": t.type, "cash_transaction_type": t.cash_transaction_type,
                    "security_transaction_type": t.security_transaction_type, "side": t.side, "isin": t.isin,
                    "description": t.description, "amount": t.amount, "currency": t.currency,
                    "quantity": t.quantity, "limit_price": t.limit_price, "status": t.status,
                    "is_cancellation": t.is_cancellation, "event_time": t.last_event_datetime,
                } for t in items]
                snap_res = self.store.save_snapshot(
                    "transactions", f"{run_id}_transactions", rid_manifest, "sc.broker.transactions",
                    started, _now(), rows, run_id=run_id)
                results["transactions"] = (snap_res, len(rows))

                ledger_stats = ingest_transaction_versions(
                    self.db, items, snapshot_id=snap_res.snapshot_id, raw_object_id=rid_manifest
                )
                results["ledger_stats"] = ledger_stats
            except Exception as exc:
                results["errors"].append(f"transactions: {exc}")
        self.audit.log_event(ACTOR, "RUN_SEALED" if not results["errors"] else "RUN_PARTIAL", "run", run_id,
                             {"series": sorted(results["series"]), "errors": results["errors"]})
        return results

    def collect_transactions(
        self,
        from_time: Optional[str] = None,
        force_full: bool = False,
    ) -> Dict[str, Any]:
        """Fetch transactions with 7-day lookback incremental fetch and ingest into ledger."""
        started = _now()
        run_id = f"txs_{started.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
        self.audit.log_event(ACTOR, "RUN_STARTED", "run", run_id, {"kind": "transactions"})

        from masa.ingestion.transaction_ledger import calculate_incremental_from_time, ingest_transaction_versions
        conn = self.db.get_connection()
        try:
            calc_from_time = calculate_incremental_from_time(conn, overlap_days=7, force_full=force_full)
        finally:
            conn.close()

        effective_from_time = from_time or calc_from_time
        items, raws = self.reader.get_all_transactions(from_time=effective_from_time)
        parts = [(self._store_raw(r), r.payload_sha256) for r in raws]
        rid_manifest, _ = self.store.store_manifest("sc.broker.transactions", parts, _now(), extra={"run_id": run_id})
        rows = [{
            "broker_tx_id": t.id, "tx_type": t.type, "cash_transaction_type": t.cash_transaction_type,
            "security_transaction_type": t.security_transaction_type, "side": t.side, "isin": t.isin,
            "description": t.description, "amount": t.amount, "currency": t.currency,
            "quantity": t.quantity, "limit_price": t.limit_price, "status": t.status,
            "is_cancellation": t.is_cancellation, "event_time": t.last_event_datetime,
        } for t in items]
        snap_res = self.store.save_snapshot(
            "transactions", f"{run_id}_transactions", rid_manifest, "sc.broker.transactions",
            started, _now(), rows, run_id=run_id)

        ledger_stats = ingest_transaction_versions(
            self.db, items, snapshot_id=snap_res.snapshot_id, raw_object_id=rid_manifest
        )
        self.audit.log_event(
            ACTOR,
            "RUN_SEALED",
            "run",
            run_id,
            {"from_time": effective_from_time, "items_count": len(items), "ledger_stats": ledger_stats},
        )
        return {
            "run_id": run_id,
            "from_time": effective_from_time,
            "items_count": len(items),
            "ledger_stats": ledger_stats,
            "snapshot": snap_res,
        }



# ====================================================================== reads
@dataclass
class SealedPosition:
    isin: str
    name: str
    quantity: Decimal
    broker_value: Decimal
    broker_mid: Decimal
    fifo_price: Optional[Decimal]
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    mid: Optional[Decimal] = None
    spread_pct: Optional[Decimal] = None
    quote_time: Optional[str] = None
    quote_age_seconds: Optional[float] = None
    quality: str = "MISSING"

    @property
    def value(self) -> Decimal:
        return self.quantity * self.mid if self.mid is not None else self.broker_value


@dataclass
class SealedRun:
    run_id: str
    completed_at: str
    hashes: Dict[str, str]
    quality: str
    positions: List[SealedPosition]
    cash: Decimal
    buying_power: Optional[Decimal]
    owner: Optional[str] = None
    performances: Dict[str, Dict[str, Decimal]] = field(default_factory=dict)

    @property
    def positions_value(self) -> Decimal:
        return sum((p.value for p in self.positions), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.positions_value + self.cash


def latest_run(db: DatabaseManager, run_id: Optional[str] = None) -> Optional[SealedRun]:
    conn = db.get_connection()
    try:
        if run_id is None:
            row = conn.execute("SELECT run_id FROM snapshots WHERE snapshot_type='quotes' AND run_id LIKE 'run_%' "
                               "ORDER BY rowid DESC LIMIT 1").fetchone()
            if not row:
                return None
            run_id = row[0]
        q_snap = conn.execute("SELECT * FROM snapshots WHERE run_id=? AND snapshot_type='quotes'", (run_id,)).fetchone()
        if q_snap is None:
            return None
        manifest = json.loads(conn.execute("SELECT payload_text FROM raw_objects WHERE raw_id=?",
                                           (q_snap["raw_object_id"],)).fetchone()[0])
        snaps = {"quotes": q_snap}
        for kind, ref in (manifest.get("binds") or {}).items():
            r = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=? AND curr_hash=?",
                             (ref["snapshot_id"], ref["curr_hash"])).fetchone()
            if r is None:
                raise RuntimeError(f"{run_id}: bağlı {kind} mührü bulunamadı veya hash uyuşmuyor")
            snaps[kind] = r
        if set(snaps) != {"portfolio", "cash", "quotes"}:
            return None
        positions = {r["isin"]: SealedPosition(
            isin=r["isin"], name=r["display_name"] or r["isin"], quantity=Decimal(r["quantity"] or "0"),
            broker_value=Decimal(r["value_eur"]), broker_mid=Decimal(r["unit_price_displayed"] or "0"),
            fifo_price=_dec(r["broker_cost_basis"]))
            for r in conn.execute("SELECT * FROM position_observations WHERE snapshot_id=? ORDER BY position_id",
                                  (snaps["portfolio"]["snapshot_id"],))}
        perfs: Dict[str, Dict[str, Decimal]] = {}
        for q in conn.execute("SELECT * FROM quotes WHERE snapshot_id=? ORDER BY quote_id",
                              (snaps["quotes"]["snapshot_id"],)):
            p = positions.get(q["isin"])
            if p is None:
                continue
            p.bid, p.ask, p.mid = Decimal(q["bid"]), Decimal(q["ask"]), Decimal(q["computed_mid"])
            p.spread_pct = Decimal(q["spread_pct"])
            p.quote_time = q["quote_timestamp"]
            p.quote_age_seconds = float(q["quote_age_seconds"]) if q["quote_age_seconds"] else None
            p.quality = q["quality_status"]
            raw = conn.execute("SELECT payload_text FROM raw_objects WHERE raw_id=?", (q["raw_object_id"],)).fetchone()
            if raw:
                try:
                    res = json.loads(raw[0])["data"]["result"]
                    perfs[q["isin"]] = {x["timeframe"]: Decimal(str(x["performance"]))
                                        for x in res.get("quote_performances") or [] if x.get("performance") is not None}
                except (KeyError, ValueError, TypeError):
                    pass
        c = conn.execute("SELECT * FROM cash_observations WHERE snapshot_id=?",
                         (snaps["cash"]["snapshot_id"],)).fetchone()
        owner = None
        try:
            who_id = manifest.get("whoami_raw_id")
            if who_id:
                who = json.loads(conn.execute("SELECT payload_text FROM raw_objects WHERE raw_id=?",
                                              (who_id,)).fetchone()[0])
                pd = who["data"]["result"]["personOverview"]["personalDetails"]
                owner = " ".join(x for x in (pd.get("firstName"), pd.get("lastName")) if x) or None
        except (KeyError, TypeError, ValueError):
            owner = None
        return SealedRun(
            run_id=run_id, completed_at=snaps["quotes"]["collection_completed_at"],
            hashes={k: v["curr_hash"] for k, v in snaps.items()}, quality=snaps["quotes"]["quality_status"],
            positions=list(positions.values()), cash=Decimal(c["total_cash"]) if c else Decimal("0"),
            buying_power=_dec(c["buying_power"]) if c else None, owner=owner, performances=perfs)
    finally:
        conn.close()


def latest_series(db: DatabaseManager, isin: str, timeframe: str = "1y") -> List[Tuple[datetime, Decimal]]:
    conn = db.get_connection()
    try:
        snap = conn.execute(
            """SELECT s.snapshot_id FROM snapshots s JOIN series_points p ON p.snapshot_id = s.snapshot_id
               WHERE s.snapshot_type='series' AND p.series_key=? ORDER BY s.rowid DESC LIMIT 1""",
            (f"{isin}:{timeframe}",)).fetchone()
        if not snap:
            return []
        return [(datetime.fromisoformat(r[0]), Decimal(r[1])) for r in conn.execute(
            "SELECT point_time, value FROM series_points WHERE snapshot_id=? ORDER BY point_time", (snap[0],))]
    finally:
        conn.close()


def latest_transactions(db: DatabaseManager) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    try:
        # Prefer v_transactions_current if transaction_versions contains records
        has_txv = 0
        try:
            has_txv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        except Exception:
            pass

        if has_txv > 0:
            rows = conn.execute(
                "SELECT * FROM v_transactions_current ORDER BY event_time, version_id"
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                # Map compatibility keys for analytics and performance engines
                d["cash_transaction_type"] = d.get("sub_type")
                d["security_transaction_type"] = d.get("sub_type")
                d["tx_row_id"] = d.get("version_id")
                out.append(d)
            return out

        # Fallback to transaction_observations
        snap = conn.execute("SELECT snapshot_id FROM snapshots WHERE snapshot_type='transactions' "
                            "ORDER BY rowid DESC LIMIT 1").fetchone()
        if not snap:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT * FROM transaction_observations WHERE snapshot_id=? ORDER BY event_time, tx_row_id", (snap[0],))]
    finally:
        conn.close()



def integrity_report(db: DatabaseManager, ledger_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Actually run every check the report claims (no static text)."""
    store = SnapshotStore(db)
    snap_ok, snap_err = store.verify_integrity()
    audit_ok, audit_err = AuditLogger(db).verify_integrity()
    conn = db.get_connection()
    try:
        triggers = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        out = {
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "recursive_triggers": conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 1,
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "sqlite_version": conn.execute("SELECT sqlite_version()").fetchone()[0],
            "trigger_count": triggers,
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
            "raw_objects": conn.execute("SELECT COUNT(*) FROM raw_objects").fetchone()[0],
            "audit_events": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            "chain_tip": (conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone() or [None])[0],
        }
        from masa.backup import default_ledger_path, verify_chain_tips
        from masa.storage.db import default_db_path

        l_path = ledger_path
        if l_path is None:
            if hasattr(db, "db_path") and not getattr(db, "_is_memory", False):
                try:
                    is_live = (db.db_path.resolve() == default_db_path().resolve())
                except Exception:
                    is_live = False

                if is_live:
                    l_path = default_ledger_path()
                else:
                    candidates = [
                        db.db_path.parent / "backups" / "zincir-uclari.jsonl",
                        db.db_path.parent.parent / "backups" / "zincir-uclari.jsonl",
                        db.db_path.parent / "zincir-uclari.jsonl",
                    ]
                    for cand in candidates:
                        if cand.exists():
                            l_path = cand
                            break
                    if l_path is None:
                        l_path = db.db_path.parent / "backups" / "zincir-uclari.jsonl"
            else:
                l_path = default_ledger_path()

        tip_res = verify_chain_tips(conn, ledger_path=l_path)
    finally:
        conn.close()

    is_critical_violation = tip_res.status.startswith("CRITICAL")
    out.update({
        "snapshot_chain_ok": snap_ok,
        "snapshot_chain_error": snap_err,
        "audit_chain_ok": audit_ok,
        "audit_chain_error": audit_err,
        "chain_tip_status": tip_res.status,
        "chain_tip_details": tip_res.details,
        "sealed_snapshot_tip": tip_res.sealed_snapshot_tip,
        "sealed_audit_tip": tip_res.sealed_audit_tip,
        "critical_integrity_violation": is_critical_violation,
        "ok": bool(
            snap_ok
            and audit_ok
            and out["journal_mode"].lower() == "truncate"
            and out["trigger_count"] >= 33
            and not is_critical_violation
        ),
    })
    return out

