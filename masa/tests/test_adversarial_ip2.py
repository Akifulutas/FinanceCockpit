"""Empirical Adversarial Stress Test Suite for İP-2.

Executed by: challenger_ip2_1
Target Modules:
- masa.ingestion.sc_reader (ScalableReader security barriers, forbidden tokens, flag injection)
- masa.ingestion.capabilities (Scalable CLI v1.0.0 drift engine, synthetic mutations, core read removals)
- masa.storage.schema (Schema v3 immutability triggers: instruments, listings, issuer_links)
- masa.identity.registry (IdentityRegistry DB idempotency, zero duplicates, invalid ISIN rejection)

All tests are empirical and designed to challenge assumptions and attack potential bypass vectors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import itertools
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock

from pydantic import ValidationError
import pytest

from masa.config import MASA_DIR
from masa.backup import create_backup
from masa.identity.isin import validate_isin
from masa.identity.models import InstrumentType
from masa.identity.registry import IdentityRegistry
from masa.ingestion.capabilities import (
    CORE_READ_COMMANDS,
    MUTATION_TOKENS,
    SCALABLE_CLI_BASELINE_V100,
    CapabilitiesDriftReport,
    DriftLevel,
    detect_capabilities_drift,
)
from masa.ingestion.exceptions import ScalableReaderError, ScalableSecurityViolation
from masa.ingestion.sc_reader import (
    ALLOWED_FLAGS,
    ALLOWED_READ_OPERATIONS,
    FORBIDDEN_TOKENS,
    OPERATION_TO_CLI_SUBCOMMAND,
    ScalableReader,
    WatchlistItem,
)
from masa.storage.db import DatabaseManager
from masa.storage.migration import migrate_v2_to_v3
from masa.storage.snapshot_store import SnapshotStore


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def v3_db(tmp_path: Path) -> DatabaseManager:
    """Create a fully migrated Schema v3 database with 33 immutability triggers."""
    db_file = tmp_path / "test_masa_adversarial_v3.db"
    mgr = DatabaseManager(db_file)
    conn = mgr.get_connection()
    try:
        schema_sql = Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql"
        content = schema_sql.read_text(encoding="utf-8")
        conn.executescript(content)
        conn.execute("PRAGMA user_version = 3;")
    finally:
        conn.close()
    return mgr


# =============================================================================
# PART 1: ADVERSARIAL STRESS TESTING OF sc_reader.py SECURITY BARRIERS
# =============================================================================

class TestScReaderSecurityBarriers:
    """Stress-test ScalableReader against forbidden operations, case variations, and flag injections."""

    @pytest.mark.parametrize(
        "forbidden_op",
        [
            # Explicit forbidden operations from review instructions
            "watchlist add",
            "watchlist remove",
            "broker select",
            # Case variations
            "WATCHLIST ADD",
            "Watchlist Add",
            "wAtChLiSt aDd",
            "WATCHLIST REMOVE",
            "Watchlist Remove",
            "wAtChLiSt rEmOvE",
            "BROKER SELECT",
            "Broker Select",
            "bRoKeR sElEcT",
            # Dot / dash / underscore variations
            "watchlist.add",
            "watchlist-add",
            "watchlist_add",
            "broker.select",
            "broker-select",
            "broker_select",
            "broker.watchlist.add",
            "broker.watchlist.remove",
            "broker.watchlist_add",
            # Direct forbidden mutation commands
            "trade",
            "TRADE",
            "buy",
            "BUY",
            "sell",
            "SELL",
            "cancel",
            "CANCEL",
            "savings-plans",
            "price-alerts",
            "order",
            "login",
            "logout",
            # Injection tricks
            "watchlist add\n",
            "broker select --force",
            "capabilities; rm -rf /",
            "whoami && cat /etc/passwd",
        ],
    )
    def test_forbidden_operations_always_raise_security_violation(self, forbidden_op: str) -> None:
        """Every forbidden operation or variation must raise ScalableSecurityViolation."""
        runner = MagicMock(return_value=(0, '{"ok": true}', ""))
        reader = ScalableReader(runner=runner)

        with pytest.raises(ScalableSecurityViolation) as exc_info:
            reader._execute_raw(forbidden_op)

        # Ensure runner was NEVER invoked
        runner.assert_not_called()
        assert "Unauthorized broker command" in str(exc_info.value) or "forbidden" in str(exc_info.value).lower()

    @pytest.mark.parametrize(
        "target_op",
        ["capabilities", "broker_watchlist", "broker.watchlist"],
    )
    @pytest.mark.parametrize(
        "poisoned_args",
        [
            # Argument-level mutations
            ["add"],
            ["ADD"],
            ["aDd"],
            ["--add"],
            ["--ADD"],
            ["-add"],
            ["remove"],
            ["REMOVE"],
            ["rEmOvE"],
            ["--remove"],
            ["--REMOVE"],
            ["-remove"],
            ["select"],
            ["SELECT"],
            ["sElEcT"],
            ["--select"],
            ["--SELECT"],
            ["-select"],
            # Multi-word mutations
            ["broker", "select"],
            ["context", "select"],
            ["watchlist", "add"],
            ["watchlist", "remove"],
            # Flag enjection attempts
            ["--isin", "IE00B3YLTY66"],
            ["--isin=IE00B3YLTY66"],
            ["--all"],
            ["--confirm"],
            ["--CONFIRM"],
            ["--force"],
            ["--account", "1234567890"],
            ["--portfolio", "port_123"],
            ["--json"],
            ["-v"],
            ["--verbose"],
            # Shell metacharacters injection
            ["; rm -rf /"],
            ["| id"],
            ["$(whoami)"],
            ["`id`"],
            ["&& cat /etc/passwd"],
            # Value tricks
            ["--isin", "--force"],
            ["--isin"],
        ],
    )
    def test_capabilities_and_watchlist_reject_all_extra_args(
        self, target_op: str, poisoned_args: List[str]
    ) -> None:
        """capabilities and watchlist are strictly zero-flag operations. Any argument MUST raise ScalableSecurityViolation."""
        runner = MagicMock(return_value=(0, '{"ok": true}', ""))
        reader = ScalableReader(runner=runner)

        with pytest.raises(ScalableSecurityViolation):
            reader._execute_raw(target_op, extra_args=poisoned_args)

        runner.assert_not_called()

    @pytest.mark.parametrize(
        "invalid_arg",
        [
            [123],
            [None],
            [{"attack": True}],
            [[1, 2, 3]],
        ],
    )
    def test_non_string_arguments_rejected(self, invalid_arg: Any) -> None:
        """Non-string CLI arguments fail before execution with ScalableSecurityViolation."""
        runner = MagicMock(return_value=(0, '{"ok": true}', ""))
        reader = ScalableReader(runner=runner)

        with pytest.raises(ScalableSecurityViolation) as exc_info:
            reader._execute_raw("capabilities", extra_args=invalid_arg)

        assert "CLI arguments must be strings" in str(exc_info.value)
        runner.assert_not_called()

    def test_default_subprocess_runner_enforces_shell_false(self) -> None:
        """Confirm default_subprocess_runner runs with shell=False under inspect."""
        import inspect
        from masa.ingestion.sc_reader import default_subprocess_runner
        src = inspect.getsource(default_subprocess_runner)
        assert "shell=False" in src
        assert "shell=True" not in src


# =============================================================================
# PART 2: ADVERSARIAL STRESS TESTING OF capabilities.py DRIFT ENGINE
# =============================================================================

class TestCapabilitiesDriftEngine:
    """Stress-test drift detection with synthetic mutations, removals, and boundary inputs."""

    @pytest.mark.parametrize(
        "mutation_token",
        sorted(MUTATION_TOKENS),
    )
    def test_synthetic_mutation_tokens_always_trigger_critical(self, mutation_token: str) -> None:
        """Injecting ANY command containing a token from MUTATION_TOKENS must trigger DriftLevel.CRITICAL."""
        synthetic_commands = [
            f"broker.{mutation_token}",
            f"broker.special.{mutation_token}",
            f"broker.{mutation_token}.action",
            f"broker.sub-{mutation_token}-feature",
        ]
        for cmd in synthetic_commands:
            tampered_commands = set(SCALABLE_CLI_BASELINE_V100) | {cmd}
            report = detect_capabilities_drift(tampered_commands, cli_version="1.9.9")

            assert report.level == DriftLevel.CRITICAL, f"Command '{cmd}' failed to trigger CRITICAL!"
            assert report.ok is False
            assert len(report.critical_issues) >= 1
            assert any(cmd in issue for issue in report.critical_issues)
            assert any(mutation_token in issue for issue in report.critical_issues)

    @pytest.mark.parametrize(
        "mutation_cmd",
        [
            "broker.trade.instant-buy",
            "broker.crypto.quick-sell",
            "broker.orders.create",
            "broker.orders.delete",
            "broker.account.withdraw",
            "broker.funds.transfer",
            "broker.positions.modify",
            "broker.settings.update",
            "broker.api.post",
            "broker.api.put",
            "broker.favorites.add",
            "broker.favorites.remove",
            "broker.batch.cancel",
        ],
    )
    def test_realistic_broker_mutation_commands_trigger_critical(self, mutation_cmd: str) -> None:
        """Realistic mutation commands trigger CRITICAL."""
        tampered_commands = set(SCALABLE_CLI_BASELINE_V100) | {mutation_cmd}
        report = detect_capabilities_drift(tampered_commands, cli_version="2.0.0")

        assert report.level == DriftLevel.CRITICAL
        assert report.ok is False
        assert any(mutation_cmd in issue for issue in report.critical_issues)

    @pytest.mark.parametrize(
        "core_read_cmd",
        sorted(CORE_READ_COMMANDS),
    )
    def test_removing_any_core_read_command_always_triggers_critical(self, core_read_cmd: str) -> None:
        """Removing ANY single core read command must trigger DriftLevel.CRITICAL and ok=False."""
        tampered_commands = set(SCALABLE_CLI_BASELINE_V100) - {core_read_cmd}
        report = detect_capabilities_drift(tampered_commands, cli_version="1.0.1")

        assert report.level == DriftLevel.CRITICAL, f"Removing '{core_read_cmd}' did not trigger CRITICAL!"
        assert report.ok is False
        assert len(report.critical_issues) >= 1
        assert any(core_read_cmd in issue for issue in report.critical_issues)
        assert any("Kritik okuma komutu kaldırılmış" in issue for issue in report.critical_issues)

    def test_removing_all_core_read_commands_triggers_critical_with_all_reported(self) -> None:
        """Removing all 9 core read commands reports all 9 in critical_issues."""
        tampered_commands = set(SCALABLE_CLI_BASELINE_V100) - CORE_READ_COMMANDS
        report = detect_capabilities_drift(tampered_commands, cli_version="1.0.1")

        assert report.level == DriftLevel.CRITICAL
        assert report.ok is False
        assert len(report.critical_issues) == len(CORE_READ_COMMANDS)
        for core_cmd in CORE_READ_COMMANDS:
            assert any(core_cmd in issue for issue in report.critical_issues)

    def test_empty_command_set_is_maximally_critical(self) -> None:
        """Completely empty CLI command set is detected as CRITICAL."""
        report = detect_capabilities_drift([], cli_version="0.0.0")
        assert report.level == DriftLevel.CRITICAL
        assert report.ok is False
        assert len(report.removed_commands) == len(SCALABLE_CLI_BASELINE_V100)
        assert len(report.critical_issues) == len(CORE_READ_COMMANDS)

    def test_simultaneous_mutation_and_core_read_removal(self) -> None:
        """Both a mutation addition AND a core read removal produce compound critical issues."""
        tampered = (set(SCALABLE_CLI_BASELINE_V100) - {"broker.holdings"}) | {"broker.trade.one-click-buy"}
        report = detect_capabilities_drift(tampered, cli_version="1.2.0")

        assert report.level == DriftLevel.CRITICAL
        assert report.ok is False
        assert any("broker.holdings" in issue for issue in report.critical_issues)
        assert any("broker.trade.one-click-buy" in issue for issue in report.critical_issues)
        assert len(report.critical_issues) == 2

    def test_non_critical_removals_trigger_warning(self) -> None:
        """Removing an optional/non-core command (e.g. broker.security-news) triggers WARNING, ok=True."""
        tampered = set(SCALABLE_CLI_BASELINE_V100) - {"broker.security-news"}
        report = detect_capabilities_drift(tampered, cli_version="1.0.1")

        assert report.level == DriftLevel.WARNING
        assert report.ok is True
        assert "broker.security-news" in report.removed_commands
        assert len(report.critical_issues) == 0

    def test_safe_read_command_addition_triggers_info(self) -> None:
        """Adding a benign, purely read-only command (e.g. broker.dividends) triggers INFO, ok=True."""
        tampered = set(SCALABLE_CLI_BASELINE_V100) | {"broker.dividends", "broker.reports"}
        report = detect_capabilities_drift(tampered, cli_version="1.0.1")

        assert report.level == DriftLevel.INFO
        assert report.ok is True
        assert "broker.dividends" in report.added_commands
        assert "broker.reports" in report.added_commands
        assert len(report.critical_issues) == 0


# =============================================================================
# PART 3: SCHEMA v3 IMMUTABILITY TRIGGERS AND REGISTRY STRESS TESTING
# =============================================================================

class TestSchemaV3ImmutabilityAndRegistryStress:
    """Stress-test Schema v3 immutability triggers and IdentityRegistry idempotency."""

    def test_schema_v3_direct_sql_tampering_aborts(self, v3_db: DatabaseManager) -> None:
        """Direct SQL UPDATE/DELETE/REPLACE on instruments, listings, issuer_links must fail."""
        reg = IdentityRegistry(db=v3_db)
        inst_id = reg.ensure_instrument(
            isin="IE00B3YLTY66",
            name="SPDR MSCI ACWI IMI",
            instrument_type="ETF",
            issuer_id="iss_ssga",
        )
        list_id = reg.ensure_listing(
            instrument_id=inst_id,
            mic="XETR",
            ticker="SPYI",
            currency="EUR",
        )
        link_id = reg.ensure_issuer_link(
            issuer_id="iss_ssga",
            name="State Street Global Advisors",
            country="IE",
        )

        conn = v3_db.get_connection()
        try:
            # 1. Direct UPDATE attacks
            with pytest.raises(sqlite3.IntegrityError, match="instruments degistirilemez"):
                conn.execute("UPDATE instruments SET name = 'Attacked' WHERE instrument_id = ?", (inst_id,))

            with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
                conn.execute("UPDATE listings SET ticker = 'HACK' WHERE listing_id = ?", (list_id,))

            with pytest.raises(sqlite3.IntegrityError, match="issuer_links degistirilemez"):
                conn.execute("UPDATE issuer_links SET name = 'Attacked' WHERE link_id = ?", (link_id,))

            # 2. Direct DELETE attacks
            with pytest.raises(sqlite3.IntegrityError, match="instruments kaydi silinemez"):
                conn.execute("DELETE FROM instruments WHERE instrument_id = ?", (inst_id,))

            with pytest.raises(sqlite3.IntegrityError, match="listings kaydi silinemez"):
                conn.execute("DELETE FROM listings WHERE listing_id = ?", (list_id,))

            with pytest.raises(sqlite3.IntegrityError, match="issuer_links kaydi silinemez"):
                conn.execute("DELETE FROM issuer_links WHERE link_id = ?", (link_id,))

            # 3. Direct Overwrite / UPSERT simulation (INSERT with existing PK or UNIQUE)
            now = datetime.now(timezone.utc).isoformat()
            with pytest.raises(sqlite3.IntegrityError, match="instruments: mevcut kaydin uzerine yazma"):
                conn.execute(
                    "INSERT INTO instruments (instrument_id, isin, name, instrument_type, issuer_id, base_currency, created_at, record_hash) "
                    "VALUES (?, ?, 'Fake', 'ETF', 'iss_fake', 'EUR', ?, 'dummyhash')",
                    (inst_id, "IE00B3YLTY66", now),
                )

            with pytest.raises(sqlite3.IntegrityError, match="listings: mevcut kaydin uzerine yazma"):
                conn.execute(
                    "INSERT INTO listings (listing_id, instrument_id, mic, ticker, currency, created_at, record_hash) "
                    "VALUES ('list_fake_new', ?, 'XETR', 'SPYI', 'EUR', ?, 'dummyhash')",
                    (inst_id, now),
                )
        finally:
            conn.close()

    def test_identity_registry_consecutive_seedings_zero_duplicate_rows(self, v3_db: DatabaseManager) -> None:
        """Seeding 5 times consecutively produces exactly the same row counts (strict idempotency)."""
        reg = IdentityRegistry(db=v3_db)

        # Baseline seed
        counts_0 = reg.seed_from_configs()
        assert counts_0["instruments"] > 0
        assert counts_0["listings"] > 0

        conn = v3_db.get_connection()
        try:
            inst_0 = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
            list_0 = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            link_0 = conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
        finally:
            conn.close()

        # Seed 4 more times
        for _ in range(4):
            reg.seed_from_configs()
            chk_conn = v3_db.get_connection()
            try:
                inst_n = chk_conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
                list_n = chk_conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
                link_n = chk_conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
            finally:
                chk_conn.close()

            assert inst_n == inst_0
            assert list_n == list_0
            assert link_n == link_0

    @pytest.mark.parametrize(
        "invalid_isin",
        [
            "",
            "US0378331000",   # Luhn check digit failure (Apple correct is 5)
            "IE00B3YLTY60",   # Luhn check digit failure
            "DE000BAY0010",   # Luhn check digit failure
            "US123",          # Too short
            "US03783310051",  # Too long
            "123456789012",   # No country code
            "us0378331000",   # Lowercase invalid checksum (Luhn check digit 0 vs expected 5)
        ],
    )
    def test_invalid_isins_rejected_before_db_write(self, v3_db: DatabaseManager, invalid_isin: str) -> None:
        """Every invalid ISIN must be rejected with ValueError, leaving DB completely untouched."""
        reg = IdentityRegistry(db=v3_db)
        with pytest.raises(ValueError):
            reg.ensure_instrument(
                isin=invalid_isin,
                name="Bogus Security",
                instrument_type="EQUITY",
                issuer_id="iss_bogus",
            )


# =============================================================================
# PART 5: ROUND 2 ADVERSARIAL STRESS SUITE (challenger_ip2_r2_1)
# =============================================================================

class TestWatchlistItemValidationAdversarial:
    """Stress-test WatchlistItem quote_mid_price validation."""

    @pytest.mark.parametrize(
        "valid_price",
        [
            Decimal("0"),
            Decimal("0.0"),
            Decimal("0.00"),
            Decimal("0.0000000001"),
            Decimal("999999.99"),
            None,
        ],
    )
    def test_quote_mid_price_valid_boundary_values(self, valid_price: Any) -> None:
        """Ensure 0, positive decimals, and None pass Pydantic validation without exception."""
        item = WatchlistItem(
            isin="IE00B4L5Y983",
            name="iShares Core MSCI World UCITS ETF",
            quote_mid_price=valid_price,
        )
        assert item.quote_mid_price == valid_price

    @pytest.mark.parametrize(
        "negative_price",
        [
            Decimal("-0.00000001"),
            Decimal("-0.01"),
            Decimal("-1.0"),
            Decimal("-9999.99"),
        ],
    )
    def test_quote_mid_price_negative_rejected(self, negative_price: Decimal) -> None:
        """Negative prices must raise ValidationError due to ge=Decimal('0')."""
        with pytest.raises(ValidationError):
            WatchlistItem(
                isin="IE00B4L5Y983",
                name="iShares Core MSCI World UCITS ETF",
                quote_mid_price=negative_price,
            )


class TestLiveLedgerIsolationAdversarial:
    """Empirical proof that non-live database backups and migrations NEVER touch live ledger."""

    def test_migration_and_backup_never_pollute_live_ledger(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even without MASA_BACKUP_DIR set, temp DB migration and backup must write to tempdir/backups."""
        monkeypatch.delenv("MASA_BACKUP_DIR", raising=False)
        live_ledger = MASA_DIR / "var" / "backups" / "zincir-uclari.jsonl"
        orig_bytes = live_ledger.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()
        orig_lines = orig_bytes.decode("utf-8").splitlines()

        # Step 1: Create a temporary v2 database
        temp_db = tmp_path / "adversarial_v2.db"
        mgr = DatabaseManager(temp_db)
        conn = mgr.get_connection()
        schema_v2_sql = (Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql").read_text(encoding="utf-8")
        lines = schema_v2_sql.splitlines()
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
        conn.executescript("\n".join(v2_lines))
        conn.execute("PRAGMA user_version = 2;")
        conn.close()

        store = SnapshotStore(mgr)
        now = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)
        raw_id, _ = store.store_raw_object("sc", "{}", now)
        store.save_quote_snapshot("snap_adv", raw_id, "sc", now, now, [{
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
        }])

        # Step 2: Migrate v2 -> v3
        mig_res = migrate_v2_to_v3(mgr)
        assert mig_res.success, f"Migration failed: {mig_res.error_message}"

        # Step 3: Take another backup directly
        b_res = create_backup(mgr, run_drill=True)
        assert b_res.success

        # Step 4: Verify isolated backup dir received the ledger
        isolated_ledger = tmp_path / "backups" / "zincir-uclari.jsonl"
        assert isolated_ledger.exists()
        isolated_lines = isolated_ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(isolated_lines) == 2  # 1 from migration, 1 from create_backup

        # Step 5: Assert 100% zero leakage into live ledger
        new_bytes = live_ledger.read_bytes()
        new_sha = hashlib.sha256(new_bytes).hexdigest()
        assert new_sha == orig_sha, f"CRITICAL LEAK: Live ledger sha changed from {orig_sha} to {new_sha}"
        assert len(new_bytes.decode("utf-8").splitlines()) == len(orig_lines)


class TestIssuerLinksCounterAdversarial:
    """Verify seed_from_configs counts issuer links accurately."""

    def test_issuer_links_counter_nonzero(self, v3_db: DatabaseManager) -> None:
        reg = IdentityRegistry(db=v3_db)
        counts = reg.seed_from_configs()
        assert "issuer_links" in counts
        assert counts["issuer_links"] > 0
        assert counts["issuer_links"] == 11

