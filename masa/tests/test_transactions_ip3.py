"""Comprehensive tests for IP-3: Transaction ledger, 7-day overlapping incremental fetch,
deduplication, versioning, flow/cost classification, and immutability.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
import pytest

from masa.calc.transaction_classifier import (
    ClassificationStatus,
    FlowClassification,
    SUPPORTED_SCALABLE_TYPES,
    classify_transaction,
)
from masa.ingestion.models import TransactionItem
from masa.ingestion.sc_reader import ScalableReader, ScalableSecurityViolation
from masa.ingestion.transaction_ledger import (
    calculate_incremental_from_time,
    get_current_transactions,
    ingest_transaction_versions,
)
from masa.pipeline import Pipeline, integrity_report, latest_transactions
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_transaction_version_hash


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Isolated database manager with secure temp backup dir."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    db_path = tmp_path / "test_masa.db"
    mgr = DatabaseManager(db_path=db_path)
    mgr.initialize_schema()
    return mgr


def test_schema_and_trigger_count(test_db):
    """Verify Schema v3, trigger count reaches at least 42, and IP-3 tables exist."""
    conn = test_db.get_connection()
    try:
        user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_ver == 3, f"Expected user_version 3, got {user_ver}"

        triggers = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        assert triggers >= 42, f"Expected at least 42 triggers, got {triggers}"

        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('transaction_versions', 'corporate_actions', 'reconciliations')"
            ).fetchall()
        }
        assert tables == {"transaction_versions", "corporate_actions", "reconciliations"}

        views = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view' AND name = 'v_transactions_current'"
            ).fetchall()
        }
        assert "v_transactions_current" in views
    finally:
        conn.close()


def test_transaction_versions_immutability(test_db):
    """Verify that UPDATE, DELETE, and OVERWRITE on transaction_versions are strictly aborted."""
    now_iso = datetime.now(timezone.utc).isoformat()
    values = {
        "version_id": "txv_immut_001",
        "broker_tx_id": "BTX_001",
        "supersedes_id": None,
        "version_number": 1,
        "raw_object_id": None,
        "snapshot_id": None,
        "tx_type": "BUY",
        "sub_type": None,
        "side": "BUY",
        "isin": "IE00B4L5Y983",
        "description": "Buy iShares Core",
        "amount": "-500.00",
        "currency": "EUR",
        "quantity": "5.0",
        "limit_price": "100.0",
        "status": "SETTLED",
        "is_cancellation": 0,
        "event_time": now_iso,
        "settlement_date": None,
        "flow_classification": "INTERNAL_TRADE",
        "cost_impact": "{}",
        "payload_json": "{}",
        "created_at": now_iso,
    }
    rec_hash = compute_transaction_version_hash(values)

    with test_db.transaction() as conn:
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
                values["version_id"], values["broker_tx_id"], values["supersedes_id"],
                values["version_number"], values["raw_object_id"], values["snapshot_id"],
                values["tx_type"], values["sub_type"], values["side"], values["isin"],
                values["description"], values["amount"], values["currency"],
                values["quantity"], values["limit_price"], values["status"],
                values["is_cancellation"], values["event_time"], values["settlement_date"],
                values["flow_classification"], values["cost_impact"], values["payload_json"],
                values["created_at"], rec_hash,
            ),
        )

    # 1. Attempt UPDATE -> must abort
    with pytest.raises(sqlite3.IntegrityError, match="transaction_versions degistirilemez"):
        with test_db.transaction() as conn:
            conn.execute("UPDATE transaction_versions SET status = 'CANCELLED' WHERE version_id = 'txv_immut_001'")

    # 2. Attempt DELETE -> must abort
    with pytest.raises(sqlite3.IntegrityError, match="transaction_versions kaydi silinemez"):
        with test_db.transaction() as conn:
            conn.execute("DELETE FROM transaction_versions WHERE version_id = 'txv_immut_001'")

    # 3. Attempt OVERWRITE (same version_id) -> must abort
    with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, supersedes_id, version_number,
                    tx_type, amount, currency, status, is_cancellation, event_time,
                    flow_classification, payload_json, created_at, record_hash
                ) VALUES ('txv_immut_001', 'BTX_001', NULL, 1, 'BUY', '-500', 'EUR', 'SETTLED', 0, ?, 'INTERNAL_TRADE', '{}', ?, 'dummy_hash')
                """,
                (now_iso, now_iso),
            )


def test_deduplication_and_versioning_state_machine(test_db):
    """Verify new transactions insert as v1, unchanged ones are skipped, and changed ones create v2."""
    now = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    t1 = TransactionItem(
        id="TX_MULTI_01",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin="IE00B4L5Y983",
        description="First buy",
        amount=Decimal("-1000.00"),
        currency="EUR",
        quantity=Decimal("10.0"),
        limit_price=Decimal("100.0"),
        status="PENDING",
        is_cancellation=False,
        last_event_datetime=now,
    )

    # Ingestion 1: First time seeing TX_MULTI_01 -> insert v1
    st1 = ingest_transaction_versions(test_db, [t1])
    assert st1["inserted"] == 1
    assert st1["skipped"] == 0
    assert st1["updated"] == 0

    cur1 = get_current_transactions(test_db)
    assert len(cur1) == 1
    assert cur1[0]["broker_tx_id"] == "TX_MULTI_01"
    assert cur1[0]["version_number"] == 1
    assert cur1[0]["status"] == "PENDING"
    assert cur1[0]["supersedes_id"] is None
    v1_id = cur1[0]["version_id"]

    # Ingestion 2: Identical transaction received in 7-day overlap -> skipped (deduplicated)
    st2 = ingest_transaction_versions(test_db, [t1])
    assert st2["inserted"] == 0
    assert st2["skipped"] == 1
    assert st2["updated"] == 0

    # Ensure still exactly 1 row in DB
    conn = test_db.get_connection()
    try:
        total_rows = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        assert total_rows == 1
    finally:
        conn.close()

    # Ingestion 3: Status transitions from PENDING to SETTLED -> version 2 created, supersedes v1
    t1_settled = TransactionItem(
        id="TX_MULTI_01",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin="IE00B4L5Y983",
        description="First buy",
        amount=Decimal("-1000.00"),
        currency="EUR",
        quantity=Decimal("10.0"),
        limit_price=Decimal("100.0"),
        status="SETTLED",
        is_cancellation=False,
        last_event_datetime=now + timedelta(hours=2),
    )
    st3 = ingest_transaction_versions(test_db, [t1_settled])
    assert st3["updated"] == 1
    assert st3["inserted"] == 0
    assert st3["skipped"] == 0

    # Verify v_transactions_current resolves ONLY version 2
    cur2 = get_current_transactions(test_db)
    assert len(cur2) == 1
    assert cur2[0]["version_number"] == 2
    assert cur2[0]["status"] == "SETTLED"
    assert cur2[0]["supersedes_id"] == v1_id

    # Verify linear lineage: attempting to fork by inserting another child pointing to v1 must fail
    conn = test_db.get_connection()
    try:
        val_fork = {
            "version_id": "txv_fork_attempt",
            "broker_tx_id": "TX_MULTI_01",
            "supersedes_id": v1_id,  # Already superseded by v2!
            "version_number": 3,
            "raw_object_id": None,
            "snapshot_id": None,
            "tx_type": "BUY",
            "sub_type": None,
            "side": "BUY",
            "isin": "IE00B4L5Y983",
            "description": "Fork attempt",
            "amount": "-1000.00",
            "currency": "EUR",
            "quantity": "10.0",
            "limit_price": "100.0",
            "status": "CANCELLED",
            "is_cancellation": 1,
            "event_time": now.isoformat(),
            "settlement_date": None,
            "flow_classification": "INTERNAL_TRADE",
            "cost_impact": "{}",
            "payload_json": "{}",
            "created_at": now.isoformat(),
        }
        fork_hash = compute_transaction_version_hash(val_fork)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: transaction_versions.supersedes_id"):
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
                    val_fork["version_id"], val_fork["broker_tx_id"], val_fork["supersedes_id"],
                    val_fork["version_number"], val_fork["raw_object_id"], val_fork["snapshot_id"],
                    val_fork["tx_type"], val_fork["sub_type"], val_fork["side"], val_fork["isin"],
                    val_fork["description"], val_fork["amount"], val_fork["currency"],
                    val_fork["quantity"], val_fork["limit_price"], val_fork["status"],
                    val_fork["is_cancellation"], val_fork["event_time"], val_fork["settlement_date"],
                    val_fork["flow_classification"], val_fork["cost_impact"], val_fork["payload_json"],
                    val_fork["created_at"], fork_hash,
                ),
            )
    finally:
        conn.close()


def test_incremental_from_time_calculation(test_db):
    """Verify from_time is None on empty DB and max(event_time) - 7 days on populated DB."""
    conn = test_db.get_connection()
    try:
        # 1. Empty database -> None
        ft1 = calculate_incremental_from_time(conn, overlap_days=7)
        assert ft1 is None

        # 2. Add an event
        t_base = datetime(2026, 10, 25, 14, 30, 0, tzinfo=timezone.utc)
        item = TransactionItem(
            id="TX_TIME_01",
            type="DEPOSIT",
            amount=Decimal("5000.00"),
            currency="EUR",
            status="SETTLED",
            last_event_datetime=t_base,
        )
    finally:
        conn.close()

    ingest_transaction_versions(test_db, [item])

    conn2 = test_db.get_connection()
    try:
        ft2 = calculate_incremental_from_time(conn2, overlap_days=7)
        expected = (t_base - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert ft2 == expected
        assert ft2 == "2026-10-18T14:30:00Z"

        # Force full overrides calculation
        ft_full = calculate_incremental_from_time(conn2, overlap_days=7, force_full=True)
        assert ft_full is None
    finally:
        conn2.close()


def test_all_21_scalable_types_classification(test_db):
    """Verify that all 21 Scalable Capital types are classified correctly."""
    classifications_map = {
        "BUY": FlowClassification.INTERNAL_TRADE,
        "SELL": FlowClassification.INTERNAL_TRADE,
        "SAVINGS_PLAN": FlowClassification.INTERNAL_TRADE,
        "DEPOSIT": FlowClassification.EXTERNAL_INFLOW,
        "WITHDRAWAL": FlowClassification.EXTERNAL_OUTFLOW,
        "DISTRIBUTION": FlowClassification.INCOME,
        "FEE": FlowClassification.COST,
        "INTEREST": FlowClassification.INCOME,
        "TAX": FlowClassification.COST,
        "TAX_RETURN": FlowClassification.COST,
        "SWAP_IN": FlowClassification.NEUTRAL,
        "SWAP_OUT": FlowClassification.NEUTRAL,
        "TRANSFER_IN": FlowClassification.EXTERNAL_INFLOW,
        "TRANSFER_OUT": FlowClassification.EXTERNAL_OUTFLOW,
        "CURRENCY_SWITCH_BUY": FlowClassification.INTERNAL_TRADE,
        "CURRENCY_SWITCH_SELL": FlowClassification.INTERNAL_TRADE,
        "CASH_TRANSFER_IN": FlowClassification.EXTERNAL_INFLOW,
        "CASH_TRANSFER_OUT": FlowClassification.EXTERNAL_OUTFLOW,
        "POCKET_MONEY": FlowClassification.INTERNAL_TRADE,
        "REINVESTMENT": FlowClassification.INCOME,
        "REINVESTMENT_DISTRIBUTION": FlowClassification.INCOME,
        "REINVESTMENT_POCKET_MONEY": FlowClassification.INTERNAL_TRADE,
    }

    assert len(classifications_map) == 22  # 21 types + SAVINGS_PLAN
    for tx_type, expected_flow in classifications_map.items():
        res = classify_transaction({"type": tx_type, "amount": "100.00"}, db=test_db)
        assert res.status == ClassificationStatus.CLASSIFIED, f"Failed for {tx_type}"
        assert res.classification == expected_flow, f"Expected {expected_flow} for {tx_type}, got {res.classification}"


def test_unsupported_transaction_type_fails_safe(test_db):
    """Verify that unsupported transaction type marks NEEDS_REVIEW, logs audit event, and halts returns."""
    res = classify_transaction(
        {"type": "UNKNOWN_CRYPTO_TOKEN", "id": "TX_ROGUE_99", "amount": "250.00"},
        db=test_db,
    )
    assert res.status == ClassificationStatus.NEEDS_REVIEW
    assert res.classification == FlowClassification.UNKNOWN

    # Check audit log for TRANSACTION_CLASSIFICATION_FAILED
    conn = test_db.get_connection()
    try:
        ev = conn.execute(
            "SELECT action, entity_id, payload_json FROM audit_events WHERE action = 'TRANSACTION_CLASSIFICATION_FAILED'"
        ).fetchone()
        assert ev is not None
        assert ev["entity_id"] == "TX_ROGUE_99"
        payload = json.loads(ev["payload_json"])
        assert "Desteklenmeyen veya tanımlanmamış işlem tipi" in payload["reason"]
    finally:
        conn.close()

    # Now verify analytics.realized_returns halts gracefully without inventing data
    from masa.analytics import realized_returns
    bad_rows = [
        {
            "tx_row_id": "1",
            "broker_tx_id": "TX_ROGUE_99",
            "event_time": "2026-10-25T12:00:00Z",
            "status": "SETTLED",
            "is_cancellation": 0,
            "tx_type": "UNKNOWN_CRYPTO_TOKEN",
            "amount": "250.00",
            "quantity": "1.0",
        }
    ]
    ret = realized_returns(
        transactions=bad_rows,
        holdings={},
        holding_values={},
        broker_fifo={},
        cash_now=Decimal("250.00"),
        as_of=datetime.now(timezone.utc),
        series_by_isin={},
    )
    assert ret.available is False
    assert "Desteklenmeyen veya tanımlanmamış işlem tipi" in ret.reason or "İnceleme bekleyen" in ret.reason
    assert not ret.gain  # No invented numbers!


def test_sc_reader_from_time_flag_security():
    """Verify that sc_reader accepts ISO from_time and rejects command injection attempts."""
    fake_calls = []

    def mock_runner(cmd, timeout=None):
        fake_calls.append(cmd)
        return 0, json.dumps({"ok": True, "data": {"result": {"items": [], "cursor": None}}}), ""

    reader = ScalableReader(runner=mock_runner)

    # Valid datetime
    valid_dt = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    reader.get_history(from_time=valid_dt)
    assert len(fake_calls) == 1
    assert "--from-time" in fake_calls[0]
    idx = fake_calls[0].index("--from-time")
    assert fake_calls[0][idx + 1] == "2026-10-20T15:00:00Z"

    # Invalid string / injection attempt -> rejected by security validator
    with pytest.raises(ScalableSecurityViolation):
        reader.get_history(from_time="2026-10-20; rm -rf /")

    with pytest.raises(ScalableSecurityViolation):
        reader.get_history(from_time="evil_not_a_date")
