"""Tests for GFS backup retention policy, pruning, and deduplication (İP-0.6 [O3])."""

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
import sqlite3

from masa.backup import (
    create_backup,
    prune_backups,
    verify_chain_tips,
    default_ledger_path,
    BackupManifest,
    GENESIS_HASH,
    append_chain_tip_log,
)
from masa.storage.db import DatabaseManager


@pytest.fixture
def temp_backup_env(tmp_path):
    """Creates a temporary database and backup environment."""
    db_path = tmp_path / "private" / "test_masa.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    mgr = DatabaseManager(db_path=db_path)
    mgr.initialize_schema()

    return mgr, backup_dir


def test_backup_deduplication_skip(temp_backup_env):
    """When live DB is unchanged since last backup, create_backup skips duplicate generation."""
    mgr, b_dir = temp_backup_env

    # First backup
    b1 = create_backup(db_manager=mgr, backup_dir=b_dir, run_drill=True)
    assert b1.success
    assert not b1.skipped
    assert b1.db_path.exists()

    # Second backup without any changes to live DB
    b2 = create_backup(db_manager=mgr, backup_dir=b_dir, run_drill=True)
    assert b2.success
    assert b2.skipped
    assert "Değişiklik yok" in b2.message
    assert b2.db_path == b1.db_path

    # Only 1 .db file exists
    db_files = list(b_dir.glob("backup-*.db"))
    assert len(db_files) == 1


def test_backup_pruning_gfs_retention(temp_backup_env):
    """Create 40 mock backups across 60 days, prune with GFS, verify ledger monotonicity."""
    mgr, b_dir = temp_backup_env
    ledger_p = default_ledger_path(b_dir)

    now = datetime.now(timezone.utc)
    base_time = now - timedelta(days=60)

    # Generate 40 backups spread over 60 days
    created_items = []
    prev_hash = "0" * 64

    for i in range(40):
        # Spaced out dates: e.g. every 1.5 days
        item_dt = base_time + timedelta(days=i * 1.5)
        ts_str = item_dt.strftime("%Y%m%d_%H%M%S")
        db_file = b_dir / f"backup-{ts_str}.db"
        json_file = b_dir / f"backup-{ts_str}.json"

        # Dummy sqlite database file
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY);")
        conn.close()

        drill_verified = (i == 10)  # Mark an older backup (index 10) as drill-verified

        manifest_data = {
            "manifest_version": 1,
            "backup_timestamp": item_dt.isoformat(),
            "backup_filename": db_file.name,
            "backup_sha256": "a" * 64,
            "backup_bytes": 4096,
            "source_db_path": str(mgr.db_path),
            "schema_version": 3,
            "snapshot_chain_tip": "0" * 64,
            "snapshot_count": 0,
            "audit_chain_tip": "0" * 64,
            "audit_count": 0,
            "raw_object_count": 0,
            "table_counts": {},
            "integrity_status": {"drill_verified": drill_verified},
            "created_at": item_dt.isoformat(),
        }
        json_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        # Record in ledger
        entry = append_chain_tip_log(
            snapshot_chain_tip="0" * 64,
            snapshot_count=0,
            audit_chain_tip="0" * 64,
            audit_count=0,
            backup_filename=db_file.name,
            backup_sha256="a" * 64,
            event="BACKUP",
            ledger_path=ledger_p,
            enforce_monotonicity=False,
        )
        created_items.append((db_file.name, drill_verified))

    assert len(list(b_dir.glob("backup-*.db"))) == 40

    drill_verified_name = [name for name, dv in created_items if dv][0]
    latest_name = created_items[-1][0]

    # 1. Test Dry Run
    dry_res = prune_backups(
        backup_dir=b_dir,
        dry_run=True,
        confirmed=False,
        retention_daily=7,
        retention_weekly=4,
        retention_monthly=12,
        db_manager=mgr,
    )
    assert dry_res.dry_run is True
    assert dry_res.total_backups == 40
    assert dry_res.protected_latest == latest_name
    assert dry_res.protected_drill == drill_verified_name
    assert dry_res.pruned_count > 0
    assert len(list(b_dir.glob("backup-*.db"))) == 40  # Nothing deleted

    # 2. Test Confirmed Apply
    apply_res = prune_backups(
        backup_dir=b_dir,
        dry_run=False,
        confirmed=True,
        retention_daily=7,
        retention_weekly=4,
        retention_monthly=12,
        db_manager=mgr,
    )
    assert apply_res.dry_run is False
    assert apply_res.ledger_updated is True
    assert apply_res.pruned_count > 0

    # Verify pruned files are actually unlinked
    for p_name in apply_res.pruned_files:
        assert not (b_dir / p_name).exists()
        assert not (b_dir / Path(p_name).with_suffix(".json")).exists()

    # Verify kept files exist
    for k_name in apply_res.kept_files:
        assert (b_dir / k_name).exists()
        assert (b_dir / Path(k_name).with_suffix(".json")).exists()

    # Protected items MUST be in kept_files
    assert latest_name in apply_res.kept_files
    assert drill_verified_name in apply_res.kept_files

    # Verify ledger integrity and monotonicity
    conn = mgr.get_connection()
    try:
        verif = verify_chain_tips(conn, ledger_path=ledger_p)
        assert verif.status == "MATCH_SEALED"
    finally:
        conn.close()
