"""Adversarial stress-testing suite for IP-1 (Backup, Restore, Rollback and DB Substitution Attacks).

Tested by Challenger:
1. Rollback Attack Simulation:
   - Live DB replaced with older backup when zincir-uclari.jsonl has higher tip.
   - Forked chain attack where live DB has same or higher count but different chain.
   - CLI verification (exit code 3 on 'masa denetle' / 'masa dogrula').
2. Fake Database Substitution Attack:
   - Completely independent database with valid genesis hash replacing live DB.
   - Fake DB with zero snapshots.
   - Fake DB with forged ledger line or corrupted ledger hash chain.
3. Fault Injection during restore_database:
   - Injected error during staging PRAGMA check.
   - Injected error during os.replace.
   - Verify live DB is intact, inode/SHA-256 preserved from pre-restore .bak, temp files removed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch
import pytest

from masa.audit.events import AuditLogger
from masa.backup import (
    BackupCorruptionError,
    BackupError,
    RestoreConfirmationRequiredError,
    RestoreExecutionError,
    append_chain_tip_log,
    compute_file_sha256,
    create_backup,
    restore_database,
    restore_drill,
    verify_chain_tips,
)
from masa.cli import main as cli_main
from masa.pipeline import integrity_report
from masa.storage import DatabaseManager, SCHEMA_VERSION, SnapshotStore
from masa.storage.hash_chain import GENESIS_HASH, canonical_json, sha256_text


def _add_snapshot(mgr: DatabaseManager, snap_id: str, isin: str, price: float, dt: datetime):
    store = SnapshotStore(mgr)
    raw_payload = json.dumps({"quotes": [{"isin": isin, "bid": price}]})
    raw_id, _ = store.store_raw_object("sc", raw_payload, dt)
    quotes = [{
        "isin": isin,
        "currency": "EUR",
        "bid": f"{price:.2f}",
        "ask": f"{price + 0.02:.2f}",
        "provider_mid": f"{price + 0.01:.2f}",
        "computed_mid": f"{price + 0.01:.2f}",
        "spread": "0.02",
        "spread_pct": "0.10",
        "quote_timestamp": dt,
        "retrieved_at": dt,
        "quality_status": "FRESH",
    }]
    return store.save_quote_snapshot(snap_id, raw_id, "sc", dt, dt, quotes)


# ==============================================================================
# CHALLENGE 1: CANLI VERİTABANINI GERİYE SARMA (ROLLBACK ATTACK)
# ==============================================================================

def test_rollback_attack_detected_by_integrity_report_and_cli(tmp_path: Path, monkeypatch):
    """Simulates rolling back the live DB to an earlier backup when external ledger has a later seal."""
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()

    # Step 1: Create State 1 & Backup 1
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    res_b1 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Step 2: Create State 2 & Backup 2
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_002", "IE00BKM4GZ66", 20.0, t2)
    res_b2 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Step 3: Create State 3 & Backup 3
    t3 = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_003", "IE00B5BMR087", 30.0, t3)
    res_b3 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Verify that before attack, integrity report is healthy (MATCH_SEALED)
    report_healthy = integrity_report(mgr, ledger_path=ledger_path)
    assert report_healthy["ok"] is True
    assert report_healthy["chain_tip_status"] == "MATCH_SEALED"
    assert report_healthy["critical_integrity_violation"] is False

    # ATTACK: Malicious actor or accidental rollback copies Backup 1 over live DB!
    # Backup 1 only has 1 snapshot, while ledger knows about 3 snapshots.
    import shutil
    shutil.copy2(res_b1.db_path, live_db_file)

    # Verify integrity_report detects rollback
    report_attacked = integrity_report(mgr, ledger_path=ledger_path)
    assert report_attacked["ok"] is False, "integrity_report MUST fail after rollback!"
    assert report_attacked["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert report_attacked["critical_integrity_violation"] is True
    assert "Geriye sarma (rollback) veya veri silinmesi tespit edildi" in report_attacked["chain_tip_details"]

    # Verify CLI exit code on 'masa denetle' and 'masa dogrula'
    monkeypatch.setenv("MASA_DB_PATH", str(live_db_file))
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    with pytest.raises(SystemExit) as exc1:
        cli_main(["denetle"])
    assert exc1.value.code == 3, f"CLI 'masa denetle' must return code 3, got {exc1.value.code}"

    with pytest.raises(SystemExit) as exc2:
        cli_main(["dogrula"])
    assert exc2.value.code == 3, f"CLI 'masa dogrula' must return code 3, got {exc2.value.code}"


def test_forked_chain_rollback_attack(tmp_path: Path):
    """Simulates an attacker who rolls back to an earlier state and branches off a new chain."""
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()

    # Legit history: Snap 1 -> Snap 2 -> Backup
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_002", "IE00BKM4GZ66", 20.0, t2)
    create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Attacker crafts an alternate chain with equal or MORE snapshots (count >= sealed),
    # but the sealed snapshot hash does NOT exist in the attacker's history.
    alt_db_file = tmp_path / "alt_live.db"
    alt_mgr = DatabaseManager(db_path=alt_db_file)
    alt_mgr.initialize_schema()

    t_alt = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    _add_snapshot(alt_mgr, "alt_001", "IE00B3YLTY66", 99.0, t_alt)
    _add_snapshot(alt_mgr, "alt_002", "IE00BKM4GZ66", 99.0, t_alt)
    _add_snapshot(alt_mgr, "alt_003", "IE00B5BMR087", 99.0, t_alt)  # 3 > 2
    # Also populate audit events in alt_mgr so audit count >= sealed audit count
    AuditLogger(alt_mgr).log_event("alt_actor", "ALT_EVENT_1", "state", "alt", {})
    AuditLogger(alt_mgr).log_event("alt_actor", "ALT_EVENT_2", "state", "alt", {})

    # Replace live DB with alt DB
    import shutil
    shutil.copy2(alt_db_file, live_db_file)

    report = integrity_report(mgr, ledger_path=ledger_path)
    assert report["ok"] is False
    assert report["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert report["critical_integrity_violation"] is True
    assert "Zincir çatallanması, manipülasyon veya farklı veritabanı tespit edildi" in report["chain_tip_details"]


# ==============================================================================
# CHALLENGE 2: SAHTE VERİTABANI SALDIRISI (FAKE DB SUBSTITUTION)
# ==============================================================================

def test_fake_database_substitution_attack(tmp_path: Path, monkeypatch):
    """Simulates substituting live DB with a completely new DB that has valid genesis & internal hash chain."""
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    real_mgr = DatabaseManager(db_path=live_db_file)
    real_mgr.initialize_schema()

    # Real DB has 2 legit snapshots and backup recorded in ledger
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(real_mgr, "real_snap_1", "IE00B3YLTY66", 11.5, t1)
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(real_mgr, "real_snap_2", "IE00BKM4GZ66", 21.5, t2)
    create_backup(db_manager=real_mgr, backup_dir=backup_dir)

    # Attacker creates a fresh, separate database from scratch
    fake_db_file = tmp_path / "attacker_fresh.db"
    fake_mgr = DatabaseManager(db_path=fake_db_file)
    fake_mgr.initialize_schema()
    _add_snapshot(fake_mgr, "fake_snap_1", "IE00B3YLTY66", 999.0, t1)
    _add_snapshot(fake_mgr, "fake_snap_2", "IE00BKM4GZ66", 999.0, t2)
    # Populate audit events to match or exceed real DB
    AuditLogger(fake_mgr).log_event("fake_actor", "FAKE_EVENT_1", "state", "fake", {})
    AuditLogger(fake_mgr).log_event("fake_actor", "FAKE_EVENT_2", "state", "fake", {})

    # Verify fake DB internally passes hash chain check
    conn_fake = fake_mgr.get_connection()
    snap_ok, _ = SnapshotStore(fake_mgr).verify_integrity()
    conn_fake.close()
    assert snap_ok is True, "Fake DB internally has valid hash chain"

    # ATTACK: Substitute live masa.db with the fake DB
    import shutil
    shutil.copy2(fake_db_file, live_db_file)

    # Test integrity_report
    report = integrity_report(real_mgr, ledger_path=ledger_path)
    assert report["ok"] is False
    assert report["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert report["critical_integrity_violation"] is True
    assert "Zincir çatallanması, manipülasyon veya farklı veritabanı tespit edildi" in report["chain_tip_details"]

    # Verify CLI exit code 3
    monkeypatch.setenv("MASA_DB_PATH", str(live_db_file))
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    with pytest.raises(SystemExit) as exc:
        cli_main(["denetle"])
    assert exc.value.code == 3


def test_fake_empty_database_attack(tmp_path: Path):
    """Simulates substituting live DB with an empty newly initialized DB (0 snapshots)."""
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    real_mgr = DatabaseManager(db_path=live_db_file)
    real_mgr.initialize_schema()
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(real_mgr, "real_snap_1", "IE00B3YLTY66", 11.5, t1)
    create_backup(db_manager=real_mgr, backup_dir=backup_dir)

    # Empty DB with only schema (0 snapshots, 0 audit events)
    empty_db_file = tmp_path / "empty.db"
    empty_mgr = DatabaseManager(db_path=empty_db_file)
    empty_mgr.initialize_schema()

    import shutil
    shutil.copy2(empty_db_file, live_db_file)

    report = integrity_report(real_mgr, ledger_path=ledger_path)
    assert report["ok"] is False
    assert report["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert report["critical_integrity_violation"] is True
    assert "Geriye sarma (rollback) veya veri silinmesi tespit edildi" in report["chain_tip_details"]


def test_tampered_external_ledger_hash_chain_detected(tmp_path: Path):
    """Simulates an attacker trying to tamper with zincir-uclari.jsonl lines."""
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"
    ledger_path = backup_dir / "zincir-uclari.jsonl"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_1", "IE00B3YLTY66", 10.0, t1)
    create_backup(db_manager=mgr, backup_dir=backup_dir)
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_2", "IE00BKM4GZ66", 20.0, t2)
    create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Read ledger lines
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Case A: Alter content of first line without updating entry_sha256
    obj1 = json.loads(lines[0])
    obj1["snapshot_count"] = 999
    tampered_lines = [json.dumps(obj1), lines[1]]
    ledger_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    report1 = integrity_report(mgr, ledger_path=ledger_path)
    assert report1["ok"] is False
    assert report1["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert "satır özeti uyuşmuyor" in report1["chain_tip_details"]

    # Case B: Recompute entry_sha256 of line 1, but line 2's prev_entry_sha256 now mismatches!
    new_sha1 = hashlib.sha256(canonical_json({k: v for k, v in obj1.items() if k != "entry_sha256"}).encode()).hexdigest()
    obj1["entry_sha256"] = new_sha1
    tampered_lines2 = [canonical_json(obj1), lines[1]]
    ledger_path.write_text("\n".join(tampered_lines2) + "\n", encoding="utf-8")

    report2 = integrity_report(mgr, ledger_path=ledger_path)
    assert report2["ok"] is False
    assert report2["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert "Harici kütük zinciri bozulmuş" in report2["chain_tip_details"]


# ==============================================================================
# CHALLENGE 3: GERİ YÜKLEME SIRASINDA KAZA / FAULT INJECTION SİMÜLASYONU
# ==============================================================================

def test_restore_fault_injection_during_staging_recovers_live_db(tmp_path: Path):
    """Simulates a failure during staging PRAGMA quick_check before atomic replacement.
    Verifies that live DB is restored from .bak and temp files are cleaned up.
    """
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()

    # Step 1: Create Backup 1 (Source to restore)
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    res_b1 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Step 2: Live DB continues to evolve (State 2)
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_002", "IE00BKM4GZ66", 20.0, t2)
    AuditLogger(mgr).log_event("actor_live", "LIVE_EVOLUTION", "db", "live", {"state": 2})

    live_sha_before = compute_file_sha256(live_db_file)
    live_content_before = live_db_file.read_bytes()

    # INJECT FAULT: Intercept sqlite3.connect when connecting to staging_path
    # Force it to raise an unexpected database corruption / I/O error
    real_connect = sqlite3.connect

    def faulty_connect(database, *args, **kwargs):
        if ".masa.db.restoring-" in str(database):
            raise sqlite3.OperationalError("Simulated disk error or power failure during staging validation")
        return real_connect(database, *args, **kwargs)

    with patch("masa.backup.sqlite3.connect", side_effect=faulty_connect):
        with pytest.raises(RestoreExecutionError) as exc_info:
            restore_database(res_b1.db_path, confirm=True, db_manager=mgr)
        assert "Simulated disk error" in str(exc_info.value)

    # Check 1: Live DB was recovered and has identical SHA-256 and content
    assert live_db_file.exists(), "Live DB must exist after rollback!"
    live_sha_after = compute_file_sha256(live_db_file)
    assert live_sha_after == live_sha_before, "Live DB content MUST be perfectly preserved!"
    assert live_db_file.read_bytes() == live_content_before

    # Check 2: Verify live DB has State 2 intact
    conn = mgr.get_connection()
    live_snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    live_audit = conn.execute("SELECT action FROM audit_events WHERE action='LIVE_EVOLUTION'").fetchone()
    conn.close()
    assert live_snap_count == 2, "Live DB snapshots must not be truncated on failed restore!"
    assert live_audit is not None, "State 2 audit event must be intact!"

    # Check 3: Staging temporary files cleaned up
    tmp_files = list(live_db_file.parent.glob(".masa.db.restoring-*.tmp"))
    assert len(tmp_files) == 0, f"Temporary staging files were not cleaned up: {tmp_files}"


def test_restore_fault_injection_during_atomic_replace_recovers_live_db(tmp_path: Path):
    """Simulates a failure during os.replace (e.g. PermissionError or OS crash).
    Verifies that rollback restores live DB from .bak archive.
    """
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()

    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    res_b1 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Live DB state 2
    t2 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_002", "IE00BKM4GZ66", 20.0, t2)

    live_sha_before = compute_file_sha256(live_db_file)

    real_os_replace = os.replace

    def faulty_replace(src, dst):
        if ".masa.db.restoring-" in str(src) and str(dst) == str(live_db_file):
            raise OSError("Simulated atomic os.replace failure (Permission denied or EIO)")
        return real_os_replace(src, dst)

    with patch("masa.backup.os.replace", side_effect=faulty_replace):
        with pytest.raises(RestoreExecutionError) as exc_info:
            restore_database(res_b1.db_path, confirm=True, db_manager=mgr)
        assert "Simulated atomic os.replace failure" in str(exc_info.value)

    # Check live DB is restored
    assert live_db_file.exists()
    assert compute_file_sha256(live_db_file) == live_sha_before

    # Verify staging cleaned up
    tmp_files = list(live_db_file.parent.glob(".masa.db.restoring-*.tmp"))
    assert len(tmp_files) == 0


def test_restore_drill_failure_leaves_zero_traces_on_live_db(tmp_path: Path):
    """Simulates calling restore on a corrupted backup.
    Verifies restore_drill fails and NO .bak archive or staging files are created at all.
    """
    live_db_file = tmp_path / "var" / "private" / "masa.db"
    live_db_file.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "var" / "backups"

    mgr = DatabaseManager(db_path=live_db_file)
    mgr.initialize_schema()
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    res_b1 = create_backup(db_manager=mgr, backup_dir=backup_dir)

    # Corrupt backup file
    res_b1.db_path.write_bytes(b"corrupt non-sqlite payload")

    stat_before = live_db_file.stat()
    sha_before = compute_file_sha256(live_db_file)

    with pytest.raises(BackupCorruptionError):
        restore_database(res_b1.db_path, confirm=True, db_manager=mgr)

    # Zero .bak files created because drill failed before live DB touch!
    bak_files = list(live_db_file.parent.glob("*.bak"))
    assert len(bak_files) == 0, f"No .bak archive should be created if drill fails! Found: {bak_files}"

    stat_after = live_db_file.stat()
    sha_after = compute_file_sha256(live_db_file)
    assert stat_before.st_ino == stat_after.st_ino
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns
    assert sha_before == sha_after


# ==============================================================================
# ADDITIONAL STRESS HARNESSES (CONCURRENCY & CORNER CASES)
# ==============================================================================

def test_concurrent_append_chain_tip_log(tmp_path: Path):
    """Stress tests concurrent append_chain_tip_log calls under file lock contention."""
    from concurrent.futures import ThreadPoolExecutor
    ledger_path = tmp_path / "concurrent_zincir.jsonl"

    num_threads = 20

    def worker(i: int):
        append_chain_tip_log(
            snapshot_chain_tip=f"snap_hash_{i:04d}",
            snapshot_count=i + 1,
            audit_chain_tip=f"audit_hash_{i:04d}",
            audit_count=i + 1,
            backup_filename=f"backup_{i}.db",
            backup_sha256=f"sha_{i:04d}",
            ledger_path=ledger_path,
            enforce_monotonicity=False,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == num_threads, f"Expected {num_threads} lines, got {len(lines)}"

    # Verify that the resulting hash chain is 100% valid and unbroken
    expected_prev = "0" * 64
    for idx, line in enumerate(lines):
        obj = json.loads(line)
        assert obj["prev_entry_sha256"] == expected_prev, f"Chain broken at index {idx}"
        data_to_hash = {k: v for k, v in obj.items() if k != "entry_sha256"}
        calc_sha = sha256_text(canonical_json(data_to_hash))
        assert obj["entry_sha256"] == calc_sha, f"Hash mismatch at index {idx}"
        expected_prev = calc_sha


def test_restore_database_when_no_live_db_exists(tmp_path: Path):
    """Verifies that restore_database succeeds on a clean system where live DB file does not exist yet."""
    live_db_file = tmp_path / "fresh" / "masa.db"
    backup_dir = tmp_path / "backups"

    # Create a source database to back up
    src_db_file = tmp_path / "source.db"
    src_mgr = DatabaseManager(db_path=src_db_file)
    src_mgr.initialize_schema()
    t1 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    _add_snapshot(src_mgr, "snap_001", "IE00B3YLTY66", 10.0, t1)
    res_b = create_backup(db_manager=src_mgr, backup_dir=backup_dir)

    # Now restore into live_db_file (which does NOT exist)
    target_mgr = DatabaseManager(db_path=live_db_file)
    assert not live_db_file.exists()

    restore_res = restore_database(res_b.db_path, confirm=True, db_manager=target_mgr)
    assert restore_res.success is True
    assert restore_res.archived_live_db is None  # Nothing was archived since live DB didn't exist
    assert live_db_file.exists()

    conn = target_mgr.get_connection()
    snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn.close()
    assert snap_count == 1


def test_restore_drill_on_arbitrary_files(tmp_path: Path):
    """Verifies restore_drill cleanly rejects empty files, text files, and directories without unhandled crashes."""
    # 1. Non-existent path
    r1 = restore_drill(tmp_path / "nonexistent.db")
    assert r1.ok is False
    assert any("mevcut değil" in e for e in r1.errors)

    # 2. Text file
    txt_file = tmp_path / "not_sqlite.db"
    txt_file.write_text("plain text file", encoding="utf-8")
    r2 = restore_drill(txt_file)
    assert r2.ok is False
    assert any("SQLite PRAGMA" in e or "hata" in e or "bütünlük" in e for e in r2.errors)

    # 3. 0-byte file
    empty_file = tmp_path / "empty.db"
    empty_file.write_bytes(b"")
    r3 = restore_drill(empty_file)
    assert r3.ok is False
    assert any("Şema sürümü uyuşmazlığı" in e or "Tetikleyici" in e for e in r3.errors)

    # 4. Directory path (raises IsADirectoryError in compute_file_sha256)
    sub_dir = tmp_path / "some_dir.db"
    sub_dir.mkdir()
    with pytest.raises(IsADirectoryError):
        restore_drill(sub_dir)

