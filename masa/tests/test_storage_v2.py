"""Regression tests for the 2026-10-30 audit findings K1/K2 (schema v2)."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from masa.storage import DatabaseManager, SchemaVersionError, SnapshotStore

NOW = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)


def _quote(bid: str):
    return [{"isin": "IE00B3YLTY66", "currency": "EUR", "bid": bid, "ask": "11.62",
             "provider_mid": "11.61", "computed_mid": "11.61", "spread": "0.02",
             "spread_pct": "0.17", "quote_timestamp": NOW, "retrieved_at": NOW,
             "quality_status": "FRESH"}]


@pytest.fixture
def store(tmp_path):
    mgr = DatabaseManager(tmp_path / "v2.db")
    mgr.initialize_schema()
    return SnapshotStore(mgr)


def test_new_raw_payload_creates_new_snapshot(store):
    r1, _ = store.store_raw_object("sc", '{"bid": 11.60, "t": 1}', NOW)
    r2, new = store.store_raw_object("sc", '{"bid": 12.00, "t": 2}', NOW + timedelta(hours=1))
    assert new is True and r1 != r2
    s1 = store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, _quote("11.60"))
    s2 = store.save_quote_snapshot("snap_B", r2, "sc", NOW, NOW, _quote("12.00"))
    assert (s1, s2) == ("snap_A", "snap_B")
    conn = store.db.get_connection()
    assert [r[0] for r in conn.execute("SELECT bid FROM quotes ORDER BY quote_id")] == ["11.60", "12.00"]
    assert store.verify_integrity() == (True, None)


def test_same_raw_payload_is_idempotent(store):
    r1, _ = store.store_raw_object("sc", '{"x": 1}', NOW)
    assert store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, _quote("11.60")) == "snap_A"
    assert store.save_quote_snapshot("snap_dup", r1, "sc", NOW, NOW, _quote("11.60")) == "snap_A"


@pytest.mark.parametrize("sql", [
    "INSERT OR REPLACE INTO quotes(quote_id, snapshot_id, isin, currency, bid, ask, computed_mid, spread,"
    " spread_pct, quote_timestamp, retrieved_at, source, quality_status, record_hash)"
    " SELECT quote_id, snapshot_id, isin, currency, '50.00', '50.02', '50.01', spread, spread_pct,"
    " quote_timestamp, retrieved_at, source, quality_status, record_hash FROM quotes WHERE quote_id = 1",
    "INSERT OR REPLACE INTO raw_objects(raw_id, source, payload_sha256, payload_text, retrieved_at,"
    " record_count, created_at) VALUES (1, 'evil', 'x', 'forged', 't', 0, 't')",
    "REPLACE INTO snapshots SELECT * FROM snapshots",
])
def test_replace_cannot_overwrite_sealed_rows(store, sql):
    r1, _ = store.store_raw_object("sc", '{"x": 1}', NOW)
    store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, _quote("11.60"))
    conn = store.db.get_connection()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(sql)
    assert conn.execute("SELECT bid FROM quotes").fetchone()[0] == "11.60"


def test_replace_blocked_even_without_masa_pragmas(store):
    """A foreign client without recursive_triggers is still stopped by INSERT guards."""
    r1, _ = store.store_raw_object("sc", '{"x": 1}', NOW)
    store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, _quote("11.60"))
    raw = sqlite3.connect(str(store.db.db_path))
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("INSERT OR REPLACE INTO raw_objects(raw_id, source, payload_sha256, payload_text,"
                    " retrieved_at, record_count, created_at) VALUES (1,'e','x','f','t',0,'t')")


def test_data_tamper_with_dropped_trigger_is_detected(store):
    r1, _ = store.store_raw_object("sc", '{"x": 1}', NOW)
    store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, _quote("11.60"))
    raw = sqlite3.connect(str(store.db.db_path))
    raw.execute("DROP TRIGGER prevent_update_quotes")
    raw.execute("UPDATE quotes SET bid='99.99', ask='100', computed_mid='99.995'")
    raw.commit()
    ok, err = store.verify_integrity()
    assert ok is False and "Record tampered" in err


def test_deleted_child_row_is_detected(store):
    r1, _ = store.store_raw_object("sc", '{"x": 1}', NOW)
    rows = _quote("11.60") + [dict(_quote("11.60")[0], isin="IE00BKM4GZ66")]
    store.save_quote_snapshot("snap_A", r1, "sc", NOW, NOW, rows)
    raw = sqlite3.connect(str(store.db.db_path))
    raw.execute("DROP TRIGGER prevent_delete_quotes")
    raw.execute("DELETE FROM quotes WHERE isin='IE00BKM4GZ66'")
    raw.commit()
    ok, err = store.verify_integrity()
    assert ok is False and "Child count mismatch" in err


def test_raw_payload_tamper_is_detected(store):
    store.store_raw_object("sc", '{"x": 1}', NOW)
    raw = sqlite3.connect(str(store.db.db_path))
    raw.execute("DROP TRIGGER prevent_update_raw_objects")
    raw.execute("UPDATE raw_objects SET payload_text='{\"x\": 2}'")
    raw.commit()
    ok, err = store.verify_integrity()
    assert ok is False and "raw_objects" in err


def test_old_schema_database_is_refused(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE snapshots (snapshot_id TEXT PRIMARY KEY)")
    c.commit(); c.close()
    with pytest.raises(SchemaVersionError):
        DatabaseManager(p).initialize_schema()


def test_pragmas_are_enforced(store):
    conn = store.db.get_connection()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "truncate"
    assert conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
