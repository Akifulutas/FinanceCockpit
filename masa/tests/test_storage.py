"""Tests for SQLite append-only persistence, triggers, deduplication, and SHA-256 hash chaining."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import pytest

from masa.storage import (
    GENESIS_HASH,
    DatabaseManager,
    HashChainEngine,
    SnapshotStore,
    compute_event_hash,
    get_database_connection,
    verify_hash_chain,
    sha256_text,
)


class TestStorageImmutabilityAndPragmas:
    """Verify engine-level BEFORE UPDATE / BEFORE DELETE abort triggers and journal settings."""

    def test_database_pragmas_and_permissions(self, tmp_path: Path) -> None:
        db_path = tmp_path / "private" / "test_masa.db"
        mgr = DatabaseManager(db_path=db_path)
        mgr.initialize_schema()

        # Check permissions
        assert oct(os.stat(db_path.parent).st_mode)[-3:] == "700"
        assert oct(os.stat(db_path).st_mode)[-3:] == "600"

        with mgr.transaction() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode;")
            journal_mode = cur.fetchone()[0]
            assert journal_mode.upper() == "TRUNCATE"

            cur.execute("PRAGMA foreign_keys;")
            fk = cur.fetchone()[0]
            assert fk == 1

            cur.execute("PRAGMA synchronous;")
            sync = cur.fetchone()[0]
            assert sync == 2  # 2 corresponds to FULL

    def test_immutability_triggers_abort_updates_and_deletes(self, tmp_path: Path) -> None:
        conn = get_database_connection(tmp_path / "immutable.db")
        cur = conn.cursor()

        # 1. raw_objects
        cur.execute(
            """INSERT INTO raw_objects (source, payload_sha256, payload_text, retrieved_at, created_at)
               VALUES ('test', 'hash1', 'payload1', '2026-10-30T10:00:00Z', '2026-10-30T10:00:00Z')"""
        )
        raw_id = cur.lastrowid
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE raw_objects SET source = 'tampered' WHERE raw_id = ?", (raw_id,))

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM raw_objects WHERE raw_id = ?", (raw_id,))

        # 2. snapshots
        cur.execute(
            """INSERT INTO snapshots 
               (snapshot_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at)
               VALUES ('snap1', 'quotes', '2026-10-30T10:00:00Z', '2026-10-30T10:01:00Z',
                       ?, 'test', 1, 'VALID', 'v1', ?, 'curr1', '2026-10-30T10:01:00Z')""",
            (raw_id, GENESIS_HASH),
        )
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE snapshots SET quality_status = 'TAMPERED' WHERE snapshot_id = 'snap1'")

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM snapshots WHERE snapshot_id = 'snap1'")

        # 3. quotes
        cur.execute(
            """INSERT INTO quotes
               (snapshot_id, isin, currency, bid, ask, computed_mid, spread, spread_pct,
                quote_timestamp, retrieved_at, source, quality_status, record_hash)
               VALUES ('snap1', 'IE00B3YLTY66', 'EUR', '11.50', '11.60', '11.55', '0.10', '0.86',
                       '2026-10-30T10:00:00Z', '2026-10-30T10:01:00Z', 'sc', 'FRESH', 'rec1')"""
        )
        quote_id = cur.lastrowid
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE quotes SET bid = '12.00' WHERE quote_id = ?", (quote_id,))

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM quotes WHERE quote_id = ?", (quote_id,))

        # 4. position_observations
        cur.execute(
            """INSERT INTO position_observations
               (snapshot_id, isin, value_eur, record_hash)
               VALUES ('snap1', 'IE00B3YLTY66', '1000.00', 'pos_hash1')"""
        )
        pos_id = cur.lastrowid
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE position_observations SET value_eur = '2000.00' WHERE position_id = ?", (pos_id,))

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM position_observations WHERE position_id = ?", (pos_id,))

        # 5. cash_observations
        cur.execute(
            """INSERT INTO cash_observations
               (snapshot_id, account_id_masked, settled_cash, total_cash, observed_at, record_hash)
               VALUES ('snap1', '***1234', '500.00', '500.00', '2026-10-30T10:00:00Z', 'cash_hash1')"""
        )
        cash_id = cur.lastrowid
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE cash_observations SET total_cash = '999.00' WHERE cash_id = ?", (cash_id,))

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM cash_observations WHERE cash_id = ?", (cash_id,))

        # 6. audit_events
        cur.execute(
            """INSERT INTO audit_events
               (event_uuid, event_time, actor, action, entity_type, entity_id,
                payload_json, payload_sha256, prev_hash, curr_hash)
               VALUES ('uuid1', '2026-10-30T10:00:00Z', 'user', 'LOGIN', 'auth', 'u1',
                       '{}', 'phash1', ?, 'ahash1')""",
            (GENESIS_HASH,),
        )
        conn.commit()

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("UPDATE audit_events SET actor = 'hacker' WHERE event_uuid = 'uuid1'")

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
            cur.execute("DELETE FROM audit_events WHERE event_uuid = 'uuid1'")


class TestDeduplicationAndHashChain:
    """Verify idempotency on restarts and cryptographic chaining integrity."""

    def test_raw_payload_and_snapshot_deduplication(self, tmp_path: Path) -> None:
        mgr = DatabaseManager(tmp_path / "dedup.db")
        mgr.initialize_schema()
        store = SnapshotStore(mgr)

        now = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
        raw_text = '{"ok": true, "data": {"items": [1, 2, 3]}}'

        # First insert
        raw_id_1, is_new_1 = store.store_raw_object("test_source", raw_text, now)
        assert is_new_1 is True

        # Second insert with identical payload
        raw_id_2, is_new_2 = store.store_raw_object("test_source", raw_text, now)
        assert is_new_2 is False
        assert raw_id_1 == raw_id_2

        # Quote snapshot idempotency
        quotes_data = [
            {
                "isin": "US0378331005",
                "currency": "EUR",
                "bid": "309.65",
                "ask": "309.85",
                "computed_mid": "309.75",
                "spread": "0.20",
                "spread_pct": "0.065",
                "quote_timestamp": "2026-10-30T09:30:00Z",
                "retrieved_at": "2026-10-30T09:31:00Z",
                "quality_status": "FRESH",
            }
        ]

        sid_1 = store.save_quote_snapshot(
            snapshot_id="snap_quote_1",
            raw_object_id=raw_id_1,
            source="sc_cli",
            started_at=now,
            completed_at=now,
            quotes_data=quotes_data,
        )
        assert sid_1 == "snap_quote_1"

        # Duplicate attempt with same raw_object_id
        sid_2 = store.save_quote_snapshot(
            snapshot_id="snap_quote_duplicate",
            raw_object_id=raw_id_1,
            source="sc_cli",
            started_at=now,
            completed_at=now,
            quotes_data=quotes_data,
        )
        assert sid_2 == "snap_quote_1"

    def test_cryptographic_hash_chain_verification(self, tmp_path: Path) -> None:
        mgr = DatabaseManager(tmp_path / "chain.db")
        mgr.initialize_schema()
        store = SnapshotStore(mgr)

        t1 = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 11, 0, 0, tzinfo=timezone.utc)

        raw_id_1, _ = store.store_raw_object("src", "payload 1", t1)
        raw_id_2, _ = store.store_raw_object("src", "payload 2", t2)

        q1 = [
            {
                "isin": "US0378331005",
                "currency": "EUR",
                "bid": "300.00",
                "ask": "301.00",
                "computed_mid": "300.50",
                "spread": "1.00",
                "spread_pct": "0.33",
                "quote_timestamp": "2026-10-30T10:00:00Z",
                "retrieved_at": "2026-10-30T10:01:00Z",
                "quality_status": "FRESH",
            }
        ]
        q2 = [
            {
                "isin": "IE00BKM4GZ66",
                "currency": "EUR",
                "bid": "45.00",
                "ask": "45.10",
                "computed_mid": "45.05",
                "spread": "0.10",
                "spread_pct": "0.22",
                "quote_timestamp": "2026-10-30T11:00:00Z",
                "retrieved_at": "2026-10-30T11:01:00Z",
                "quality_status": "FRESH",
            }
        ]

        store.save_quote_snapshot("snap_01", raw_id_1, "src", t1, t1, q1)
        store.save_quote_snapshot("snap_02", raw_id_2, "src", t2, t2, q2)

        # Verify snapshot chain
        valid, err = store.verify_integrity()
        assert valid is True
        assert err is None

        # Verify audit chain with helper
        with mgr.transaction() as conn:
            cur = conn.cursor()
            prev_hash = GENESIS_HASH
            PH = sha256_text('{}')
            h1 = compute_event_hash("u1", "2026-10-30T10:00:00Z", "sys", "INIT", "SYS", "S1", PH, prev_hash)
            cur.execute(
                """INSERT INTO audit_events 
                   (event_uuid, event_time, actor, action, entity_type, entity_id,
                    payload_json, payload_sha256, prev_hash, curr_hash)
                   VALUES ('u1', '2026-10-30T10:00:00Z', 'sys', 'INIT', 'SYS', 'S1', '{}', ?, ?, ?)""",
                (PH, prev_hash, h1),
            )
            h2 = compute_event_hash("u2", "2026-10-30T10:05:00Z", "usr", "RUN", "JOB", "J1", PH, h1)
            cur.execute(
                """INSERT INTO audit_events 
                   (event_uuid, event_time, actor, action, entity_type, entity_id,
                    payload_json, payload_sha256, prev_hash, curr_hash)
                   VALUES ('u2', '2026-10-30T10:05:00Z', 'usr', 'RUN', 'JOB', 'J1', '{}', ?, ?, ?)""",
                (PH, h1, h2),
            )

        with mgr.transaction() as conn:
            assert verify_hash_chain(conn) is True
