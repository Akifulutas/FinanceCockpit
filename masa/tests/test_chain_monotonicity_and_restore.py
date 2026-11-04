"""Tests for Step 2: Chain tip monotonicity and restore audit logging."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from masa.backup import (
    append_chain_tip_log,
    verify_chain_tips,
    restore_database,
    default_ledger_path,
)
from masa.storage.db import DatabaseManager
from masa.storage.snapshot_store import SnapshotStore
from masa.audit.events import AuditLogger


def test_append_ledger_prevents_unapproved_rewind(tmp_path: Path):
    """Appending BACKUP with fewer snapshots than previous ledger entry must raise RuntimeError."""
    ledger = tmp_path / "zincir-uclari.jsonl"
    
    # 1. First backup with 10 snapshots
    e1 = append_chain_tip_log(
        snapshot_chain_tip="1" * 64,
        snapshot_count=10,
        audit_chain_tip="a" * 64,
        audit_count=5,
        event="BACKUP",
        ledger_path=ledger,
    )
    assert e1.snapshot_count == 10

    # 2. Attempt second backup with only 2 snapshots without RESTORE -> MUST FAIL
    with pytest.raises(RuntimeError, match="CRITICAL: Onaysız geriye sarma"):
        append_chain_tip_log(
            snapshot_chain_tip="2" * 64,
            snapshot_count=2,
            audit_chain_tip="b" * 64,
            audit_count=2,
            event="BACKUP",
            ledger_path=ledger,
        )


def test_verify_chain_tips_detects_unapproved_rewind_in_ledger(tmp_path: Path):
    """If ledger contains an unapproved drop in count, verify_chain_tips must return CRITICAL_CHAIN_REWIND_DETECTED."""
    ledger = tmp_path / "zincir-uclari.jsonl"
    db_file = tmp_path / "test.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()

    # Manually create entries where line 2 rewinds count without RESTORE
    append_chain_tip_log("1" * 64, 10, "a" * 64, 5, event="BACKUP", ledger_path=ledger)
    
    # Forcefully append an invalid rewind line (simulating legacy bug or attacker)
    # Using RESTORE first then simulating
    lines = [json.loads(l) for l in ledger.read_text().splitlines()]
    prev_sha = lines[-1]["entry_sha256"]
    
    # Rewind to 0 count with event=BACKUP
    from masa.storage.hash_chain import sha256_text, canonical_json
    rewind_data = {
        "timestamp": "2026-10-31T10:00:00Z",
        "event": "BACKUP",
        "backup_filename": "fake.db",
        "backup_sha256": "f" * 64,
        "snapshot_chain_tip": "0" * 64,
        "snapshot_count": 0,
        "audit_chain_tip": "0" * 64,
        "audit_count": 0,
        "prev_entry_sha256": prev_sha,
    }
    rewind_data["entry_sha256"] = sha256_text(canonical_json(rewind_data))
    with open(ledger, "a") as f:
        f.write(canonical_json(rewind_data) + "\n")

    conn = mgr.get_connection()
    try:
        res = verify_chain_tips(conn, ledger_path=ledger)
        assert res.status == "CRITICAL_CHAIN_REWIND_DETECTED"
        assert "onaysız geriye sarma" in res.details
    finally:
        conn.close()


def test_verify_chain_tips_requires_all_historical_tips_in_live_db(tmp_path: Path):
    """Every historical tip in the ledger must exist in live DB snapshots."""
    ledger = tmp_path / "zincir-uclari.jsonl"
    db_file = tmp_path / "test.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()

    # 1. First test: live count < sealed count -> triggers rollback detection
    append_chain_tip_log("3" * 64, 5, "c" * 64, 2, event="BACKUP", ledger_path=ledger)
    conn = mgr.get_connection()
    try:
        res = verify_chain_tips(conn, ledger_path=ledger)
        assert res.status == "CRITICAL_MISMATCH"
        assert "kayıt sayısı dış kütükteki mühürlü sayıdan az" in res.details
    finally:
        conn.close()

    # 2. Second test: live count matches sealed count (e.g. 0), but ledger has previous non-zero tip
    # We create a ledger with 0 count at the end following a RESTORE with 0 count, but earlier had 5 snapshots
    # Or simulate live DB having enough count but lacking the previous tip:
    # Create audit events as well
    a_logger = AuditLogger(mgr)
    a_logger.log_event("test", "EVENT_1", "test", "1", {})
    a_logger.log_event("test", "EVENT_2", "test", "2", {})
    a_logger.log_event("test", "EVENT_3", "test", "3", {})

    store = SnapshotStore(mgr)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for i in range(6):
        raw_id, _ = store.store_raw_object("test", f'{{"idx": {i}}}', now)
        store.save_quote_snapshot(f"snap_test_{i}", raw_id, "sc", now, now, [])

    conn = mgr.get_connection()
    try:
        # Now live DB has 6 snapshots, but its tip is NOT "3"*64
        res2 = verify_chain_tips(conn, ledger_path=ledger)
        assert res2.status == "CRITICAL_MISMATCH"
        assert "önceki mühür ucu" in res2.details
    finally:
        conn.close()


def test_restore_database_appends_approved_restore_event(tmp_path: Path):
    """restore_database with confirm=True must append a RESTORE event to the ledger."""
    backup_file = tmp_path / "sample_backup.db"
    live_file = tmp_path / "live.db"
    b_mgr = DatabaseManager(backup_file)
    b_mgr.initialize_schema()

    mgr = DatabaseManager(live_file)
    mgr.initialize_schema()

    ledger = tmp_path / "backups" / "zincir-uclari.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    
    # Initial state in ledger
    append_chain_tip_log("1" * 64, 5, "a" * 64, 2, event="BACKUP", ledger_path=ledger)

    # Perform restore
    res = restore_database(backup_file, confirm=True, db_manager=mgr)
    assert res.success

    # Read ledger
    lines = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[-1]["event"] == "RESTORE"
    assert lines[-1]["backup_filename"] == backup_file.name
