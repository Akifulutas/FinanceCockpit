"""Append-only snapshot repository (schema v2).

* Ham nesne = sc komutunun stdout'u (veya cok parcali toplamalarda parca
  ozetlerini listeleyen kanonik bir manifest). Ayni icerik bir kez saklanir.
* Bir muhur ayni (snapshot_type, raw_object_id) icin yalnizca bir kez yazilir:
  ayni ham veri tekrar islenirse kopya olusmaz, yeni ham veri yeni muhur uretir.
* Her alt kaydin ozeti tum alanlardan hesaplanir; baslik ozeti alt ozetleri
  ekleme sirasiyla icerir ve onceki muhure baglanir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import (
    CHILD_SPECS,
    GENESIS_HASH,
    HashChainEngine,
    canonical_json,
    compute_header_hash,
    compute_record_hash,
    normalize_value,
    sha256_text,
)

CONNECTOR_VERSION = "masa-0.2.0"
_DEFAULTS = {"portfolio": {"currency": "EUR"}, "cash": {"currency": "EUR"}}


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    return value


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_id: str
    curr_hash: str
    created: bool


class SnapshotStore:
    """Manages append-only persistence of raw objects and snapshots."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    # ------------------------------------------------------------------ raw
    def store_raw_object(
        self,
        source: str,
        raw_payload: str,
        retrieved_at: datetime,
        record_count: int = 0,
        command: str = "",
    ) -> Tuple[int, bool]:
        """Store raw text once. Returns (raw_id, is_new)."""
        payload_sha256 = sha256_text(raw_payload)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT raw_id FROM raw_objects WHERE payload_sha256 = ?", (payload_sha256,)
            ).fetchone()
            if row:
                return int(row["raw_id"]), False
            cur = conn.execute(
                """INSERT INTO raw_objects
                   (source, command, payload_sha256, payload_text, retrieved_at, record_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source, command, payload_sha256, raw_payload, _iso(retrieved_at), record_count,
                 datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid), True

    def store_manifest(self, source: str, parts: Sequence[Tuple[int, str]],
                       retrieved_at: datetime, extra: Optional[Mapping[str, Any]] = None) -> Tuple[int, bool]:
        """Raw object for a multi-command collection: canonical list of (raw_id, sha256)."""
        manifest = {"kind": "manifest", "source": source,
                    "parts": [{"raw_id": rid, "sha256": sha} for rid, sha in parts],
                    **(dict(extra) if extra else {})}
        return self.store_raw_object(source, canonical_json(manifest), retrieved_at,
                                     record_count=len(parts), command="manifest")

    def raw_sha(self, raw_id: int) -> str:
        conn = self.db.get_connection()
        try:
            return str(conn.execute("SELECT payload_sha256 FROM raw_objects WHERE raw_id=?",
                                    (raw_id,)).fetchone()[0])
        finally:
            conn.close()

    # ------------------------------------------------------------ snapshots
    @staticmethod
    def get_latest_snapshot_hash(conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
        return str(row["curr_hash"]) if row else GENESIS_HASH

    def save_snapshot(
        self,
        snapshot_type: str,
        snapshot_id: str,
        raw_object_id: Optional[int],
        source: str,
        started_at: datetime,
        completed_at: datetime,
        rows: Iterable[Mapping[str, Any]],
        *,
        run_id: str = "",
        quality_status: str = "VALID",
        connector_version: str = CONNECTOR_VERSION,
    ) -> SnapshotResult:
        if snapshot_type not in CHILD_SPECS:
            raise ValueError(f"unknown snapshot_type {snapshot_type!r}")
        table, _pk, columns = CHILD_SPECS[snapshot_type]
        rows = list(rows)
        with self.db.transaction() as conn:
            if raw_object_id is not None:
                existing = conn.execute(
                    "SELECT snapshot_id, curr_hash FROM snapshots WHERE raw_object_id = ? AND snapshot_type = ?",
                    (raw_object_id, snapshot_type),
                ).fetchone()
                if existing:
                    return SnapshotResult(str(existing["snapshot_id"]), str(existing["curr_hash"]), False)

            prev_hash = self.get_latest_snapshot_hash(conn)  # read under BEGIN IMMEDIATE lock
            normalized: List[Dict[str, Optional[str]]] = []
            child_hashes: List[str] = []
            for r in rows:
                merged = {**_DEFAULTS.get(snapshot_type, {}), **{k: v for k, v in r.items() if v is not None}}
                values = {c: normalize_value(_iso(merged.get(c))) for c in columns}
                values["snapshot_id"] = snapshot_id
                if values.get("raw_object_id") is None and raw_object_id is not None:
                    values["raw_object_id"] = normalize_value(raw_object_id)
                normalized.append(values)
                child_hashes.append(compute_record_hash(snapshot_type, values))

            header = {
                "snapshot_id": snapshot_id, "run_id": run_id, "snapshot_type": snapshot_type,
                "collection_started_at": _iso(started_at), "collection_completed_at": _iso(completed_at),
                "raw_object_id": raw_object_id, "source": source, "item_count": len(rows),
                "quality_status": quality_status, "connector_version": connector_version,
                "prev_hash": prev_hash,
            }
            curr_hash = compute_header_hash(header, child_hashes)
            conn.execute(
                """INSERT INTO snapshots
                   (snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                    raw_object_id, source, item_count, quality_status, connector_version,
                    prev_hash, curr_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_id, run_id, snapshot_type, header["collection_started_at"],
                 header["collection_completed_at"], raw_object_id, source, len(rows),
                 quality_status, connector_version, prev_hash, curr_hash,
                 datetime.now(timezone.utc).isoformat()),
            )
            cols = list(columns) + ["record_hash"]
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            for values, h in zip(normalized, child_hashes):
                conn.execute(sql, [values[c] for c in columns] + [h])
            return SnapshotResult(snapshot_id, curr_hash, True)

    # ---- backwards compatible wrappers (return snapshot_id) ----
    def save_quote_snapshot(self, snapshot_id: str, raw_object_id: int, source: str,
                            started_at: datetime, completed_at: datetime,
                            quotes_data: List[Dict[str, Any]], connector_version: str = CONNECTOR_VERSION,
                            quality_status: str = "VALID", run_id: str = "") -> str:
        rows = []
        for q in quotes_data:
            r = dict(q)
            r.setdefault("source", source)
            r.setdefault("quality_status", "UNKNOWN")
            rows.append(r)
        return self.save_snapshot("quotes", snapshot_id, raw_object_id, source, started_at,
                                  completed_at, rows, run_id=run_id, quality_status=quality_status,
                                  connector_version=connector_version).snapshot_id

    def save_position_snapshot(self, snapshot_id: str, raw_object_id: int, source: str,
                               started_at: datetime, completed_at: datetime,
                               positions_data: List[Dict[str, Any]], connector_version: str = CONNECTOR_VERSION,
                               quality_status: str = "VALID", run_id: str = "") -> str:
        return self.save_snapshot("portfolio", snapshot_id, raw_object_id, source, started_at,
                                  completed_at, positions_data, run_id=run_id,
                                  quality_status=quality_status,
                                  connector_version=connector_version).snapshot_id

    def save_cash_snapshot(self, snapshot_id: str, raw_object_id: int, source: str,
                           started_at: datetime, completed_at: datetime,
                           cash_data: List[Dict[str, Any]], connector_version: str = CONNECTOR_VERSION,
                           quality_status: str = "VALID", run_id: str = "") -> str:
        return self.save_snapshot("cash", snapshot_id, raw_object_id, source, started_at,
                                  completed_at, cash_data, run_id=run_id,
                                  quality_status=quality_status,
                                  connector_version=connector_version).snapshot_id

    # ---------------------------------------------------------------- reads
    def snapshot_hash(self, snapshot_id: str) -> Optional[str]:
        conn = self.db.get_connection()
        try:
            r = conn.execute("SELECT curr_hash FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            return str(r[0]) if r else None
        finally:
            conn.close()

    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        """Field-level verification of raw objects and the full snapshot chain."""
        conn = self.db.get_connection()
        try:
            ok, err = HashChainEngine.verify_raw_objects(conn)
            if not ok:
                return ok, err
            return HashChainEngine.verify_snapshot_chain(conn)
        finally:
            conn.close()
