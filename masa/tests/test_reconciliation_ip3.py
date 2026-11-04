"""Comprehensive tests for IP-3 4-dimension reconciliation engine and immutability."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import sqlite3
import pytest

from masa.calc.reconciliation import (
    CASH_TOLERANCE,
    COST_TOLERANCE,
    SHARES_TOLERANCE,
    VALUATION_TOLERANCE,
    reconcile_ledger_with_broker,
)
from masa.ingestion.models import TransactionItem
from masa.ingestion.transaction_ledger import ingest_transaction_versions
from masa.storage.db import DatabaseManager


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


def _seed_broker_data(test_db, *, quantity="10.0000", value_eur="500.00", cost_basis="50.00", cash="500.00"):
    """Helper to seed snapshots, position observations, and cash observations."""
    with test_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_portfolio_001', 'run_001', 'portfolio', '2026-10-25T10:00:00Z',
                '2026-10-25T10:05:00Z', 'scalable', 1, 'OK', '1.0',
                'GENESIS', 'curr_hash_pos_01', '2026-10-25T10:05:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO position_observations (
                snapshot_id, isin, display_name, quantity, value_eur,
                broker_cost_basis, observed_at, record_hash
            ) VALUES (
                'snap_portfolio_001', 'IE00B4L5Y983', 'Core MSCI World',
                ?, ?, ?, '2026-10-25T10:05:00Z', 'pos_hash_01'
            )
            """,
            (quantity, value_eur, cost_basis),
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_portfolio_001', 'DE12***345', 'EUR', ?,
                ?, '2026-10-25T10:05:00Z', 'cash_hash_01'
            )
            """,
            (cash, cash),
        )


def _seed_transactions(test_db):
    """Seed standard transactions: 1000 EUR deposit + 10 shares buy @ 50 EUR (-500 EUR)."""
    t_dep = TransactionItem(
        id="tx_dep_01",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        is_cancellation=False,
        last_event_datetime=datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc),
    )
    t_buy = TransactionItem(
        id="tx_buy_01",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin="IE00B4L5Y983",
        amount=Decimal("-500.00"),
        currency="EUR",
        quantity=Decimal("10.0000"),
        status="SETTLED",
        is_cancellation=False,
        last_event_datetime=datetime(2026, 10, 25, 9, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(test_db, [t_dep, t_buy])


def test_reconciliations_immutability(test_db):
    """Verify reconciliations table immutability triggers (UPDATE/DELETE/OVERWRITE abort)."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert a valid reconciliation record
    with test_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO reconciliations (
                reconciliation_id, run_id, reconciliation_time, reconciliation_type,
                status, discrepancies_count, discrepancies_json, shares_match, cash_match,
                valuation_match, cost_basis_match, created_at, record_hash
            ) VALUES (
                'rec_test_001', 'run_001', ?, 'PORTFOLIO_FULL',
                'RECONCILED', 0, '[]', 1, 1, 1, 1, ?, 'dummy_hash'
            )
            """,
            (now_iso, now_iso),
        )

    # 1. UPDATE must fail
    with pytest.raises(sqlite3.IntegrityError, match="reconciliations degistirilemez"):
        with test_db.transaction() as conn:
            conn.execute("UPDATE reconciliations SET status = 'DISCREPANCY' WHERE reconciliation_id = 'rec_test_001'")

    # 2. DELETE must fail
    with pytest.raises(sqlite3.IntegrityError, match="reconciliations kaydi silinemez"):
        with test_db.transaction() as conn:
            conn.execute("DELETE FROM reconciliations WHERE reconciliation_id = 'rec_test_001'")

    # 3. OVERWRITE must fail
    with pytest.raises(sqlite3.IntegrityError, match="reconciliations: mevcut kaydin uzerine yazma"):
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO reconciliations (
                    reconciliation_id, run_id, reconciliation_time, reconciliation_type,
                    status, discrepancies_count, discrepancies_json, shares_match, cash_match,
                    valuation_match, cost_basis_match, created_at, record_hash
                ) VALUES (
                    'rec_test_001', 'run_001', ?, 'PORTFOLIO_FULL',
                    'DISCREPANCY', 1, '[]', 0, 0, 0, 0, ?, 'dummy_hash_overwrite'
                )
                """,
                (now_iso, now_iso),
            )


def test_reconciliation_perfect_match(test_db):
    """Verify 4-dimension reconciliation returns RECONCILED when all 4 dimensions match."""
    _seed_broker_data(test_db, quantity="10.0000", value_eur="500.00", cost_basis="50.00", cash="500.00")
    _seed_transactions(test_db)

    summary = reconcile_ledger_with_broker(test_db, run_id="test_run_reconciled")
    assert summary.status == "RECONCILED"
    assert summary.shares_match is True
    assert summary.cash_match is True
    assert summary.valuation_match is True
    assert summary.cost_basis_match is True
    assert len(summary.discrepancies) == 0
    assert summary.cash_gap_eur == Decimal("0")
    # Latency: snapshot is at 10:05:00, latest tx is at 09:30:00 -> 35 min = 2100s
    assert summary.observation_lag_seconds == 2100

    # Ensure record was sealed in DB
    conn = test_db.get_connection()
    try:
        rec_row = conn.execute("SELECT * FROM reconciliations WHERE run_id = 'test_run_reconciled'").fetchone()
        assert rec_row is not None
        assert rec_row["status"] == "RECONCILED"
        assert rec_row["shares_match"] == 1
        assert rec_row["cash_match"] == 1
        assert rec_row["valuation_match"] == 1
        assert rec_row["cost_basis_match"] == 1
        assert rec_row["record_hash"] is not None
    finally:
        conn.close()


def test_reconciliation_position_discrepancy(test_db):
    """Verify position discrepancy exceeding 0.0001 shares tolerance flags DISCREPANCY."""
    # Broker has 9.9998 shares (difference is 0.0002 shares, exceeding 0.0001)
    _seed_broker_data(test_db, quantity="9.9998", value_eur="500.00", cost_basis="50.00", cash="500.00")
    _seed_transactions(test_db)

    summary = reconcile_ledger_with_broker(test_db, run_id="test_run_pos_diff")
    assert summary.status == "DISCREPANCY"
    assert summary.shares_match is False
    assert any(d.dimension == "POSITION" and d.entity == "IE00B4L5Y983" for d in summary.discrepancies)


def test_reconciliation_cash_discrepancy_and_zero_hallucination(test_db):
    """Verify cash gap exceeding 0.01 EUR flags DISCREPANCY and records gap without hallucinating fees."""
    # Broker cash is 485.50 EUR, ledger cash is 500.00 EUR (gap is 14.50 EUR)
    _seed_broker_data(test_db, quantity="10.0000", value_eur="500.00", cost_basis="50.00", cash="485.50")
    _seed_transactions(test_db)

    summary = reconcile_ledger_with_broker(test_db, run_id="test_run_cash_diff")
    assert summary.status == "DISCREPANCY"
    assert summary.cash_match is False
    assert summary.cash_gap_eur == Decimal("14.50")

    cash_disc = [d for d in summary.discrepancies if d.dimension == "CASH"]
    assert len(cash_disc) == 1
    assert "Açık=14.50" in cash_disc[0].reason

    # Zero hallucination guarantee: confirm no synthetic transactions were injected into ledger
    conn = test_db.get_connection()
    try:
        tx_count = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
        # Only the 2 original transactions must exist
        assert tx_count == 2
    finally:
        conn.close()


def test_reconciliation_cost_basis_discrepancy(test_db):
    """Verify unit cost basis difference exceeding 0.01 EUR/share flags DISCREPANCY."""
    # Broker cost basis is 52.00, ledger cost basis is 50.00 (diff 2.00 > 0.01)
    _seed_broker_data(test_db, quantity="10.0000", value_eur="500.00", cost_basis="52.00", cash="500.00")
    _seed_transactions(test_db)

    summary = reconcile_ledger_with_broker(test_db, run_id="test_run_cost_diff")
    assert summary.status == "DISCREPANCY"
    assert summary.cost_basis_match is False
    assert any(d.dimension == "COST_BASIS" and d.entity == "IE00B4L5Y983" for d in summary.discrepancies)


def test_cli_mutabakat(test_db, monkeypatch, capsys):
    """Verify `masa mutabakat`, `--json`, and `--detay` CLI commands."""
    from masa.cli import main

    monkeypatch.setenv("MASA_DB_PATH", str(test_db.db_path))

    _seed_broker_data(test_db, quantity="10.0000", value_eur="500.00", cost_basis="50.00", cash="500.00")
    _seed_transactions(test_db)

    # 1. Standard text output
    with pytest.raises(SystemExit) as exc_std:
        main(["mutabakat"])
    assert exc_std.value.code == 0
    out_std, _ = capsys.readouterr()
    assert "RECONCILED" in out_std
    assert "MUTABAKAT BAŞARILI" in out_std

    # 2. JSON output
    with pytest.raises(SystemExit) as exc_json:
        main(["mutabakat", "--json"])
    assert exc_json.value.code == 0
    out_json, _ = capsys.readouterr()
    data = json.loads(out_json)
    assert data["status"] == "RECONCILED"
    assert data["shares_match"] is True
    assert data["cash_match"] is True

    # 3. Detailed output
    with pytest.raises(SystemExit) as exc_det:
        main(["mutabakat", "--detay"])
    assert exc_det.value.code == 0
    out_det, _ = capsys.readouterr()
    assert "RECONCILED" in out_det
    assert "MUTABAKAT BAŞARILI" in out_det
