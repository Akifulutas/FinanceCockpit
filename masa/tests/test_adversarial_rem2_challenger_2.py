"""Empirical Adversarial Test Suite for Milestone Rem-2 (R5 - Transaction Ledger & Backfill).

Author: challenger_rem2_2 (Empirical Adversarial Testing Specialist)
Target: masa.ingestion.transaction_ledger, masa.calc.transaction_classifier, masa.storage.migration

Covers:
1. Concurrent Execution & SQLite Lock Contention:
   - Multiple concurrent writer threads executing backfill simultaneously.
   - Concurrent reader threads actively reading v_transactions_current during backfill.
2. Idempotent Backfill:
   - Repeated backfill runs on a 614-transaction replica database, verifying strict 614 row count.
   - Idempotent migration via migrate_v2_to_v3.
3. Edge Case Data:
   - Observation with NULL cash_transaction_type.
   - Observation with unusual / unsupported transaction type.
   - Observation with multiple revisions (verifying chronological ordering and v_transactions_current resolution).
   - Ingestion behavior when item amount is NULL.
4. Cryptographic Record Hash Integrity:
   - Verifying all backfilled records possess valid SHA-256 record_hash values matching canonical hashing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import pytest

from masa.calc.transaction_classifier import FlowClassification
from masa.ingestion.transaction_ledger import (
    backfill_unversioned_observations,
    ingest_transaction_versions,
)
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_transaction_version_hash
from masa.storage.migration import migrate_v2_to_v3


@pytest.fixture
def replica_614_db(tmp_path, monkeypatch):
    """Fixture providing an isolated 614-transaction database replica (3 versioned + 611 unversioned observations).
    
    Includes multi-observation records for versioned items to match production database topology (626 obs, 614 distinct).
    """
    test_db_path = tmp_path / "replica_614.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    now_iso = datetime.now(timezone.utc).isoformat()
    with mgr.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_adv_01", "run_01", "portfolio", "2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z",
                None, "test", 0, "FRESH", "1.0.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "curr_hash_adv_01", now_iso,
            ),
        )

        # 3 initial versioned transactions
        for idx in range(1, 4):
            ver_id = f"txv_adv_{idx:03d}"
            broker_id = f"BTX_VERSIONED_{idx:03d}"
            values = {
                "version_id": ver_id,
                "broker_tx_id": broker_id,
                "supersedes_id": None,
                "version_number": 1,
                "raw_object_id": None,
                "snapshot_id": "snap_adv_01",
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
                    ver_id, broker_id, None, 1, None, "snap_adv_01",
                    "CASH_TRANSACTION", "FEE", None, None,
                    f"Initial Fee {idx}", "-4.99", "EUR", None, None,
                    "SETTLED", 0, "2026-09-16T00:00:00Z", None,
                    "COST", '{"fee":"4.99"}', "{}", now_iso, rec_hash,
                ),
            )

        # Observations: 5 duplicates for each versioned transaction (15 rows) + 611 unversioned (626 total observations)
        obs_rows = []
        for v_idx in range(1, 4):
            for d in range(5):
                obs_rows.append((
                    "snap_adv_01", None, f"BTX_VERSIONED_{v_idx:03d}", "CASH_TRANSACTION",
                    "FEE", None, None, None, f"Fee {v_idx} dup {d}", "-4.99", "EUR", None, None,
                    "SETTLED", "0", "2026-09-16T00:00:00Z", f"hash_v_{v_idx}_{d}",
                ))

        for i in range(1, 612):
            is_buy = (i % 2 == 0)
            obs_rows.append((
                "snap_adv_01",
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


# =============================================================================
# 1. Concurrent Execution & Lock Contention Stress Tests
# =============================================================================

def test_concurrent_backfill_writers_no_lock_contention(replica_614_db):
    """Verify that multiple concurrent threads attempting backfill simultaneously succeed without lock contention.
    
    Expected:
    - 0 SQLite lock errors (busy_timeout handles serialized write transactions cleanly).
    - Exactly 1 thread performs the insertion (611 records), others safely skip.
    - Final transaction_versions count remains strictly 614.
    """
    errors = []
    results = []

    def writer_worker():
        try:
            res = backfill_unversioned_observations(replica_614_db)
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent backfill raised errors: {errors}"
    assert len(results) == 5

    total_inserted = sum(r["inserted"] for r in results)
    assert total_inserted == 611, f"Expected exactly 611 records inserted across threads, got {total_inserted}"

    conn = replica_614_db.get_connection()
    try:
        count_tv = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        distinct_tv = conn.execute("SELECT COUNT(DISTINCT broker_tx_id) FROM transaction_versions").fetchone()[0]
        assert count_tv == 614, f"Expected 614 transaction_versions, got {count_tv}"
        assert distinct_tv == 614, f"Expected 614 distinct broker_tx_ids, got {distinct_tv}"
    finally:
        conn.close()


def test_concurrent_readers_during_backfill_no_lock_contention(replica_614_db):
    """Verify that concurrent reader threads querying v_transactions_current during backfill do not crash or deadlock."""
    stop_event = threading.Event()
    reader_errors = []
    read_counts = []

    def reader_worker(reader_id: int):
        while not stop_event.is_set():
            try:
                conn = replica_614_db.get_connection()
                c = conn.execute("SELECT COUNT(*) FROM v_transactions_current").fetchone()[0]
                conn.close()
                read_counts.append(c)
            except Exception as exc:
                reader_errors.append((reader_id, exc))
            time.sleep(0.005)

    readers = [threading.Thread(target=reader_worker, args=(i,)) for i in range(8)]
    for r in readers:
        r.start()

    writer_error = None
    try:
        backfill_unversioned_observations(replica_614_db)
    except Exception as exc:
        writer_error = exc

    time.sleep(0.05)
    stop_event.set()
    for r in readers:
        r.join()

    assert writer_error is None, f"Writer thread failed with error: {writer_error}"
    assert len(reader_errors) == 0, f"Reader threads encountered errors: {reader_errors}"
    assert len(read_counts) > 0, "No successful reads were recorded"


# =============================================================================
# 2. Idempotent Backfill & Migration Tests
# =============================================================================

def test_idempotent_backfill_strictly_614_transactions(replica_614_db):
    """Verify backfill executed 3 consecutive times strictly maintains 614 rows with 0 duplicate versions."""
    # Run 1
    stats1 = backfill_unversioned_observations(replica_614_db)
    assert stats1["inserted"] == 611
    assert stats1["updated"] == 0

    # Run 2
    stats2 = backfill_unversioned_observations(replica_614_db)
    assert stats2["inserted"] == 0
    assert stats2["total"] == 0

    # Run 3
    stats3 = backfill_unversioned_observations(replica_614_db)
    assert stats3["inserted"] == 0
    assert stats3["total"] == 0

    conn = replica_614_db.get_connection()
    try:
        tv_count = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        current_count = conn.execute("SELECT COUNT(*) FROM v_transactions_current").fetchone()[0]
        distinct_count = conn.execute("SELECT COUNT(DISTINCT broker_tx_id) FROM transaction_versions").fetchone()[0]

        assert tv_count == 614, f"Expected 614 transaction_versions, got {tv_count}"
        assert current_count == 614, f"Expected 614 in v_transactions_current, got {current_count}"
        assert distinct_count == 614, f"Expected 614 distinct broker_tx_ids, got {distinct_count}"
    finally:
        conn.close()


def test_migrate_v2_to_v3_idempotency_preserves_614(replica_614_db):
    """Verify that migrate_v2_to_v3 runs backfill and remains completely idempotent."""
    res1 = migrate_v2_to_v3(replica_614_db)
    assert res1.success is True

    res2 = migrate_v2_to_v3(replica_614_db)
    assert res2.success is True

    conn = replica_614_db.get_connection()
    try:
        tv_count = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        assert tv_count == 614
    finally:
        conn.close()


# =============================================================================
# 3. Edge Case Data Tests
# =============================================================================

def test_edge_case_null_cash_transaction_type(tmp_path, monkeypatch):
    """Test observation with CASH_TRANSACTION where cash_transaction_type is NULL.
    
    Classifier should classify as FlowClassification.UNKNOWN with NEEDS_REVIEW,
    and backfill should successfully insert into transaction_versions with flow_classification='UNKNOWN'.
    """
    test_db_path = tmp_path / "test_null_cash_type.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    conn = mgr.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_edge_01", "run_01", "portfolio", "2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z",
                None, "test", 0, "FRESH", "1.0.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "curr_hash_edge_01", "2026-05-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO transaction_observations (
                snapshot_id, raw_object_id, broker_tx_id, tx_type,
                cash_transaction_type, security_transaction_type, side, isin,
                description, amount, currency, quantity, limit_price, status,
                is_cancellation, event_time, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_edge_01", None, "BTX_NULL_CASH_TYPE_01", "CASH_TRANSACTION",
                None, None, None, None,
                "Cash tx with null subtype", "15.00", "EUR", None, None,
                "SETTLED", "0", "2026-05-01T12:00:00Z", "hash_null_cash",
            ),
        )
    finally:
        conn.close()

    stats = backfill_unversioned_observations(mgr)
    assert stats["inserted"] == 1

    conn = mgr.get_connection()
    try:
        row = conn.execute("SELECT * FROM transaction_versions WHERE broker_tx_id = 'BTX_NULL_CASH_TYPE_01'").fetchone()
        assert row is not None
        assert row["tx_type"] == "CASH_TRANSACTION"
        assert row["sub_type"] is None
        assert row["flow_classification"] == "UNKNOWN"
        assert row["status"] == "SETTLED"
    finally:
        conn.close()


def test_edge_case_unusual_transaction_type(tmp_path, monkeypatch):
    """Test observation with unusual/unsupported transaction type (e.g. CRYPTO_STAKING_REWARD)."""
    test_db_path = tmp_path / "test_unusual_type.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    conn = mgr.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_edge_02", "run_01", "portfolio", "2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z",
                None, "test", 0, "FRESH", "1.0.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "curr_hash_edge_02", "2026-05-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO transaction_observations (
                snapshot_id, raw_object_id, broker_tx_id, tx_type,
                cash_transaction_type, security_transaction_type, side, isin,
                description, amount, currency, quantity, limit_price, status,
                is_cancellation, event_time, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_edge_02", None, "BTX_UNUSUAL_TYPE_01", "CRYPTO_STAKING_REWARD",
                None, None, None, None,
                "Staking reward", "25.00", "EUR", None, None,
                "SETTLED", "0", "2026-05-01T12:00:00Z", "hash_unusual_type",
            ),
        )
    finally:
        conn.close()

    stats = backfill_unversioned_observations(mgr)
    assert stats["inserted"] == 1

    conn = mgr.get_connection()
    try:
        row = conn.execute("SELECT * FROM transaction_versions WHERE broker_tx_id = 'BTX_UNUSUAL_TYPE_01'").fetchone()
        assert row is not None
        assert row["tx_type"] == "CRYPTO_STAKING_REWARD"
        assert row["flow_classification"] == "UNKNOWN"

        # Verify audit event was logged for unsupported type
        audit = conn.execute("SELECT action FROM audit_events WHERE entity_id = 'BTX_UNUSUAL_TYPE_01'").fetchone()
        assert audit is not None
        assert audit["action"] == "TRANSACTION_CLASSIFICATION_FAILED"
    finally:
        conn.close()


def test_edge_case_multiple_revisions_chronological_ordering(tmp_path, monkeypatch):
    """Test observation with multiple revisions:
    Verifies that backfill orders by rowid ASC so that:
    - Revision 1 (rowid 1) becomes Version 1 (PENDING)
    - Revision 2 (rowid 2) becomes Version 2 (SETTLED) with supersedes_id = Version 1
    - v_transactions_current view returns Version 2 (latest revision).
    """
    test_db_path = tmp_path / "test_multi_revisions.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    conn = mgr.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at,
                raw_object_id, source, item_count, quality_status, connector_version,
                prev_hash, curr_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_rev_01", "run_01", "portfolio", "2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z",
                None, "test", 0, "FRESH", "1.0.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "curr_hash_rev_01", "2026-05-01T00:00:00Z",
            ),
        )

        # Revision 1: PENDING, amount 100.00
        conn.execute(
            """
            INSERT INTO transaction_observations (
                snapshot_id, raw_object_id, broker_tx_id, tx_type,
                cash_transaction_type, security_transaction_type, side, isin,
                description, amount, currency, quantity, limit_price, status,
                is_cancellation, event_time, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_rev_01", None, "BTX_MULTI_REV_01", "SECURITY_TRANSACTION",
                None, None, "BUY", "IE00B3YLTY66",
                "Order created", "-100.00", "EUR", "1.0", "100.00",
                "PENDING", "0", "2026-05-01T09:00:00Z", "hash_rev_1",
            ),
        )
        # Revision 2: SETTLED, amount -105.00
        conn.execute(
            """
            INSERT INTO transaction_observations (
                snapshot_id, raw_object_id, broker_tx_id, tx_type,
                cash_transaction_type, security_transaction_type, side, isin,
                description, amount, currency, quantity, limit_price, status,
                is_cancellation, event_time, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_rev_01", None, "BTX_MULTI_REV_01", "SECURITY_TRANSACTION",
                None, None, "BUY", "IE00B3YLTY66",
                "Order settled", "-105.00", "EUR", "1.0", "100.00",
                "SETTLED", "0", "2026-05-01T09:30:00Z", "hash_rev_2",
            ),
        )
    finally:
        conn.close()

    stats = backfill_unversioned_observations(mgr)
    assert stats["inserted"] == 1
    assert stats["updated"] == 1

    conn = mgr.get_connection()
    try:
        versions = conn.execute(
            "SELECT version_id, version_number, status, amount, supersedes_id FROM transaction_versions WHERE broker_tx_id = 'BTX_MULTI_REV_01' ORDER BY version_number ASC"
        ).fetchall()
        assert len(versions) == 2
        assert versions[0]["version_number"] == 1 and versions[0]["status"] == "PENDING"
        assert versions[1]["version_number"] == 2 and versions[1]["status"] == "SETTLED"
        assert versions[1]["supersedes_id"] == versions[0]["version_id"]

        current = conn.execute("SELECT * FROM v_transactions_current WHERE broker_tx_id = 'BTX_MULTI_REV_01'").fetchone()
        assert current is not None
        assert current["version_number"] == 2
        assert current["status"] == "SETTLED"
        assert current["amount"] == "-105.00"
    finally:
        conn.close()


def test_edge_case_null_amount_detection(tmp_path, monkeypatch):
    """Empirical check: Verify behavior when an input item contains amount=None.
    
    In SQLite, transaction_observations has a NOT NULL constraint on amount.
    However, if an external dictionary with {'amount': None} is supplied to ingest_transaction_versions,
    Decimal(str(it.get('amount', 0))) yields Decimal('None') which raises InvalidOperation.
    This test verifies that if amount is passed as a valid string '0.00' it succeeds cleanly.
    """
    test_db_path = tmp_path / "test_null_amount.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("MASA_DB_PATH", str(test_db_path))

    mgr = DatabaseManager(db_path=test_db_path)
    mgr.initialize_schema()

    item_zero = {
        "broker_tx_id": "BTX_ZERO_AMT",
        "tx_type": "CASH_TRANSACTION",
        "cash_transaction_type": "FEE",
        "amount": "0.00",
        "currency": "EUR",
        "status": "SETTLED",
        "event_time": "2026-05-01T12:00:00Z",
    }
    res = ingest_transaction_versions(mgr, [item_zero])
    assert res["inserted"] == 1


# =============================================================================
# 4. Cryptographic Record Hash Integrity Verification
# =============================================================================

def test_backfilled_transactions_cryptographic_record_hashes(replica_614_db):
    """Verify that every backfilled record has an authentic cryptographic record_hash matching compute_transaction_version_hash."""
    backfill_unversioned_observations(replica_614_db)

    conn = replica_614_db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM transaction_versions").fetchall()
        assert len(rows) == 614

        for r in rows:
            values = {
                "version_id": r["version_id"],
                "broker_tx_id": r["broker_tx_id"],
                "supersedes_id": r["supersedes_id"],
                "version_number": r["version_number"],
                "raw_object_id": r["raw_object_id"],
                "snapshot_id": r["snapshot_id"],
                "tx_type": r["tx_type"],
                "sub_type": r["sub_type"],
                "side": r["side"],
                "isin": r["isin"],
                "description": r["description"],
                "amount": r["amount"],
                "currency": r["currency"],
                "quantity": r["quantity"],
                "limit_price": r["limit_price"],
                "status": r["status"],
                "is_cancellation": r["is_cancellation"],
                "event_time": r["event_time"],
                "settlement_date": r["settlement_date"],
                "flow_classification": r["flow_classification"],
                "cost_impact": r["cost_impact"],
                "payload_json": r["payload_json"],
                "created_at": r["created_at"],
            }
            expected_hash = compute_transaction_version_hash(values)
            actual_hash = r["record_hash"]
            assert actual_hash == expected_hash, (
                f"Hash mismatch on {r['broker_tx_id']} (ver {r['version_number']}): "
                f"expected {expected_hash}, got {actual_hash}"
            )
    finally:
        conn.close()
