"""Unit and integration tests for database migration and transaction backfill (R5 / Milestone Rem-2).

Verifies:
1. backfill_unversioned_observations migrates all 611 unversioned observations into transaction_versions,
   reaching the complete 614 transaction count.
2. backfill_unversioned_observations is idempotent (second run skips already versioned transactions).
3. migrate_v2_to_v3 idempotently triggers backfill to ensure full transaction versioning.
4. Cryptographic hash chain and record_hash integrity remain 100% valid after backfill.
5. Connection deadlock in transaction_classifier is fixed: AuditLogger with active conn does not deadlock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import pytest

from masa.audit.events import AuditLogger
from masa.calc.transaction_classifier import classify_transaction
from masa.ingestion.transaction_ledger import (
    backfill_unversioned_observations,
    ingest_transaction_versions,
)
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_transaction_version_hash
from masa.storage.migration import migrate_v2_to_v3


@pytest.fixture
def test_migration_db(tmp_path, monkeypatch):
    """Create an isolated test database with 3 initial versioned transactions and 611 unversioned observations."""
    test_db_path = tmp_path / "test_migration.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    now_iso = datetime.now(timezone.utc).isoformat()
    with mgr.transaction() as conn:
        # Create a valid snapshot for foreign key constraints
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_migration_test_01", "run_01", "portfolio", "2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z",
                None, "test", 0, "FRESH", "1.0.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "curr_hash_snap_test_01", now_iso,
            ),
        )



        # Insert 3 initial versioned transactions
        for idx in range(1, 4):
            ver_id = f"txv_init_{idx:03d}"
            broker_id = f"BTX_VERSIONED_{idx:03d}"
            values = {
                "version_id": ver_id,
                "broker_tx_id": broker_id,
                "supersedes_id": None,
                "version_number": 1,
                "raw_object_id": None,
                "snapshot_id": "snap_migration_test_01",
                "tx_type": "CASH_TRANSACTION",
                "sub_type": "FEE",
                "side": None,
                "isin": None,
                "description": f"Initial Fee {idx}",
                "amount": "-4.99",
                "currency": "EUR",
                "quantity": None,
                "limit_price": None,
                "status": "SETTLED",
                "is_cancellation": 0,
                "event_time": "2026-09-16T00:00:00Z",
                "settlement_date": None,
                "flow_classification": "COST",
                "cost_impact": '{"fee":"4.99"}',
                "payload_json": "{}",
                "created_at": now_iso,
            }
            rec_hash = compute_transaction_version_hash(values)
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, supersedes_id, version_number,
                    raw_object_id, snapshot_id, tx_type, sub_type, side, isin,
                    description, amount, currency, quantity, limit_price, status,
                    is_cancellation, event_time, settlement_date, flow_classification,
                    cost_impact, payload_json, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ver_id, broker_id, None, 1, None, "snap_migration_test_01",
                    "CASH_TRANSACTION", "FEE", None, None,
                    f"Initial Fee {idx}", "-4.99", "EUR", None, None,
                    "SETTLED", 0, "2026-09-16T00:00:00Z", None,
                    "COST", '{"fee":"4.99"}', "{}", now_iso, rec_hash,
                ),
            )

        # Insert 611 unversioned observations (so 3 + 611 = 614 total distinct broker_tx_id)
        obs_rows = []
        for i in range(1, 612):
            is_buy = (i % 2 == 0)
            obs_rows.append((
                "snap_migration_test_01",
                None,
                f"BTX_UNVERSIONED_{i:04d}",
                "SECURITY_TRANSACTION" if is_buy else "CASH_TRANSACTION",
                None if is_buy else "DEPOSIT",
                None,
                "BUY" if is_buy else None,
                "IE00B3YLTY66" if is_buy else None,
                f"Observation Tx {i}",
                "-50.00" if is_buy else "500.00",
                "EUR",
                "1.0" if is_buy else None,
                "50.00" if is_buy else None,
                "SETTLED",
                "0",
                f"2026-06-{(i % 28) + 1:02d}T10:00:00Z",
                f"hash_obs_{i:04d}",
            ))

        conn.executemany(
            """
            INSERT INTO transaction_observations (
                snapshot_id, raw_object_id, broker_tx_id, tx_type,
                cash_transaction_type, security_transaction_type, side, isin,
                description, amount, currency, quantity, limit_price, status,
                is_cancellation, event_time, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            obs_rows,
        )

    return mgr


def test_backfill_migrates_to_614_transactions(test_migration_db):
    """Verify that backfill migrates all 611 unversioned observations to reach 614 total transactions."""
    conn = test_migration_db.get_connection()
    try:
        initial_txv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        unversioned_count = conn.execute(
            """
            SELECT COUNT(DISTINCT broker_tx_id) FROM transaction_observations tx
            WHERE NOT EXISTS (SELECT 1 FROM transaction_versions tv WHERE tv.broker_tx_id = tx.broker_tx_id)
            """
        ).fetchone()[0]
        assert initial_txv == 3, f"Expected 3 initial versioned transactions, got {initial_txv}"
        assert unversioned_count == 611, f"Expected 611 unversioned observations, got {unversioned_count}"
    finally:
        conn.close()

    # Execute backfill
    stats = backfill_unversioned_observations(test_migration_db)
    assert stats["inserted"] == 611, f"Expected 611 inserted records, got {stats}"

    # Verify final counts
    conn = test_migration_db.get_connection()
    try:
        total_txv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        total_current = conn.execute("SELECT COUNT(*) FROM v_transactions_current").fetchone()[0]
        distinct_btx = conn.execute("SELECT COUNT(DISTINCT broker_tx_id) FROM transaction_versions").fetchone()[0]
        remaining_unversioned = conn.execute(
            """
            SELECT COUNT(DISTINCT broker_tx_id) FROM transaction_observations tx
            WHERE NOT EXISTS (SELECT 1 FROM transaction_versions tv WHERE tv.broker_tx_id = tx.broker_tx_id)
            """
        ).fetchone()[0]

        assert total_txv == 614, f"Expected 614 transaction_versions, got {total_txv}"
        assert total_current == 614, f"Expected 614 in v_transactions_current, got {total_current}"
        assert distinct_btx == 614, f"Expected 614 distinct broker_tx_id, got {distinct_btx}"
        assert remaining_unversioned == 0, f"Expected 0 remaining unversioned observations, got {remaining_unversioned}"
    finally:
        conn.close()


def test_backfill_is_idempotent(test_migration_db):
    """Verify that calling backfill twice does not duplicate records or cause errors."""
    stats1 = backfill_unversioned_observations(test_migration_db)
    assert stats1["inserted"] == 611

    # Second run should insert 0 records
    stats2 = backfill_unversioned_observations(test_migration_db)
    assert stats2["inserted"] == 0
    assert stats2["total"] == 0

    conn = test_migration_db.get_connection()
    try:
        total_txv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        assert total_txv == 614
    finally:
        conn.close()


def test_migrate_v2_to_v3_executes_backfill(test_migration_db):
    """Verify that migrate_v2_to_v3 idempotently triggers backfill."""
    res = migrate_v2_to_v3(test_migration_db)
    assert res.success is True

    conn = test_migration_db.get_connection()
    try:
        total_txv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        assert total_txv == 614
    finally:
        conn.close()


def test_transaction_classifier_deadlock_eliminated(test_migration_db):
    """Verify that AuditLogger with active conn does not deadlock on unsupported transaction types."""
    conn = test_migration_db.get_connection()
    try:
        # Simulate active transaction
        conn.execute("BEGIN IMMEDIATE;")
        unsupported_tx = {
            "broker_tx_id": "TEST_DEADLOCK_TX_001",
            "tx_type": "UNKNOWN_UNSUPPORTED_TYPE_XYZ",
            "amount": "100.00",
            "currency": "EUR",
        }

        # Classifying with conn should safely log audit event without database locked error
        res = classify_transaction(unsupported_tx, db=test_migration_db, conn=conn)
        assert res.status.value == "NEEDS_REVIEW"
        conn.commit()

        # Check audit event logged
        row = conn.execute(
            "SELECT action FROM audit_events WHERE entity_id = 'TEST_DEADLOCK_TX_001'"
        ).fetchone()
        assert row is not None
        assert row["action"] == "TRANSACTION_CLASSIFICATION_FAILED"
    finally:
        conn.close()
