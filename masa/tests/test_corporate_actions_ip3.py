"""Comprehensive tests for IP-3: Corporate Actions module.

Tests:
- Immutability triggers (UPDATE, DELETE, OVERWRITE aborted)
- Mandatory approved_by authorization check
- ISO 6166 ISIN and action semantic validations
- Database registration with record_hash and audit logging
- Dynamic in-memory FIFO lot transformation (splits, reverse splits, ISIN change)
- Zero mutation guarantee on immutable database records
- CLI execution (ekle, listele)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
import pytest

from masa.calc.corporate import (
    CorporateActionRecord,
    CorporateActionType,
    list_corporate_actions,
    register_corporate_action,
    transform_lots_for_corporate_action,
)
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_corporate_action_hash


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    db_path = tmp_path / "ca_test.db"
    mgr = DatabaseManager(db_path=db_path)
    mgr.initialize_schema()
    return mgr


def test_corporate_actions_immutability(test_db):
    """Verify that UPDATE, DELETE, and OVERWRITE on corporate_actions are strictly aborted."""
    now_iso = datetime.now(timezone.utc).isoformat()
    val = {
        "action_id": "ca_test_001",
        "isin": "IE00B4L5Y983",
        "action_type": "SPLIT",
        "ratio": "2.0",
        "new_isin": None,
        "new_ticker": None,
        "effective_date": now_iso,
        "announcement_date": None,
        "description": "2:1 Stock Split",
        "source": "user",
        "evidence_json": None,
        "approved_by": "test_operator",
        "approved_at": now_iso,
        "supersedes_id": None,
        "created_at": now_iso,
    }
    rec_hash = compute_corporate_action_hash(val)

    with test_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO corporate_actions (
                action_id, isin, action_type, ratio, new_isin, new_ticker,
                effective_date, announcement_date, description, source,
                evidence_json, approved_by, approved_at, supersedes_id,
                created_at, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                val["action_id"], val["isin"], val["action_type"], val["ratio"],
                val["new_isin"], val["new_ticker"], val["effective_date"],
                val["announcement_date"], val["description"], val["source"],
                val["evidence_json"], val["approved_by"], val["approved_at"],
                val["supersedes_id"], val["created_at"], rec_hash,
            ),
        )

    # 1. UPDATE must fail
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions degistirilemez"):
        with test_db.transaction() as conn:
            conn.execute("UPDATE corporate_actions SET ratio = '3.0' WHERE action_id = 'ca_test_001'")

    # 2. DELETE must fail
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions kaydi silinemez"):
        with test_db.transaction() as conn:
            conn.execute("DELETE FROM corporate_actions WHERE action_id = 'ca_test_001'")

    # 3. OVERWRITE must fail
    with pytest.raises(sqlite3.IntegrityError, match="corporate_actions: mevcut kaydin uzerine yazma"):
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO corporate_actions (
                    action_id, isin, action_type, ratio, effective_date,
                    description, approved_by, approved_at, created_at, record_hash
                ) VALUES ('ca_test_001', 'IE00B4L5Y983', 'SPLIT', '2.0', ?, 'Overwrite', 'user', ?, ?, 'dummy')
                """,
                (now_iso, now_iso, now_iso),
            )


def test_mandatory_approved_by_validation():
    """Verify that corporate action cannot be constructed without approved_by."""
    with pytest.raises((ValueError, Exception)) as exc_info:
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="",  # Empty!
        )
    assert "approved_by cannot be empty" in str(exc_info.value) or "at least 1 character" in str(exc_info.value)

    with pytest.raises((ValueError, Exception)) as exc_info2:
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Test split",
            approved_by="   ",  # Whitespace!
        )
    assert "approved_by cannot be empty" in str(exc_info2.value) or "at least 1 character" in str(exc_info2.value)


def test_action_semantics_validation():
    """Verify that action types validate their required fields strictly."""
    # 1. Invalid ISIN fails
    with pytest.raises(ValueError):
        CorporateActionRecord(
            isin="INVALID_ISIN",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Bad isin",
            approved_by="test_operator",
        )

    # 2. Ratio <= 0 fails
    with pytest.raises(ValueError):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("-1.0"),
            effective_date="2026-10-25T00:00:00Z",
            description="Negative ratio",
            approved_by="test_operator",
        )

    # 3. SPLIT with new_isin must fail
    with pytest.raises(ValueError, match="SPLIT must not define new_isin"):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            new_isin="IE00B3YLTY66",
            effective_date="2026-10-25T00:00:00Z",
            description="Split with new isin",
            approved_by="test_operator",
        )

    # 4. ISIN_CHANGE without new_isin must fail
    with pytest.raises(ValueError, match="ISIN_CHANGE requires a valid new_isin"):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.ISIN_CHANGE,
            ratio=Decimal("1.0"),
            new_isin=None,
            effective_date="2026-10-25T00:00:00Z",
            description="Change without new isin",
            approved_by="test_operator",
        )

    # 5. ISIN_CHANGE with same new_isin must fail
    with pytest.raises(ValueError, match="requires new_isin to differ"):
        CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.ISIN_CHANGE,
            ratio=Decimal("1.0"),
            new_isin="IE00B4L5Y983",
            effective_date="2026-10-25T00:00:00Z",
            description="Same isin change",
            approved_by="test_operator",
        )


def test_registration_and_audit_logging(test_db):
    """Verify registration computes hash, writes to DB, and logs audit event."""
    action = CorporateActionRecord(
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("2.0"),
        effective_date="2026-10-25T00:00:00Z",
        description="2:1 Forward Stock Split",
        approved_by="operator:test_operator",
    )

    aid = register_corporate_action(test_db, action)
    assert aid == action.action_id

    # Verify query
    records = list_corporate_actions(test_db, isin="IE00B4L5Y983")
    assert len(records) == 1
    assert records[0].action_id == action.action_id
    assert records[0].ratio == Decimal("2.0")
    assert records[0].approved_by == "operator:test_operator"

    # Verify audit event
    conn = test_db.get_connection()
    try:
        ev = conn.execute(
            "SELECT action, actor, entity_id FROM audit_events WHERE action = 'CORPORATE_ACTION_REGISTERED'"
        ).fetchone()
        assert ev is not None
        assert ev["actor"] == "operator:test_operator"
        assert ev["entity_id"] == action.action_id
    finally:
        conn.close()


def test_dynamic_fifo_lot_transformation():
    """Verify in-memory lot transformations preserve cost basis and timestamps without mutating DB."""
    # 1. Forward Split (2:1)
    split_action = CorporateActionRecord(
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("2.0"),
        effective_date="2026-10-25T00:00:00Z",
        description="2:1 Forward Stock Split",
        approved_by="auditor",
    )
    initial_lots = [
        {"lot_id": "L1", "shares": Decimal("100"), "cost_per_share": Decimal("50.00"), "timestamp": "2026-01-10"},
        {"lot_id": "L2", "shares": Decimal("50"), "cost_per_share": Decimal("60.00"), "timestamp": "2026-02-15"},
    ]
    orig_total_basis = sum(l["shares"] * l["cost_per_share"] for l in initial_lots)  # 5000 + 3000 = 8000

    transformed_split, target_isin = transform_lots_for_corporate_action(initial_lots, split_action)
    assert target_isin == "IE00B4L5Y983"
    assert len(transformed_split) == 2
    assert transformed_split[0]["shares"] == Decimal("200")
    assert transformed_split[0]["cost_per_share"] == Decimal("25.00")
    assert transformed_split[1]["shares"] == Decimal("100")
    assert transformed_split[1]["cost_per_share"] == Decimal("30.00")

    new_total_basis = sum(l["shares"] * l["cost_per_share"] for l in transformed_split)
    assert new_total_basis == orig_total_basis, "Cost basis must be mathematically conserved!"

    # 2. Reverse Split (1:10)
    rev_action = CorporateActionRecord(
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.REVERSE_SPLIT,
        ratio=Decimal("0.1"),
        effective_date="2026-10-25T00:00:00Z",
        description="1:10 Reverse Split",
        approved_by="auditor",
    )
    transformed_rev, _ = transform_lots_for_corporate_action(initial_lots, rev_action)
    assert transformed_rev[0]["shares"] == Decimal("10.0")
    assert transformed_rev[0]["cost_per_share"] == Decimal("500.00")
    assert transformed_rev[0]["total_cost"] == Decimal("5000.00")

    # 3. ISIN Change
    isin_change = CorporateActionRecord(
        isin="IE00B4L5Y983",
        action_type=CorporateActionType.ISIN_CHANGE,
        ratio=Decimal("1.0"),
        new_isin="IE00B3YLTY66",
        effective_date="2026-10-25T00:00:00Z",
        description="ISIN Migration",
        approved_by="auditor",
    )
    transformed_migr, target_migr = transform_lots_for_corporate_action(initial_lots, isin_change)
    assert target_migr == "IE00B3YLTY66"
    assert transformed_migr[0]["isin"] == "IE00B3YLTY66"
    assert transformed_migr[0]["shares"] == Decimal("100")
    assert transformed_migr[0]["cost_per_share"] == Decimal("50.00")


def test_cli_kurumsal_islem(test_db, monkeypatch):
    """Verify CLI commands `masa kurumsal-islem ekle` and `listele`."""
    from masa.cli import main

    monkeypatch.setenv("MASA_DB_PATH", str(test_db.db_path))

    # Test adding a split via CLI
    with pytest.raises(SystemExit) as exc_add:
        main([
            "kurumsal-islem", "ekle",
            "--isin", "IE00B4L5Y983",
            "--tur", "SPLIT",
            "--oran", "2.0",
            "--tarih", "2026-10-25T00:00:00Z",
            "--onaylayan", "test_auditor",
            "--aciklama", "2:1 forward split via CLI",
        ])
    assert exc_add.value.code == 0

    # Test listing via CLI
    with pytest.raises(SystemExit) as exc_list:
        main(["kurumsal-islem", "listele", "--isin", "IE00B4L5Y983"])
    assert exc_list.value.code == 0

    # Ensure record was sealed in DB
    records = list_corporate_actions(test_db, isin="IE00B4L5Y983")
    assert len(records) == 1
    assert records[0].approved_by == "test_auditor"
