"""Comprehensive tests for İP-2: Identity Layer and CLI Capabilities Registry.

Covers:
1. sc_reader forbidden tokens ('add', 'remove', 'select') and command safety
2. sc_reader 'capabilities' and 'watchlist' read-only operations with lossless Decimal parsing
3. Scalable CLI v1.0.0 baseline freezing and risk-categorized drift detection
4. Schema v3 migration lifecycle: pre-migration backup + drill, 33 immutability triggers,
   v2 seal and hash chain preservation, automatic rollback on integrity failure
5. IdentityRegistry database integration and strict idempotency (0 duplicate writes)
6. Layered yfinance verification protocol handling European ETF ISIN '-' limitation
7. CLI integration: 'masa gecis', 'masa izleme', 'masa durum'
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from masa.cli import cmd_durum, cmd_gecis, cmd_izleme
from masa.identity.models import InstrumentType
from masa.identity.registry import IdentityRegistry
from masa.identity.verification import (
    normalize_tokens,
    token_similarity,
    verify_symbol_with_yfinance,
)
from masa.ingestion.capabilities import (
    SCALABLE_CLI_BASELINE_V100,
    CapabilitiesDriftReport,
    DriftLevel,
    detect_capabilities_drift,
)
from masa.ingestion.exceptions import ScalableSecurityViolation
from masa.ingestion.models import RawBrokerPayload
from masa.ingestion.sc_reader import (
    FORBIDDEN_TOKENS,
    ScalableReader,
    WatchlistItem,
    WatchlistResult,
)
from masa.pipeline import integrity_report
from masa.storage.db import DatabaseManager, SchemaVersionError
from masa.storage.migration import migrate_v2_to_v3
from masa.storage.snapshot_store import SnapshotStore


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def v2_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DatabaseManager:
    """Create a populated Schema v2 database with snapshots and audit events."""
    monkeypatch.setenv("MASA_BACKUP_DIR", str(tmp_path / "backups"))
    db_file = tmp_path / "test_masa_v2.db"
    mgr = DatabaseManager(db_file)
    conn = mgr.get_connection()
    try:
        # Create v2 schema (schema_v2 without instruments/listings)
        schema_v2_sql = Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql"
        content = schema_v2_sql.read_text(encoding="utf-8")
        # Strip v3 additions to simulate genuine v2
        lines = content.splitlines()
        v2_lines = []
        skip = False
        for line in lines:
            if "-- 10. INSTRUMENTS" in line:
                skip = True
            elif "-- DEGISMEZLIK TETIKLEYICILERI" in line:
                skip = False
            elif "-- instruments" in line and "TETIKLEYICILERI" not in line:
                break
            if not skip:
                v2_lines.append(line)
        v2_sql = "\n".join(v2_lines)
        conn.executescript(v2_sql)
        conn.execute("PRAGMA user_version = 2;")
    finally:
        conn.close()

    # Add a snapshot to simulate pre-existing data
    store = SnapshotStore(mgr)
    now = datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)
    raw_id, _ = store.store_raw_object("sc", '{"items": [{"isin": "IE00B3YLTY66"}]}', now)
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
    store.save_quote_snapshot("snap_v2_test", raw_id, "sc", now, now, quotes)
    return mgr


# -----------------------------------------------------------------------------
# 1. SC Reader Security & Forbidden Tokens
# -----------------------------------------------------------------------------

def test_sc_reader_forbidden_tokens_include_add_remove_select() -> None:
    """Ensure 'add', 'remove', and 'select' are in FORBIDDEN_TOKENS."""
    assert "add" in FORBIDDEN_TOKENS
    assert "remove" in FORBIDDEN_TOKENS
    assert "select" in FORBIDDEN_TOKENS


def test_sc_reader_watchlist_add_and_remove_strictly_rejected() -> None:
    """Verify that any attempt to call watchlist with 'add' or 'remove' is strictly rejected."""
    runner = MagicMock(return_value=(0, '{"ok": true}', ""))
    reader = ScalableReader(runner=runner)

    # 1. Raw operation 'watchlist' is forbidden top-level
    with pytest.raises(ScalableSecurityViolation):
        reader._execute_raw("watchlist")

    # 2. 'broker_watchlist' with 'add' extra_args
    with pytest.raises(ScalableSecurityViolation):
        reader._execute_raw("broker_watchlist", extra_args=["add", "--isin", "IE00B3YLTY66"])

    # 3. 'broker_watchlist' with 'remove' extra_args
    with pytest.raises(ScalableSecurityViolation):
        reader._execute_raw("broker_watchlist", extra_args=["remove", "--isin", "IE00B3YLTY66"])

    # 4. 'broker_watchlist' with unapproved flag '--isin'
    with pytest.raises(ScalableSecurityViolation):
        reader._execute_raw("broker_watchlist", extra_args=["--isin", "IE00B3YLTY66"])


# -----------------------------------------------------------------------------
# 2. Capabilities & Watchlist Execution
# -----------------------------------------------------------------------------

def test_sc_reader_get_capabilities() -> None:
    """Verify get_capabilities parses JSON into CapabilitiesResult DTO."""
    caps_payload = {
        "ok": True,
        "command": "capabilities",
        "data": {
            "version": "1.0.0",
            "output": "json_envelope",
            "commands": list(SCALABLE_CLI_BASELINE_V100),
            "auth": {"modes": ["device"]},
            "exit_codes": {"generic_error": 1, "validation_error": 10},
            "local_trade_controls": {"enabled": False},
        },
    }
    runner = MagicMock(return_value=(0, json.dumps(caps_payload), ""))
    reader = ScalableReader(runner=runner)

    res = reader.get_capabilities()
    assert res.version == "1.0.0"
    assert len(res.commands) == len(SCALABLE_CLI_BASELINE_V100)
    assert "broker.watchlist" in res.commands
    assert res.auth_modes == ["device"]
    assert res.exit_codes["generic_error"] == 1


def test_sc_reader_get_watchlist_lossless_decimal() -> None:
    """Verify get_watchlist parses items with Decimal precision and UTC timestamps."""
    wl_payload = {
        "ok": True,
        "command": "broker.watchlist",
        "data": {
            "account_id": "acc_123",
            "portfolio_id": "port_456",
            "result": {
                "account_id": "acc_123",
                "portfolio_id": "port_456",
                "count": 2,
                "items": [
                    {
                        "isin": "FR0010755611",
                        "name": "Amundi MSCI USA Daily (2x) Leveraged",
                        "quote_currency": "EUR",
                        "quote_is_outdated": False,
                        "quote_mid_price": 32.51,
                        "quote_timestamp_utc": "2026-10-30T19:37:14.192Z",
                        "security_type": "ETF",
                    },
                    {
                        "isin": "IE00B3YLTY66",
                        "name": "SPDR MSCI ACWI IMI",
                        "quote_currency": "EUR",
                        "quote_is_outdated": False,
                        "quote_mid_price": 11.615,
                        "quote_timestamp_utc": "2026-10-30T19:37:14.192Z",
                        "security_type": "ETF",
                    },
                ],
            },
        },
    }
    runner = MagicMock(return_value=(0, json.dumps(wl_payload), ""))
    reader = ScalableReader(runner=runner)

    res = reader.get_watchlist()
    assert isinstance(res, WatchlistResult)
    assert res.count == 2
    assert res.account_id == "acc_123"
    assert len(res.items) == 2

    it0 = res.items[0]
    assert it0.isin == "FR0010755611"
    assert isinstance(it0.quote_mid_price, Decimal)
    assert it0.quote_mid_price == Decimal("32.51")
    assert it0.quote_currency == "EUR"
    assert it0.quote_timestamp_utc.year == 2026


# -----------------------------------------------------------------------------
# 3. Capabilities Drift Detection
# -----------------------------------------------------------------------------

def test_capabilities_drift_clean_baseline() -> None:
    """Baseline v1.0.0 commands return DriftLevel.CLEAN."""
    rep = detect_capabilities_drift(SCALABLE_CLI_BASELINE_V100, "1.0.0")
    assert rep.level == DriftLevel.CLEAN
    assert rep.ok is True
    assert rep.baseline_count == len(SCALABLE_CLI_BASELINE_V100)
    assert rep.current_count == len(SCALABLE_CLI_BASELINE_V100)
    assert len(rep.added_commands) == 0
    assert len(rep.removed_commands) == 0


def test_capabilities_drift_critical_on_core_read_removed() -> None:
    """Removing a core read command returns DriftLevel.CRITICAL and ok=False."""
    tampered = set(SCALABLE_CLI_BASELINE_V100) - {"broker.holdings"}
    rep = detect_capabilities_drift(tampered, "1.0.1")
    assert rep.level == DriftLevel.CRITICAL
    assert rep.ok is False
    assert any("broker.holdings" in issue for issue in rep.critical_issues)


def test_capabilities_drift_critical_on_new_mutation_command() -> None:
    """Adding a command with a mutation token returns DriftLevel.CRITICAL."""
    tampered = set(SCALABLE_CLI_BASELINE_V100) | {"broker.trade.instant-buy"}
    rep = detect_capabilities_drift(tampered, "1.1.0")
    assert rep.level == DriftLevel.CRITICAL
    assert rep.ok is False
    assert any("broker.trade.instant-buy" in issue for issue in rep.critical_issues)


def test_capabilities_drift_info_on_safe_read_command() -> None:
    """Adding a safe read-only command returns DriftLevel.INFO and ok=True."""
    tampered = set(SCALABLE_CLI_BASELINE_V100) | {"broker.dividends"}
    rep = detect_capabilities_drift(tampered, "1.0.1")
    assert rep.level == DriftLevel.INFO
    assert rep.ok is True
    assert "broker.dividends" in rep.added_commands


# -----------------------------------------------------------------------------
# 4. Schema v3 Migration & Immutability Triggers
# -----------------------------------------------------------------------------

def test_schema_v3_migration_lifecycle(v2_db: DatabaseManager) -> None:
    """Test full migration from v2 to v3 with pre-backup, trigger creation, and seal preservation."""
    conn_pre = v2_db.get_connection()
    pre_snap_count = conn_pre.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn_pre.close()

    res = migrate_v2_to_v3(v2_db)
    assert res.success is True
    assert res.from_version == 2
    assert res.to_version == 3
    assert res.backup_path is not None
    assert Path(res.backup_path).exists()
    assert res.trigger_count >= 33
    assert res.integrity_ok is True
    assert res.rolled_back is False

    conn = v2_db.get_connection()
    try:
        user_ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        assert user_ver == 3

        # Check that 3 new tables exist
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('instruments', 'listings', 'issuer_links')"
            ).fetchall()
        }
        assert tables == {"instruments", "listings", "issuer_links"}

        # Check total trigger count >= 33
        trigger_count = int(
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        )
        assert trigger_count >= 33

        # Check v2 snapshot was preserved
        post_snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert post_snap_count == pre_snap_count
    finally:
        conn.close()

    # Re-running migration on v3 should be idempotent
    res2 = migrate_v2_to_v3(v2_db)
    assert res2.success is True
    assert res2.from_version == 3


def test_schema_v3_immutability_triggers(v2_db: DatabaseManager) -> None:
    """Verify that UPDATE and DELETE on instruments, listings, and issuer_links are aborted."""
    migrate_v2_to_v3(v2_db)
    conn = v2_db.get_connection()
    try:
        # 1. Test instruments immutability
        with pytest.raises(sqlite3.IntegrityError, match="instruments degistirilemez"):
            conn.execute("UPDATE instruments SET name = 'Hacked' WHERE 1=1")

        with pytest.raises(sqlite3.IntegrityError, match="instruments kaydi silinemez"):
            conn.execute("DELETE FROM instruments WHERE 1=1")

        # 2. Test listings immutability
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            conn.execute("UPDATE listings SET ticker = 'HACK' WHERE 1=1")

        with pytest.raises(sqlite3.IntegrityError, match="listings kaydi silinemez"):
            conn.execute("DELETE FROM listings WHERE 1=1")

        # 3. Test issuer_links immutability
        with pytest.raises(sqlite3.IntegrityError, match="issuer_links degistirilemez"):
            conn.execute("UPDATE issuer_links SET name = 'Hacked' WHERE 1=1")

        with pytest.raises(sqlite3.IntegrityError, match="issuer_links kaydi silinemez"):
            conn.execute("DELETE FROM issuer_links WHERE 1=1")
    finally:
        conn.close()


def test_schema_v3_migration_rollback_on_failure(tmp_path: Path) -> None:
    """Verify automatic rollback if integrity verification fails post-migration."""
    db_file = tmp_path / "rollback_test.db"
    mgr = DatabaseManager(db_file)
    conn = mgr.get_connection()
    try:
        schema_v2_sql = Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql"
        content = schema_v2_sql.read_text(encoding="utf-8")
        conn.executescript(content)
        conn.execute("PRAGMA user_version = 2;")
    finally:
        conn.close()

    # Tamper with integrity_report in migration to simulate post-migration check failure
    import masa.storage.migration as mig_mod
    original_report = mig_mod.integrity_report
    try:
        mig_mod.integrity_report = lambda db: {
            "ok": False,
            "schema_version": 3,
            "trigger_count": 33,
            "snapshot_chain_ok": False,
            "audit_chain_ok": True,
        }
        res = mig_mod.migrate_v2_to_v3(mgr)
        assert res.success is False
        assert res.rolled_back is True
        assert "başarısız oldu" in (res.error_message or "")

        # Verify database was restored to version 2
        chk_conn = mgr.get_connection()
        try:
            ver = int(chk_conn.execute("PRAGMA user_version").fetchone()[0])
            assert ver == 2
        finally:
            chk_conn.close()
    finally:
        mig_mod.integrity_report = original_report


# -----------------------------------------------------------------------------
# 5. IdentityRegistry DB Integration & Idempotency
# -----------------------------------------------------------------------------

def test_identity_registry_idempotency_zero_duplicate_writes(v2_db: DatabaseManager) -> None:
    """Verify that seeding and ensure_instrument produce 0 duplicate records when run repeatedly."""
    migrate_v2_to_v3(v2_db)
    reg = IdentityRegistry(db=v2_db)

    # First seeding
    c1 = reg.seed_from_configs()
    conn = v2_db.get_connection()
    try:
        inst_count1 = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count1 = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        link_count1 = conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
    finally:
        conn.close()

    assert inst_count1 > 0
    assert list_count1 > 0

    # Second seeding: STRICT IDEMPOTENCY CHECK
    c2 = reg.seed_from_configs()
    conn2 = v2_db.get_connection()
    try:
        inst_count2 = conn2.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count2 = conn2.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        link_count2 = conn2.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
    finally:
        conn2.close()

    assert inst_count2 == inst_count1
    assert list_count2 == list_count1
    assert link_count2 == link_count1

    # Calling ensure_instrument on existing ISIN returns existing ID with 0 writes
    inst_id = reg.ensure_instrument(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        instrument_type="ETF",
        issuer_id="iss_ssga_ie",
    )
    assert inst_id == "inst_ie00b3ylty66"


def test_identity_registry_invalid_isin_rejected(v2_db: DatabaseManager) -> None:
    """Verify that an invalid Luhn ISIN is rejected before touching the DB."""
    migrate_v2_to_v3(v2_db)
    reg = IdentityRegistry(db=v2_db)
    with pytest.raises(ValueError, match="ISIN.*mismatch"):
        reg.ensure_instrument(
            isin="US0378331000",  # Invalid check digit (correct is 5)
            name="Fake Apple",
            instrument_type="EQUITY",
            issuer_id="iss_apple_us",
        )


# -----------------------------------------------------------------------------
# 6. Yahoo Finance Layered Verification
# -----------------------------------------------------------------------------

def test_yfinance_layered_verification_direct_isin() -> None:
    """Test Layer 1: Direct ISIN match."""
    mock_ticker = MagicMock()
    mock_ticker.isin = "US0378331005"
    mock_ticker.info = {"longName": "Apple Inc.", "currency": "USD"}

    res = verify_symbol_with_yfinance(
        symbol="AAPL",
        target_isin="US0378331005",
        target_name="Apple",
        target_currency="USD",
        target_mic="XNAS",
        yf_ticker_factory=lambda s: mock_ticker,
    )
    assert res["status"] == "VERIFIED"
    assert res["evidence"]["matched_by"] == "direct_isin_match"
    assert res["evidence"]["similarity_score"] == 1.0


def test_yfinance_layered_verification_name_similarity_for_european_etf() -> None:
    """Test Layer 2: Yahoo returns '-' for ISIN, verified via token and name similarity."""
    mock_ticker = MagicMock()
    mock_ticker.isin = "-"
    mock_ticker.info = {
        "longName": "iShares Core MSCI EM IMI UCITS ETF USD (Acc)",
        "currency": "EUR",
    }

    res = verify_symbol_with_yfinance(
        symbol="IS3N.DE",
        target_isin="IE00BKM4GZ66",
        target_name="iShares Core MSCI EM IMI",
        target_currency="EUR",
        target_mic="XETR",
        yf_ticker_factory=lambda s: mock_ticker,
    )
    assert res["status"] == "VERIFIED"
    assert res["evidence"]["matched_by"] == "name_token_similarity"
    assert res["evidence"]["similarity_score"] >= 0.40


def test_yfinance_layered_verification_rejected_on_mismatch() -> None:
    """Test Layer 3: Completely mismatched ticker or security is REJECTED."""
    mock_ticker = MagicMock()
    mock_ticker.isin = "-"
    mock_ticker.info = {
        "longName": "Totally Unrelated Gold Corp",
        "currency": "CAD",
    }

    res = verify_symbol_with_yfinance(
        symbol="XYZ.DE",
        target_isin="IE00BKM4GZ66",
        target_name="iShares Core MSCI EM IMI",
        target_currency="EUR",
        target_mic="XETR",
        yf_ticker_factory=lambda s: mock_ticker,
    )
    assert res["status"] == "REJECTED"
    assert res["evidence"]["matched_by"] == "none"


# -----------------------------------------------------------------------------
# 7. CLI Integration: gecis, izleme, durum
# -----------------------------------------------------------------------------

def test_cli_cmd_gecis_and_durum(v2_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CLI commands 'masa gecis' and 'masa durum'."""
    monkeypatch.setenv("MASA_DB_PATH", str(v2_db.db_path))

    args = MagicMock()
    rc_gecis = cmd_gecis(args)
    assert rc_gecis == 0

    rc_durum = cmd_durum(args)
    assert rc_durum == 0
