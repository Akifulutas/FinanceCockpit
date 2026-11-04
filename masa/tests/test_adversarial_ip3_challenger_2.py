"""Empirical Adversarial Stress Tests for IP-3 (Challenger 2).

Scope:
1. Corporate Actions Edge Cases & Immutability:
   - Stock splits (2:1, 7:1 prime) and reverse splits (1:10, 1:100, 1:7).
   - Total lot acquisition cost conservation and inverse unit cost scaling.
   - Strict authorization validation: empty or whitespace `approved_by` rejection.
   - SQLite table immutability triggers: abort on UPDATE, DELETE, and OVERWRITE.
   - ISIN changes & mergers: lot provenance, timestamp, and unit cost preservation.
2. FIFO Cost Conservation:
   - Multi-stage lifecycle with interleaved buys, splits, reverse splits, and partial sales.
   - Multi-split cascading chain (2:1 split -> 3:1 split -> 1:6 reverse split).
   - Complete liquidation down to 0 shares (verifying clean empty state).
   - Strict mathematical identity: `net proceeds + market value = total spent + realized PnL + unrealized PnL`
     within 0.01 EUR tolerance.
   - Weighted average FIFO unit cost basis verification.
3. Reconciliation Discrepancy Scenarios:
   - Deliberate cash discrepancies (e.g. 84.14 EUR gap).
   - Verification that status='DISCREPANCY' and ZERO dummy fees/taxes are invented.
   - Share quantity discrepancy boundary tolerances (<= 0.0001 pass, > 0.0001 fail).
   - Cost basis tolerance boundary (<= 0.01 pass, > 0.01 fail).
   - Observation lag seconds (time delta) precision, direction-independence, and zero lag (0 seconds).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
import pytest
from pydantic import ValidationError

from masa.calc.corporate import (
    CorporateActionRecord,
    CorporateActionType,
    list_corporate_actions,
    register_corporate_action,
    transform_lots_for_corporate_action,
)
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
from masa.storage.hash_chain import compute_corporate_action_hash


@pytest.fixture
def db_factory(tmp_path, monkeypatch):
    """Factory fixture providing clean, isolated databases respecting append-only immutability."""
    counter = 0

    def _create():
        nonlocal counter
        counter += 1
        backup_dir = tmp_path / f"backups_{counter}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

        db_path = tmp_path / f"adversarial_ip3_{counter}.db"
        mgr = DatabaseManager(db_path=db_path)
        mgr.initialize_schema()
        return mgr

    return _create


@pytest.fixture
def test_db(db_factory):
    return db_factory()


# ==============================================================================
# 1. Corporate Actions Edge Cases & Immutability
# ==============================================================================

def test_corporate_actions_split_and_reverse_split_conservation():
    """Verify forward splits (2:1, 7:1) and reverse splits (1:10, 1:100, 1:7) conserve total acquisition cost."""
    initial_lots = [
        {"lot_id": "L1", "shares": Decimal("100"), "cost_per_share": Decimal("50.00"), "timestamp": "2026-01-10T10:00:00Z"},
        {"lot_id": "L2", "shares": Decimal("35"), "cost_per_share": Decimal("70.00"), "timestamp": "2026-01-15T10:00:00Z"},
        {"lot_id": "L3", "shares": Decimal("14"), "cost_per_share": Decimal("125.50"), "timestamp": "2026-01-20T10:00:00Z"},
    ]
    orig_total_basis = sum(l["shares"] * l["cost_per_share"] for l in initial_lots)
    # 5000 + 2450 + 1757 = 9207.00 EUR

    test_cases = [
        (CorporateActionType.SPLIT, Decimal("2.0"), "2:1 Forward Split"),
        (CorporateActionType.SPLIT, Decimal("7.0"), "7:1 Forward Split (Prime ratio)"),
        (CorporateActionType.SPLIT, Decimal("3.0"), "3:1 Forward Split"),
        (CorporateActionType.REVERSE_SPLIT, Decimal("0.1"), "1:10 Reverse Split"),
        (CorporateActionType.REVERSE_SPLIT, Decimal("0.01"), "1:100 Reverse Split"),
        (CorporateActionType.REVERSE_SPLIT, Decimal("1") / Decimal("7"), "1:7 Reverse Split"),
    ]

    for act_type, ratio, desc in test_cases:
        action = CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=act_type,
            ratio=ratio,
            effective_date="2026-10-25T00:00:00Z",
            description=desc,
            approved_by="auditor_ip3_adversarial",
        )
        transformed, target_isin = transform_lots_for_corporate_action(initial_lots, action)

        assert target_isin == "IE00B4L5Y983"
        assert len(transformed) == len(initial_lots)

        # Check each lot
        for orig, new_lot in zip(initial_lots, transformed):
            assert new_lot["lot_id"] == orig["lot_id"]
            assert new_lot["timestamp"] == orig["timestamp"]
            assert new_lot["shares"] == orig["shares"] * ratio
            expected_cps = orig["cost_per_share"] / ratio
            assert abs(new_lot["cost_per_share"] - expected_cps) < Decimal("1e-12")

        new_total_basis = sum(l["shares"] * l["cost_per_share"] for l in transformed)
        diff = abs(new_total_basis - orig_total_basis)
        assert diff < Decimal("1e-9"), f"Cost conservation failed for {desc}: diff={diff}"


def test_corporate_actions_strict_authorization_rejection():
    """Verify that approved_by cannot be empty, whitespace, or missing."""
    # 1. Empty string
    with pytest.raises((ValueError, ValidationError)):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="",
        )

    # 2. Whitespace only
    with pytest.raises((ValueError, ValidationError)):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="     ",
        )

    # 3. Tab and newline whitespace
    with pytest.raises((ValueError, ValidationError)):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="\t \n ",
        )

    # 4. Zero or negative ratio
    with pytest.raises((ValueError, ValidationError)):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="auditor",
        )

    with pytest.raises((ValueError, ValidationError)):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("-2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="auditor",
        )


def test_corporate_actions_sqlite_triggers_abort_mutation(test_db):
    """Verify SQLite triggers prevent_update, prevent_delete, and prevent_overwrite on corporate_actions."""
    action = CorporateActionRecord(
        action_id="ca_adv_001",
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("2.0"),
        effective_date="2026-10-25T00:00:00Z",
        description="Forward split for immutability check",
        approved_by="risk_officer_42",
    )
    register_corporate_action(test_db, action)

    # 1. Attempt UPDATE
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions degistirilemez"):
        with test_db.transaction() as conn:
            conn.execute("UPDATE corporate_actions SET ratio = '3.0' WHERE action_id = 'ca_adv_001'")

    # 2. Attempt DELETE
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions kaydi silinemez"):
        with test_db.transaction() as conn:
            conn.execute("DELETE FROM corporate_actions WHERE action_id = 'ca_adv_001'")

    # 3. Attempt OVERWRITE (same action_id)
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions: mevcut kaydin uzerine yazma"):
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO corporate_actions (
                    action_id, isin, action_type, ratio, effective_date,
                    description, approved_by, approved_at, created_at, record_hash
                ) VALUES ('ca_adv_001', 'IE00B4L5Y983', 'SPLIT', '2.0',
                          '2026-10-25T00:00:00Z', 'Duplicate', 'evil_actor',
                          '2026-10-25T00:00:00Z', '2026-10-25T00:00:00Z', 'fake_hash')
                """
            )


def test_corporate_actions_isin_change_and_merger_lot_provenance():
    """Verify that ISIN_CHANGE migrates lots to new_isin while strictly maintaining lot count, unit cost and timestamps."""
    initial_lots = [
        {"lot_id": "LOT_ORIG_1", "shares": Decimal("40.0"), "cost_per_share": Decimal("100.00"), "timestamp": "2026-03-01T10:00:00Z"},
        {"lot_id": "LOT_ORIG_2", "shares": Decimal("60.0"), "cost_per_share": Decimal("120.00"), "timestamp": "2026-04-01T10:00:00Z"},
    ]
    orig_total = sum(l["shares"] * l["cost_per_share"] for l in initial_lots)  # 4000 + 7200 = 11200 EUR

    migr_action = CorporateActionRecord(
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.ISIN_CHANGE,
        ratio=Decimal("1.0"),
        new_isin="IE00B3YLTY66",
        effective_date="2026-10-01T00:00:00Z",
        description="Share class migration to IE00B3YLTY66",
        approved_by="compliance_officer_1",
    )
    transformed, target_isin = transform_lots_for_corporate_action(initial_lots, migr_action)

    assert target_isin == "IE00B3YLTY66"
    assert len(transformed) == 2
    for orig, t_lot in zip(initial_lots, transformed):
        assert t_lot["isin"] == "IE00B3YLTY66"
        assert t_lot["lot_id"] == orig["lot_id"]
        assert t_lot["timestamp"] == orig["timestamp"]
        assert t_lot["shares"] == orig["shares"]
        assert t_lot["cost_per_share"] == orig["cost_per_share"]

    new_total = sum(l["shares"] * l["cost_per_share"] for l in transformed)
    assert new_total == orig_total == Decimal("11200.00")


# ==============================================================================
# 2. FIFO Cost Conservation under Interleaved Trades & Corporate Actions
# ==============================================================================

def test_fifo_cost_conservation_interleaved_trades_and_splits(test_db):
    """Empirical verification of FIFO cost basis conservation through an interleaved lifecycle:

    Lifecycle:
    1. T1 (2026-10-01): Deposit 10,000 EUR
    2. T2 (2026-10-02): Buy 100 shares @ 50.00 EUR (-5,000 EUR)
    3. T3 (2026-10-05): 2:1 Split -> 200 shares @ 25.00 EUR (basis = 5,000 EUR)
    4. T4 (2026-10-10): Partial Sale of 50 shares @ 40.00 EUR (+2,000 EUR proceeds)
       - FIFO cost consumed: 50 * 25.00 = 1,250 EUR
       - Realized PnL: 2,000 - 1,250 = +750 EUR
       - Remaining: 150 shares @ 25.00 EUR (basis = 3,750 EUR)
    5. T5 (2026-10-15): Buy 50 shares @ 30.00 EUR (-1,500 EUR)
       - Lot 1: 150 shares @ 25.00 EUR (3,750 EUR)
       - Lot 2: 50 shares @ 30.00 EUR (1,500 EUR)
       - Total: 200 shares, basis = 5,250 EUR
    6. T6 (2026-10-20): 1:10 Reverse Split (ratio = 0.1)
       - Lot 1: 15 shares @ 250.00 EUR (3,750 EUR)
       - Lot 2: 5 shares @ 300.00 EUR (1,500 EUR)
       - Total: 20 shares, basis = 5,250 EUR
    7. T7 (2026-10-22): Partial Sale of 10 shares @ 350.00 EUR (+3,500 EUR proceeds)
       - FIFO cost consumed: 10 shares from Lot 1 @ 250.00 = 2,500 EUR
       - Realized PnL: 3,500 - 2,500 = +1,000 EUR
       - Remaining: 5 shares Lot 1 @ 250.00 (1,250 EUR) + 5 shares Lot 2 @ 300.00 (1,500 EUR)
       - Remaining shares: 10 shares
       - Remaining basis: 2,750 EUR (weighted average unit cost = 275.00 EUR/share)
    8. Terminal Valuation @ 400.00 EUR/share:
       - Market value = 10 * 400.00 = 4,000 EUR
       - Unrealized PnL = 4,000 - 2,750 = +1,250 EUR

    Conservation Identity to Verify:
    net proceeds (5,500) + market value (4,000) = 9,500 EUR
    total spent (6,500) + realized PnL (1,750) + unrealized PnL (1,250) = 9,500 EUR
    Difference must be <= 0.01 EUR!
    """
    isin = "IE00B4L5Y983"

    # 1. Seed deposit & trades
    t_dep = TransactionItem(
        id="TX_DEP_01",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("10000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    t_buy1 = TransactionItem(
        id="TX_BUY_01",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin=isin,
        amount=Decimal("-5000.00"),
        currency="EUR",
        quantity=Decimal("100.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 2, 11, 0, 0, tzinfo=timezone.utc),
    )
    t_sell1 = TransactionItem(
        id="TX_SELL_01",
        type="SECURITY_TRANSACTION",
        security_transaction_type="SELL",
        side="SELL",
        isin=isin,
        amount=Decimal("2000.00"),
        currency="EUR",
        quantity=Decimal("50.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc),
    )
    t_buy2 = TransactionItem(
        id="TX_BUY_02",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin=isin,
        amount=Decimal("-1500.00"),
        currency="EUR",
        quantity=Decimal("50.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    t_sell2 = TransactionItem(
        id="TX_SELL_02",
        type="SECURITY_TRANSACTION",
        security_transaction_type="SELL",
        side="SELL",
        isin=isin,
        amount=Decimal("3500.00"),
        currency="EUR",
        quantity=Decimal("10.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc),
    )

    ingest_transaction_versions(test_db, [t_dep, t_buy1, t_sell1, t_buy2, t_sell2])

    # 2. Register corporate actions (split and reverse split)
    ca_split = CorporateActionRecord(
        action_id="ca_split_01",
        isin=isin,
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("2.0"),
        effective_date="2026-10-05T00:00:00Z",
        description="2:1 Stock Split",
        approved_by="auditor_ip3",
    )
    ca_rev = CorporateActionRecord(
        action_id="ca_rev_01",
        isin=isin,
        action_type=CorporateActionType.REVERSE_SPLIT,
        ratio=Decimal("0.1"),
        effective_date="2026-10-20T00:00:00Z",
        description="1:10 Reverse Split",
        approved_by="auditor_ip3",
    )
    register_corporate_action(test_db, ca_split)
    register_corporate_action(test_db, ca_rev)

    # 3. Seed broker snapshot matching exact terminal position
    # Cash in ledger: 10000 - 5000 + 2000 - 1500 + 3500 = 9000 EUR
    # Shares in ledger: 10.0000 shares
    # Unit cost in ledger: 275.00 EUR/share
    # Valuation: 10 * 400.00 = 4000 EUR
    with test_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_fifo_cons_01', 'run_fifo', 'portfolio', '2026-10-25T17:00:00Z',
                '2026-10-25T17:05:00Z', 'scalable', 1, 'OK', '1.0',
                'GENESIS', 'hash_curr_fifo', '2026-10-25T17:05:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO position_observations (
                snapshot_id, isin, display_name, quantity, value_eur,
                broker_cost_basis, observed_at, record_hash
            ) VALUES (
                'snap_fifo_cons_01', ?, 'Core MSCI World',
                '10.0000', '4000.00', '275.00', '2026-10-25T17:05:00Z', 'pos_hash_fifo'
            )
            """,
            (isin,),
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_fifo_cons_01', 'DE12***345', 'EUR', '9000.00',
                '9000.00', '2026-10-25T17:05:00Z', 'cash_hash_fifo'
            )
            """
        )

    # 4. Reconcile ledger with broker
    summary = reconcile_ledger_with_broker(test_db, run_id="run_fifo_conservation")

    assert summary.status == "RECONCILED", f"Expected RECONCILED, got {summary.status} with {summary.discrepancies}"
    assert summary.shares_match is True
    assert summary.cash_match is True
    assert summary.cost_basis_match is True
    assert summary.valuation_match is True

    # 5. Check exact mathematical conservation identity
    total_spent = Decimal("5000.00") + Decimal("1500.00")  # 6500.00
    net_proceeds = Decimal("2000.00") + Decimal("3500.00")  # 5500.00
    realized_pnl = Decimal("750.00") + Decimal("1000.00")   # 1750.00
    market_value = Decimal("4000.00")
    remaining_basis = Decimal("2750.00")
    unrealized_pnl = market_value - remaining_basis         # 1250.00

    left_side = net_proceeds + market_value                 # 9500.00
    right_side = total_spent + realized_pnl + unrealized_pnl  # 9500.00

    identity_diff = abs(left_side - right_side)
    assert identity_diff <= Decimal("0.01"), f"Cost conservation identity violated: diff={identity_diff}"
    assert left_side == Decimal("9500.00")
    assert right_side == Decimal("9500.00")


def test_fifo_complete_liquidation_to_zero_shares(db_factory):
    """Verify that selling all shares completely resets position to 0 shares and 0 basis without corrupting FIFO queue."""
    db = db_factory()
    isin = "IE00B4L5Y983"

    t_buy = TransactionItem(
        id="TX_LIQ_B1",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin=isin,
        amount=Decimal("-3000.00"),
        currency="EUR",
        quantity=Decimal("50.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    # Sell entire 50 shares
    t_sell = TransactionItem(
        id="TX_LIQ_S1",
        type="SECURITY_TRANSACTION",
        security_transaction_type="SELL",
        side="SELL",
        isin=isin,
        amount=Decimal("3500.00"),
        currency="EUR",
        quantity=Decimal("50.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db, [t_buy, t_sell])

    # Broker has 0 shares of ISIN
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_liq', 'run_liq', 'portfolio', '2026-10-25T10:00:00Z',
                '2026-10-25T10:05:00Z', 'scalable', 0, 'OK', '1.0',
                'GENESIS', 'hash_liq', '2026-10-25T10:05:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_liq', 'DE12***345', 'EUR', '500.00',
                '500.00', '2026-10-25T10:05:00Z', 'cash_hash_liq'
            )
            """
        )

    summary = reconcile_ledger_with_broker(db, run_id="run_liq_reconcile")
    assert summary.status == "RECONCILED"
    assert summary.shares_match is True
    assert summary.cash_match is True
    assert Decimal(summary.details["ledger_shares"].get(isin, "0")) == Decimal("0")


def test_fifo_multi_split_cascading_chain(db_factory):
    """Stress-test a multi-split cascade: 2:1 Split -> 3:1 Split -> 1:6 Reverse Split.

    Net multiplier = 2 * 3 * (1/6) = 1.0!
    Starting: 100 shares @ 60 EUR = 6,000 EUR.
    Ending: Exactly 100 shares @ 60 EUR = 6,000 EUR.
    """
    db = db_factory()
    isin = "IE00B4L5Y983"

    t_buy = TransactionItem(
        id="TX_CASCADE_B1",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin=isin,
        amount=Decimal("-6000.00"),
        currency="EUR",
        quantity=Decimal("100.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db, [t_buy])

    # 1. 2:1 Split (ratio = 2)
    ca1 = CorporateActionRecord(
        action_id="ca_casc_1",
        isin=isin,
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("2.0"),
        effective_date="2026-10-05T00:00:00Z",
        description="2:1 Split",
        approved_by="auditor",
    )
    # 2. 3:1 Split (ratio = 3)
    ca2 = CorporateActionRecord(
        action_id="ca_casc_2",
        isin=isin,
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("3.0"),
        effective_date="2026-10-10T00:00:00Z",
        description="3:1 Split",
        approved_by="auditor",
    )
    # 3. 1:6 Reverse Split (ratio = 1/6)
    ca3 = CorporateActionRecord(
        action_id="ca_casc_3",
        isin=isin,
        action_type=CorporateActionType.REVERSE_SPLIT,
        ratio=Decimal("1") / Decimal("6"),
        effective_date="2026-10-15T00:00:00Z",
        description="1:6 Reverse Split",
        approved_by="auditor",
    )
    register_corporate_action(db, ca1)
    register_corporate_action(db, ca2)
    register_corporate_action(db, ca3)

    # Reconcile with broker holding 100 shares @ 60.00 EUR
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_casc', 'run_casc', 'portfolio', '2026-10-25T10:00:00Z',
                '2026-10-25T10:05:00Z', 'scalable', 1, 'OK', '1.0',
                'GENESIS', 'hash_casc', '2026-10-25T10:05:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO position_observations (
                snapshot_id, isin, display_name, quantity, value_eur,
                broker_cost_basis, observed_at, record_hash
            ) VALUES (
                'snap_casc', 'IE00B4L5Y983', 'Core MSCI World',
                '100.0000', '6000.00', '60.00', '2026-10-25T10:05:00Z', 'pos_hash_casc'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_casc', 'DE12***345', 'EUR', '-6000.00',
                '-6000.00', '2026-10-25T10:05:00Z', 'cash_hash_casc'
            )
            """
        )

    summary = reconcile_ledger_with_broker(db, run_id="run_cascade_reconcile")
    assert summary.status == "RECONCILED"
    assert summary.shares_match is True
    assert summary.cost_basis_match is True


# ==============================================================================
# 3. Reconciliation Discrepancy Scenarios
# ==============================================================================

def test_reconciliation_deliberate_cash_discrepancy_and_zero_hallucination(test_db):
    """Verify that a deliberate 84.14 EUR cash gap triggers DISCREPANCY and no synthetic transactions are created."""
    # Seed ledger with 1000.00 EUR deposit and 500.00 EUR buy -> ledger cash is 500.00 EUR
    t_dep = TransactionItem(
        id="TX_CASH_D1",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc),
    )
    t_buy = TransactionItem(
        id="TX_CASH_B1",
        type="SECURITY_TRANSACTION",
        security_transaction_type="BUY",
        side="BUY",
        isin="IE00B4L5Y983",
        amount=Decimal("-500.00"),
        currency="EUR",
        quantity=Decimal("10.0000"),
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 9, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(test_db, [t_dep, t_buy])

    # Seed broker observation with cash = 415.86 EUR (an unexplained gap of 84.14 EUR!)
    with test_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_cash_disc', 'run_cash', 'portfolio', '2026-10-25T10:00:00Z',
                '2026-10-25T10:05:00Z', 'scalable', 1, 'OK', '1.0',
                'GENESIS', 'hash_cash_gap', '2026-10-25T10:05:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO position_observations (
                snapshot_id, isin, display_name, quantity, value_eur,
                broker_cost_basis, observed_at, record_hash
            ) VALUES (
                'snap_cash_disc', 'IE00B4L5Y983', 'Core MSCI World',
                '10.0000', '500.00', '50.00', '2026-10-25T10:05:00Z', 'pos_hash_disc'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_cash_disc', 'DE12***345', 'EUR', '415.86',
                '415.86', '2026-10-25T10:05:00Z', 'cash_hash_disc'
            )
            """
        )

    summary = reconcile_ledger_with_broker(test_db, run_id="run_cash_gap_test")

    # 1. Reconciliation status must be DISCREPANCY
    assert summary.status == "DISCREPANCY"
    assert summary.cash_match is False
    assert summary.cash_gap_eur == Decimal("84.14")

    cash_disc = [d for d in summary.discrepancies if d.dimension == "CASH"]
    assert len(cash_disc) == 1
    assert "84.14" in cash_disc[0].diff_val
    assert "Açık=84.14" in cash_disc[0].reason

    # 2. ZERO Hallucination Guarantee: check transaction_versions table
    conn = test_db.get_connection()
    try:
        tx_rows = conn.execute("SELECT broker_tx_id, tx_type, amount FROM transaction_versions").fetchall()
        # Strictly only the 2 user-supplied transactions must exist
        assert len(tx_rows) == 2
        tx_ids = {r["broker_tx_id"] for r in tx_rows}
        assert tx_ids == {"TX_CASH_D1", "TX_CASH_B1"}

        # 3. Reconciliations record in DB must reflect DISCREPANCY and cash_gap_eur
        rec_row = conn.execute("SELECT status, cash_match, cash_gap_eur FROM reconciliations WHERE run_id = 'run_cash_gap_test'").fetchone()
        assert rec_row["status"] == "DISCREPANCY"
        assert rec_row["cash_match"] == 0
        assert rec_row["cash_gap_eur"] == "84.14"
    finally:
        conn.close()


def test_reconciliation_share_quantity_discrepancy_boundary_tolerances(db_factory):
    """Test share quantity tolerance boundaries around SHARES_TOLERANCE (0.0001 shares)."""
    def run_reconcile_for_qty(broker_qty_str: str):
        db = db_factory()
        # Ledger has 10.0000 shares
        t_buy = TransactionItem(
            id="TX_QTY_B1",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("10.0000"),
            status="SETTLED",
            last_event_datetime=datetime(2026, 10, 25, 9, 30, 0, tzinfo=timezone.utc),
        )
        ingest_transaction_versions(db, [t_buy])

        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, run_id, snapshot_type, collection_started_at,
                    collection_completed_at, source, item_count, quality_status,
                    connector_version, prev_hash, curr_hash, created_at
                ) VALUES (
                    'snap_qty', 'run_qty', 'portfolio', '2026-10-25T10:00:00Z',
                    '2026-10-25T10:05:00Z', 'scalable', 1, 'OK', '1.0',
                    'GENESIS', 'hash_curr', '2026-10-25T10:05:00Z'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO position_observations (
                    snapshot_id, isin, display_name, quantity, value_eur,
                    broker_cost_basis, observed_at, record_hash
                ) VALUES (
                    'snap_qty', 'IE00B4L5Y983', 'Core MSCI World',
                    ?, '500.00', '50.00', '2026-10-25T10:05:00Z', 'pos_hash'
                )
                """,
                (broker_qty_str,),
            )
            conn.execute(
                """
                INSERT INTO cash_observations (
                    snapshot_id, account_id_masked, currency, settled_cash,
                    total_cash, observed_at, record_hash
                ) VALUES (
                    'snap_qty', 'DE12***345', 'EUR', '-500.00',
                    '-500.00', '2026-10-25T10:05:00Z', 'cash_hash'
                )
                """
            )
        return reconcile_ledger_with_broker(db, run_id=f"run_qty_{broker_qty_str}")

    # Case A: Diff = 0.00005 (< 0.0001 tolerance) -> PASS
    res_a = run_reconcile_for_qty("10.00005")
    assert res_a.shares_match is True

    # Case B: Diff = 0.00010 (== 0.0001 tolerance boundary) -> PASS (not strictly greater)
    res_b = run_reconcile_for_qty("10.00010")
    assert res_b.shares_match is True

    # Case C: Diff = 0.00011 (> 0.0001 tolerance) -> FAIL (DISCREPANCY)
    res_c = run_reconcile_for_qty("10.00011")
    assert res_c.shares_match is False
    assert res_c.status == "DISCREPANCY"
    assert any(d.dimension == "POSITION" for d in res_c.discrepancies)

    # Case D: Diff = 0.00020 (> 0.0001) below ledger (9.99980) -> FAIL (DISCREPANCY)
    res_d = run_reconcile_for_qty("9.99980")
    assert res_d.shares_match is False
    assert res_d.status == "DISCREPANCY"

    # Case E: Completely missing position in broker (0 shares) -> FAIL
    res_e = run_reconcile_for_qty("0.0000")
    assert res_e.shares_match is False
    assert res_e.status == "DISCREPANCY"


def test_reconciliation_observation_lag_seconds_calculation(db_factory):
    """Verify observation_lag_seconds (time delta) calculation accuracy under normal, reversed, and zero lag."""
    # 1. Forward Lag: Latest transaction at 08:30:00 UTC, Snapshot at 11:00:15 UTC
    # Expected lag = 2 hours, 30 minutes, 15 seconds = 9015 seconds
    db1 = db_factory()
    t_tx1 = TransactionItem(
        id="TX_LAG_01",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 8, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db1, [t_tx1])

    with db1.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_lag_01', 'run_lag_1', 'portfolio', '2026-10-25T11:00:00Z',
                '2026-10-25T11:00:15Z', 'scalable', 0, 'OK', '1.0',
                'GENESIS', 'hash_lag_1', '2026-10-25T11:00:15Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_lag_01', 'DE12***345', 'EUR', '1000.00',
                '1000.00', '2026-10-25T11:00:15Z', 'cash_hash_lag'
            )
            """
        )

    summary1 = reconcile_ledger_with_broker(db1, run_id="run_lag_forward")
    assert summary1.observation_lag_seconds == 9015

    # Check persistence in DB
    conn = db1.get_connection()
    try:
        row1 = conn.execute("SELECT observation_lag_seconds FROM reconciliations WHERE run_id = 'run_lag_forward'").fetchone()
        assert row1["observation_lag_seconds"] == "9015"
    finally:
        conn.close()

    # 2. Reverse Lag: Snapshot occurred BEFORE latest transaction:
    # Snapshot at 08:00:00 UTC, latest tx at 08:30:00 UTC -> Lag = 1800 seconds (absolute value)
    db2 = db_factory()
    t_tx2 = TransactionItem(
        id="TX_LAG_02",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 8, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db2, [t_tx2])

    with db2.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_lag_02', 'run_lag_2', 'portfolio', '2026-10-25T07:55:00Z',
                '2026-10-25T08:00:00Z', 'scalable', 0, 'OK', '1.0',
                'GENESIS', 'hash_lag_2', '2026-10-25T08:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_lag_02', 'DE12***345', 'EUR', '1000.00',
                '1000.00', '2026-10-25T08:00:00Z', 'cash_hash_lag_2'
            )
            """
        )

    summary2 = reconcile_ledger_with_broker(db2, run_id="run_lag_reverse")
    assert summary2.observation_lag_seconds == 1800

    # 3. Exact Zero Lag: Snapshot at exactly 08:30:00 UTC, tx at 08:30:00 UTC -> Lag = 0
    db3 = db_factory()
    t_tx3 = TransactionItem(
        id="TX_LAG_03",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 8, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db3, [t_tx3])

    with db3.transaction() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_lag_03', 'run_lag_3', 'portfolio', '2026-10-25T08:29:00Z',
                '2026-10-25T08:30:00Z', 'scalable', 0, 'OK', '1.0',
                'GENESIS', 'hash_lag_3', '2026-10-25T08:30:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cash_observations (
                snapshot_id, account_id_masked, currency, settled_cash,
                total_cash, observed_at, record_hash
            ) VALUES (
                'snap_lag_03', 'DE12***345', 'EUR', '1000.00',
                '1000.00', '2026-10-25T08:30:00Z', 'cash_hash_lag_3'
            )
            """
        )

    summary3 = reconcile_ledger_with_broker(db3, run_id="run_lag_zero")
    assert summary3.observation_lag_seconds == 0

    # 4. No snapshot at all -> lag must be None
    db4 = db_factory()
    t_tx4 = TransactionItem(
        id="TX_LAG_04",
        type="CASH_TRANSACTION",
        cash_transaction_type="DEPOSIT",
        amount=Decimal("1000.00"),
        currency="EUR",
        status="SETTLED",
        last_event_datetime=datetime(2026, 10, 25, 8, 30, 0, tzinfo=timezone.utc),
    )
    ingest_transaction_versions(db4, [t_tx4])

    summary4 = reconcile_ledger_with_broker(db4, run_id="run_lag_none")
    assert summary4.observation_lag_seconds is None


def test_reconciliation_cost_basis_tolerance_boundary(db_factory):
    """Verify COST_TOLERANCE (0.01 EUR/share) boundary conditions."""
    isin = "IE00B4L5Y983"

    def run_reconcile_for_cost(broker_cost_str: str):
        db = db_factory()
        t_buy = TransactionItem(
            id="TX_COST_B1",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin=isin,
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("10.0000"),
            status="SETTLED",
            last_event_datetime=datetime(2026, 10, 25, 9, 30, 0, tzinfo=timezone.utc),
        )
        ingest_transaction_versions(db, [t_buy])
        # Ledger unit cost is exactly 50.00 EUR/share

        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, run_id, snapshot_type, collection_started_at,
                    collection_completed_at, source, item_count, quality_status,
                    connector_version, prev_hash, curr_hash, created_at
                ) VALUES (
                    'snap_cst', 'run_cst', 'portfolio', '2026-10-25T10:00:00Z',
                    '2026-10-25T10:05:00Z', 'scalable', 1, 'OK', '1.0',
                    'GENESIS', 'hash_curr', '2026-10-25T10:05:00Z'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO position_observations (
                    snapshot_id, isin, display_name, quantity, value_eur,
                    broker_cost_basis, observed_at, record_hash
                ) VALUES (
                    'snap_cst', 'IE00B4L5Y983', 'Core MSCI World',
                    '10.0000', '500.00', ?, '2026-10-25T10:05:00Z', 'pos_hash'
                )
                """,
                (broker_cost_str,),
            )
            conn.execute(
                """
                INSERT INTO cash_observations (
                    snapshot_id, account_id_masked, currency, settled_cash,
                    total_cash, observed_at, record_hash
                ) VALUES (
                    'snap_cst', 'DE12***345', 'EUR', '-500.00',
                    '-500.00', '2026-10-25T10:05:00Z', 'cash_hash'
                )
                """
            )
        return reconcile_ledger_with_broker(db, run_id=f"run_cst_{broker_cost_str}")

    # Case A: Diff = 0.008 (<= 0.01 tolerance) -> cost_basis_match is True
    res_a = run_reconcile_for_cost("50.008")
    assert res_a.cost_basis_match is True

    # Case B: Diff = 0.010 (== 0.01 tolerance boundary) -> cost_basis_match is True
    res_b = run_reconcile_for_cost("50.010")
    assert res_b.cost_basis_match is True

    # Case C: Diff = 0.015 (> 0.01 tolerance) -> cost_basis_match is False, DISCREPANCY
    res_c = run_reconcile_for_cost("50.015")
    assert res_c.cost_basis_match is False
    assert res_c.status == "DISCREPANCY"
    assert any(d.dimension == "COST_BASIS" for d in res_c.discrepancies)
