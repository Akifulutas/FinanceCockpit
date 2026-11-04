"""Tests for SQLite online backup, restore drill, restore, and chain tip verification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import pytest

from masa.audit.events import AuditLogger
from masa.backup import (
    BackupCorruptionError,
    BackupError,
    BackupManifest,
    BackupResult,
    ChainDivergenceError,
    ChainTipEntry,
    RestoreConfirmationRequiredError,
    RestoreDrillResult,
    RestoreResult,
    append_chain_tip_log,
    check_filevault_status,
    compute_file_sha256,
    create_backup,
    find_latest_backup,
    restore_database,
    restore_drill,
    verify_chain_tips,
)
from masa.cli import main as cli_main
from masa.pipeline import integrity_report
from masa.storage import DatabaseManager, SCHEMA_VERSION, SnapshotStore
from masa.storage.hash_chain import canonical_json


@pytest.fixture
def sample_db(tmp_path: Path) -> DatabaseManager:
    """Creates a temporary SQLite database initialized with schema and a valid snapshot chain."""
    db_file = tmp_path / "var" / "private" / "masa.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema()

    store = SnapshotStore(mgr)
    now = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)
    raw_id, _ = store.store_raw_object("sc", '{"quotes": [{"isin": "IE00B3YLTY66", "bid": 11.60}]}', now)
    quotes = [{
        "isin": "IE00B3YLTY66",
        "currency": "EUR",
        "bid": "11.60",
        "ask": "11.62",
        "provider_mid": "11.61",
        "computed_mid": "11.61",
        "spread": "0.02",
        "spread_pct": "0.17",
        "quote_timestamp": now,
        "retrieved_at": now,
        "quality_status": "FRESH",
    }]
    store.save_quote_snapshot("snap_001", raw_id, "sc", now, now, quotes)

    # Insert an audit event
    AuditLogger(mgr).log_event("test_actor", "INIT_TEST", "test", "1", {"hello": "world"})
    return mgr


# ---------------------------------------------------------------- Test 1
def test_create_backup_creates_manifest_and_ledger_entry(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    assert res.success is True
    assert res.db_path.exists()
    assert res.manifest_path.exists()
    assert res.chain_tip_recorded is True

    # Check file permissions
    db_stat = res.db_path.stat()
    assert oct(db_stat.st_mode)[-3:] == "600"
    dir_stat = backup_dir.stat()
    assert oct(dir_stat.st_mode)[-3:] == "700"

    # Verify manifest
    manifest_data = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    manifest = BackupManifest(**manifest_data)
    assert manifest.schema_version == SCHEMA_VERSION
    assert manifest.snapshot_count == 1
    assert manifest.audit_count >= 1
    assert manifest.backup_sha256 == compute_file_sha256(res.db_path)

    # Verify independent ledger
    ledger_file = backup_dir / "zincir-uclari.jsonl"
    assert ledger_file.exists()
    lines = [line.strip() for line in ledger_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    entry_dict = json.loads(lines[0])
    entry = ChainTipEntry(**entry_dict)
    assert entry.snapshot_chain_tip == manifest.snapshot_chain_tip
    assert entry.snapshot_count == manifest.snapshot_count
    assert entry.audit_chain_tip == manifest.audit_chain_tip
    assert entry.backup_filename == res.db_path.name
    assert entry.prev_entry_sha256 == "0" * 64


# ---------------------------------------------------------------- Test 2
def test_restore_drill_isolated_success(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is True
    assert drill_res.db_sha256_matches is True
    assert drill_res.sqlite_integrity_ok is True
    assert drill_res.raw_objects_verified is True
    assert drill_res.snapshot_chain_verified is True
    assert drill_res.audit_chain_verified is True
    assert drill_res.tips_match_manifest is True
    assert drill_res.schema_version == SCHEMA_VERSION
    assert drill_res.trigger_count >= 24
    assert len(drill_res.errors) == 0


# ---------------------------------------------------------------- Test 3
def test_restore_drill_does_not_touch_live_db(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    live_path = sample_db.db_path
    stat_before = live_path.stat()
    sha_before = compute_file_sha256(live_path)

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is True

    stat_after = live_path.stat()
    sha_after = compute_file_sha256(live_path)

    assert stat_before.st_ino == stat_after.st_ino, "Canlı DB inode değişmemeli!"
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns, "Canlı DB mtime değişmemeli!"
    assert sha_before == sha_after, "Canlı DB içeriği değişmemeli!"


# ---------------------------------------------------------------- Test 4
def test_restore_drill_rejects_sha256_mismatch(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    # Tamper with 1 byte in the backup db
    data = bytearray(res.db_path.read_bytes())
    data[100] = (data[100] + 1) % 256
    res.db_path.write_bytes(bytes(data))

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert drill_res.db_sha256_matches is False
    assert any("SHA-256 uyuşmazlığı" in err for err in drill_res.errors)


# ---------------------------------------------------------------- Test 5
def test_restore_drill_rejects_truncated_db(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    # Truncate file to half size
    data = res.db_path.read_bytes()
    truncated = data[: len(data) // 2]
    res.db_path.write_bytes(truncated)

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert any("SHA-256" in err or "bütünlük" in err or "quick_check" in err for err in drill_res.errors)


# ---------------------------------------------------------------- Test 6
def test_restore_drill_detects_manipulated_hash_chain(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    # Manipulate a record in sqlite table directly without triggers aborting
    raw_conn = sqlite3.connect(str(res.db_path))
    raw_conn.execute("PRAGMA recursive_triggers = OFF;")
    raw_conn.execute("DROP TRIGGER IF EXISTS prevent_update_quotes;")
    raw_conn.execute("UPDATE quotes SET computed_mid = 999.0 WHERE isin='IE00B3YLTY66';")
    raw_conn.commit()
    raw_conn.close()

    # Re-compute file sha256 and update manifest so SHA check passes
    new_sha = compute_file_sha256(res.db_path)
    manifest_data = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    manifest_data["backup_sha256"] = new_sha
    res.manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert drill_res.snapshot_chain_verified is False
    assert any("Record tampered" in err or "doğrulaması başarısız" in err for err in drill_res.errors)


# ---------------------------------------------------------------- Test 7
def test_restore_database_requires_confirmation_flag(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    with pytest.raises(RestoreConfirmationRequiredError):
        restore_database(res.db_path, confirm=False, db_manager=sample_db)


# ---------------------------------------------------------------- Test 8
def test_restore_database_archives_live_db_and_replaces_atomically(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res_v1 = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    # Now mutate live DB by adding a new audit event (State 2)
    AuditLogger(sample_db).log_event("actor_v2", "STATE_2_EVENT", "state", "v2", {"version": 2})

    conn = sample_db.get_connection()
    audit_count_v2 = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    conn.close()
    assert audit_count_v2 > res_v1.manifest.audit_count

    # Perform restore with confirm=True
    restore_res = restore_database(res_v1.db_path, confirm=True, db_manager=sample_db)

    assert restore_res.success is True
    assert restore_res.archived_live_db is not None
    archived_file = Path(restore_res.archived_live_db)
    assert archived_file.exists()
    assert "pre-restore" in archived_file.name

    # Check that live DB has been restored to v1 state (plus the 1 restore audit event)
    conn = sample_db.get_connection()
    restored_snap_tip = conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    restore_event = conn.execute(
        "SELECT action, payload_json FROM audit_events WHERE action='RESTORE_DATABASE'"
    ).fetchone()
    conn.close()

    assert restored_snap_tip == res_v1.manifest.snapshot_chain_tip
    assert restore_event is not None


# ---------------------------------------------------------------- Test 9
def test_restore_database_aborts_if_drill_fails_without_touching_live_db(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)

    # Corrupt backup
    res.db_path.write_bytes(b"corrupted SQLite header")

    live_sha_before = compute_file_sha256(sample_db.db_path)

    with pytest.raises(BackupCorruptionError):
        restore_database(res.db_path, confirm=True, db_manager=sample_db)

    live_sha_after = compute_file_sha256(sample_db.db_path)
    assert live_sha_before == live_sha_after, "Canlı DB asla değişmemeli!"


# ---------------------------------------------------------------- Test 10
def test_chain_tip_divergence_detected_in_integrity_report(sample_db: DatabaseManager, tmp_path: Path):
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    # Case A: Henüz hiç yedek yokken
    report = integrity_report(sample_db, ledger_path=ledger_path)
    assert report["ok"] is True
    assert report["chain_tip_status"] == "NO_EXTERNAL_LEDGER"
    assert report["critical_integrity_violation"] is False

    # Case B: Yedek alındı -> MATCH_SEALED
    res = create_backup(db_manager=sample_db, backup_dir=backup_dir)
    report = integrity_report(sample_db, ledger_path=ledger_path)
    assert report["ok"] is True
    assert report["chain_tip_status"] == "MATCH_SEALED"
    assert report["critical_integrity_violation"] is False

    # Case C: Canlı DB'ye yeni bir mühür eklendi -> AHEAD_OF_SEALED
    store = SnapshotStore(sample_db)
    now = datetime(2026, 10, 30, 17, 0, tzinfo=timezone.utc)
    raw_id2, _ = store.store_raw_object("sc", '{"quotes": [{"isin": "IE00BKM4GZ66", "bid": 40.00}]}', now)
    quotes2 = [{
        "isin": "IE00BKM4GZ66",
        "currency": "EUR",
        "bid": "40.00",
        "ask": "40.10",
        "provider_mid": "40.05",
        "computed_mid": "40.05",
        "spread": "0.10",
        "spread_pct": "0.25",
        "quote_timestamp": now,
        "retrieved_at": now,
        "quality_status": "FRESH",
    }]
    store.save_quote_snapshot("snap_002", raw_id2, "sc", now, now, quotes2)

    report = integrity_report(sample_db, ledger_path=ledger_path)
    assert report["ok"] is True
    assert report["chain_tip_status"] == "AHEAD_OF_SEALED"
    assert report["critical_integrity_violation"] is False

    # Case D: Kütükte canlı DB'de bulunmayan sahte bir mühür ucu olması -> CRITICAL_MISMATCH
    fake_ledger_path = tmp_path / "fake_ledger.jsonl"
    fake_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "BACKUP",
        "backup_filename": "fake.db",
        "backup_sha256": "0" * 64,
        "snapshot_chain_tip": "f" * 64,
        "snapshot_count": 10,
        "audit_chain_tip": "a" * 64,
        "audit_count": 10,
        "prev_entry_sha256": "0" * 64,
    }
    fake_entry["entry_sha256"] = hashlib.sha256(canonical_json(fake_entry).encode("utf-8")).hexdigest()
    fake_ledger_path.write_text(canonical_json(fake_entry) + "\n", encoding="utf-8")

    report_fake = integrity_report(sample_db, ledger_path=fake_ledger_path)
    assert report_fake["ok"] is False
    assert report_fake["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert report_fake["critical_integrity_violation"] is True


# ---------------------------------------------------------------- Test 11
def test_cli_yedek_and_geri_yukle(sample_db: DatabaseManager, tmp_path: Path, monkeypatch):
    backup_dir = tmp_path / "cli_backups"
    monkeypatch.setenv("MASA_DB_PATH", str(sample_db.db_path))
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    # 1. masa yedek
    with pytest.raises(SystemExit) as exc:
        cli_main(["yedek"])
    assert exc.value.code == 0

    # 2. masa yedek --prova
    with pytest.raises(SystemExit) as exc:
        cli_main(["yedek", "--prova"])
    assert exc.value.code == 0

    # 3. masa geri-yukle without --onayla -> must fail with exit code 1
    with pytest.raises(SystemExit) as exc:
        cli_main(["geri-yukle"])
    assert exc.value.code == 1

    # 4. masa geri-yukle --onayla -> must succeed with exit code 0
    with pytest.raises(SystemExit) as exc:
        cli_main(["geri-yukle", "--onayla"])
    assert exc.value.code == 0

    # 5. masa dogrula -> must succeed with exit code 0
    with pytest.raises(SystemExit) as exc:
        cli_main(["dogrula"])
    assert exc.value.code == 0


# ---------------------------------------------------------------- Test 12
def test_check_filevault_status():
    status = check_filevault_status()
    assert isinstance(status, str)
    assert len(status) > 0
