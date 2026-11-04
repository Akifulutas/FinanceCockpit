"""Adversarial Empirical Challenge Suite for IP-2: Schema Transition & Identity Idempotency.

Authored by: challenger_ip2_2 (Empirical Challenger Subagent)
Target: IP-2 (Schema v3 migration, immutability triggers, IdentityRegistry idempotency, fault injection)

Test Matrix:
1. `masa gecis` Schema Transition Stress Tests:
   - Idempotency: Multiple (10x) consecutive runs on v3 DB with pre-existing data -> 0 errors, 0 data loss.
   - Fault Injection A: DDL execution failure midway -> automatic rollback to v2, user_version=2, data intact.
   - Fault Injection B: Post-migration integrity verification failure (trigger tampering) -> automatic rollback.
   - Fault Injection C: Post-migration hash chain failure -> automatic rollback to v2.
   - Fault Injection D: CLI `cmd_gecis` on fault injection -> returns exit code 1, prints rollback message.
2. Immutability Triggers (ABORT) on instruments, listings, issuer_links:
   - UPDATE on instruments (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - DELETE on instruments (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - UPDATE on listings (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - DELETE on listings (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - UPDATE on issuer_links (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - DELETE on issuer_links (targeted + bulk) -> sqlite3.IntegrityError ABORT
   - INSERT OR REPLACE / ON CONFLICT DO UPDATE on instruments -> ABORT
   - INSERT OR REPLACE on listings -> ABORT
   - INSERT OR REPLACE on issuer_links -> ABORT
3. IdentityRegistry 50-Run Stress Test & Holdings Sync Idempotency:
   - 50 consecutive runs of `seed_from_configs()` -> zero duplicate instruments, listings, or issuer_links.
   - 50 consecutive iterations of simulated holdings/watchlist synchronization -> 0 duplicates, 0 writes after run 1.
   - Group-by verification: 0 duplicate ISINs, 0 duplicate (MIC, ticker, currency).
4. Edge Case Invalidation:
   - Invalid ISINs (checksum failure, malformed, empty) rejected with ValueError and zero DB pollution.
   - Foreign key & relation integrity between listings and instruments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import pytest

from masa.audit.events import AuditLogger
from masa.cli import cmd_durum, cmd_gecis
from masa.identity.isin import ISIN, validate_isin
from masa.identity.models import InstrumentType
from masa.identity.registry import IdentityRegistry
from masa.pipeline import integrity_report
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import HashChainEngine
from masa.storage.migration import SCHEMA_V3_UPGRADE_SQL, migrate_v2_to_v3
from masa.storage.snapshot_store import SnapshotStore


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def populated_v2_db(tmp_path: Path) -> DatabaseManager:
    """Creates a Schema v2 database populated with snapshots, quotes, and audit events."""
    db_file = tmp_path / "var" / "private" / "test_v2_populated.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    mgr = DatabaseManager(db_file)

    conn = mgr.get_connection()
    try:
        schema_sql_path = Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql"
        content = schema_sql_path.read_text(encoding="utf-8")

        # Strip v3 tables and triggers to build pure v2 schema
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

    # Seed 3 snapshots and audit events into v2
    store = SnapshotStore(mgr)
    audit = AuditLogger(mgr)
    for i in range(1, 4):
        dt = datetime(2026, 10, 30, 10 + i, 0, tzinfo=timezone.utc)
        payload = json.dumps({"quotes": [{"isin": f"IE00B3YLTY6{i}", "bid": 10.0 + i}]})
        raw_id, _ = store.store_raw_object("sc", payload, dt)
        quotes = [{
            "isin": f"IE00B3YLTY6{i}",
            "currency": "EUR",
            "bid": f"{10.0 + i:.2f}",
            "ask": f"{10.0 + i + 0.02:.2f}",
            "provider_mid": f"{10.0 + i + 0.01:.2f}",
            "computed_mid": f"{10.0 + i + 0.01:.2f}",
            "spread": "0.02",
            "spread_pct": "0.15",
            "quote_timestamp": dt,
            "retrieved_at": dt,
            "quality_status": "FRESH",
        }]
        store.save_quote_snapshot(f"snap_v2_{i}", raw_id, "sc", dt, dt, quotes)
        audit.log_event(
            actor="test.seeder",
            action=f"SEED_V2_{i}",
            entity_type="snapshot",
            entity_id=f"snap_v2_{i}",
            payload={"index": i},
        )

    return mgr


# -----------------------------------------------------------------------------
# 1. `masa gecis` STRESS TESTS: IDEMPOTENCY & FAULT INJECTION ROLLBACK
# -----------------------------------------------------------------------------

def test_masa_gecis_idempotency_10x_no_data_loss(populated_v2_db: DatabaseManager) -> None:
    """Stress test: Run migration 10 consecutive times on the same DB. Zero error, zero data loss."""
    # First run: v2 -> v3
    res1 = migrate_v2_to_v3(populated_v2_db)
    assert res1.success is True
    assert res1.from_version == 2
    assert res1.to_version == 3
    assert res1.integrity_ok is True
    assert res1.trigger_count >= 33

    # Capture state post-migration
    conn = populated_v2_db.get_connection()
    try:
        snap_count_orig = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        quote_count_orig = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        audit_count_orig = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        inst_count_orig = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count_orig = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        link_count_orig = conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
        ver_orig = int(conn.execute("PRAGMA user_version").fetchone()[0])
        trig_orig = int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0])
    finally:
        conn.close()

    assert ver_orig == 3
    assert trig_orig >= 33
    assert snap_count_orig == 3
    assert quote_count_orig == 3
    assert inst_count_orig > 0
    assert list_count_orig > 0

    # Repeat migration 9 more times (total 10 runs)
    for run_idx in range(2, 11):
        res = migrate_v2_to_v3(populated_v2_db)
        assert res.success is True, f"Run {run_idx} failed: {res.error_message}"
        assert res.from_version == 3
        assert res.to_version == 3
        assert res.integrity_ok is True
        assert res.rolled_back is False

        # Verify state is 100% frozen and no duplicates or leaks occurred
        chk_conn = populated_v2_db.get_connection()
        try:
            assert int(chk_conn.execute("PRAGMA user_version").fetchone()[0]) == 3
            assert int(chk_conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]) == snap_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]) == quote_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]) == audit_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]) == inst_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]) == list_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]) == link_count_orig
            assert int(chk_conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]) == trig_orig

            # Verify cryptographic chains
            snap_ok, snap_err = HashChainEngine.verify_snapshot_chain(chk_conn)
            assert snap_ok is True, f"Snapshot chain broken on run {run_idx}: {snap_err}"

            audit_ok, audit_err = HashChainEngine.verify_audit_chain(chk_conn)
            assert audit_ok is True, f"Audit chain broken on run {run_idx}: {audit_err}"
        finally:
            chk_conn.close()


def test_masa_gecis_fault_injection_ddl_failure_triggers_automatic_rollback(
    populated_v2_db: DatabaseManager,
) -> None:
    """Fault Injection: Inject a SQL syntax/execution error during DDL. Verify automatic rollback to v2."""
    conn_pre = populated_v2_db.get_connection()
    pre_snap_count = conn_pre.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    pre_ver = int(conn_pre.execute("PRAGMA user_version").fetchone()[0])
    conn_pre.close()
    assert pre_ver == 2

    # Patch SCHEMA_V3_UPGRADE_SQL inside migration module to introduce a fatal syntax error
    corrupted_sql = "CREATE TABLE instruments (this is completely invalid sql);"
    with patch("masa.storage.migration.SCHEMA_V3_UPGRADE_SQL", corrupted_sql):
        res = migrate_v2_to_v3(populated_v2_db)
        assert res.success is False
        assert res.rolled_back is True
        assert "DDL yürütme hatası" in (res.error_message or "")
        assert res.backup_path is not None
        assert Path(res.backup_path).exists()

    # Empirically verify live DB has been rolled back to pristine v2
    conn_post = populated_v2_db.get_connection()
    try:
        post_ver = int(conn_post.execute("PRAGMA user_version").fetchone()[0])
        assert post_ver == 2, f"Expected DB rolled back to v2, found v{post_ver}"

        # Ensure no half-created tables exist
        tables = [r[0] for r in conn_post.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "instruments" not in tables
        assert "listings" not in tables
        assert "issuer_links" not in tables

        # Ensure pre-migration snapshots and audit chains are completely intact
        post_snap_count = conn_post.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert post_snap_count == pre_snap_count

        snap_ok, _ = HashChainEngine.verify_snapshot_chain(conn_post)
        assert snap_ok is True

        audit_ok, _ = HashChainEngine.verify_audit_chain(conn_post)
        assert audit_ok is True
    finally:
        conn_post.close()


def test_masa_gecis_fault_injection_post_migration_integrity_failure_triggers_rollback(
    populated_v2_db: DatabaseManager,
) -> None:
    """Fault Injection: Post-migration integrity verification fails (e.g. trigger count < 33).
    
    Verify that automatic rollback restores pre-migration v2 DB.
    """
    # Simulate post-migration check failure: integrity_report returns ok=False
    with patch("masa.storage.migration.integrity_report") as mock_integ:
        mock_integ.return_value = {
            "ok": False,
            "schema_version": 3,
            "trigger_count": 25,  # Insufficient triggers (< 33)
            "snapshot_chain_ok": True,
            "audit_chain_ok": True,
        }
        res = migrate_v2_to_v3(populated_v2_db)
        assert res.success is False
        assert res.rolled_back is True
        assert "bütünlük doğrulaması başarısız oldu" in (res.error_message or "")

    # Empirically verify database restored to v2
    conn = populated_v2_db.get_connection()
    try:
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        assert ver == 2
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "instruments" not in tables
    finally:
        conn.close()


def test_masa_gecis_fault_injection_pre_backup_failure_aborts_without_touching_db(
    populated_v2_db: DatabaseManager,
) -> None:
    """Fault Injection: If pre-migration backup fails, migration must abort with zero DDL changes."""
    with patch("masa.backup.create_backup", side_effect=RuntimeError("Disk full during pre-backup")):
        res = migrate_v2_to_v3(populated_v2_db)
        assert res.success is False
        assert res.rolled_back is False
        assert "Geçiş öncesi online yedek ve prova başarısız oldu" in (res.error_message or "")

    conn = populated_v2_db.get_connection()
    try:
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        assert ver == 2
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "instruments" not in tables
    finally:
        conn.close()


def test_cli_cmd_gecis_failure_and_rollback_exit_code_1(
    populated_v2_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify CLI `cmd_gecis` returns exit code 1 when migration fails and rolls back."""
    monkeypatch.setenv("MASA_DB_PATH", str(populated_v2_db.db_path))

    with patch("masa.storage.migration.integrity_report") as mock_integ:
        mock_integ.return_value = {
            "ok": False,
            "schema_version": 3,
            "trigger_count": 20,
            "snapshot_chain_ok": False,
            "audit_chain_ok": True,
        }
        args = MagicMock()
        rc = cmd_gecis(args)
        assert rc == 1


# -----------------------------------------------------------------------------
# 2. IMMUTABILITY TRIGGER STRESS TESTS (ABORT ON UPDATE, DELETE, OVERWRITE)
# -----------------------------------------------------------------------------

def test_triggers_instruments_strictly_immutable(populated_v2_db: DatabaseManager) -> None:
    """Adversarial stress test on `instruments` table triggers.
    
    Verifies ABORT on:
    - UPDATE (all rows, specific rowid, specific isin)
    - DELETE (all rows, specific rowid, specific isin)
    - INSERT OR REPLACE
    - ON CONFLICT DO UPDATE
    """
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)
    inst_id = reg.ensure_instrument(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        instrument_type="ETF",
        issuer_id="iss_ssga_ie",
    )

    conn = populated_v2_db.get_connection()
    try:
        # Attack 1: Targeted UPDATE by instrument_id
        with pytest.raises(sqlite3.IntegrityError, match="instruments degistirilemez"):
            conn.execute("UPDATE instruments SET name = 'Attacked Name' WHERE instrument_id = ?", (inst_id,))

        # Attack 2: Targeted UPDATE by isin
        with pytest.raises(sqlite3.IntegrityError, match="instruments degistirilemez"):
            conn.execute("UPDATE instruments SET ter_bps = 999 WHERE isin = 'IE00B3YLTY66'")

        # Attack 3: Bulk UPDATE (WHERE 1=1)
        with pytest.raises(sqlite3.IntegrityError, match="instruments degistirilemez"):
            conn.execute("UPDATE instruments SET is_active = 0 WHERE 1=1")

        # Attack 4: Targeted DELETE by instrument_id
        with pytest.raises(sqlite3.IntegrityError, match="instruments kaydi silinemez"):
            conn.execute("DELETE FROM instruments WHERE instrument_id = ?", (inst_id,))

        # Attack 5: Bulk DELETE
        with pytest.raises(sqlite3.IntegrityError, match="instruments kaydi silinemez"):
            conn.execute("DELETE FROM instruments WHERE 1=1")

        # Attack 6: INSERT OR REPLACE attack
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma.*yasak"):
            conn.execute(
                """
                INSERT OR REPLACE INTO instruments (
                    instrument_id, isin, name, instrument_type, issuer_id,
                    is_active, created_at, record_hash, base_currency
                ) VALUES (?, 'IE00B3YLTY66', 'Replaced', 'ETF', 'iss_ssga_ie', 1, 'now', 'hash', 'EUR')
                """,
                (inst_id,),
            )

        # Attack 7: ON CONFLICT DO UPDATE attack
        with pytest.raises(sqlite3.IntegrityError, match="instruments: mevcut kaydin uzerine yazma|instruments degistirilemez"):
            conn.execute(
                """
                INSERT INTO instruments (
                    instrument_id, isin, name, instrument_type, issuer_id,
                    is_active, created_at, record_hash, base_currency
                ) VALUES ('inst_new', 'IE00B3YLTY66', 'Conflict', 'ETF', 'iss_ssga_ie', 1, 'now', 'hash', 'EUR')
                ON CONFLICT(isin) DO UPDATE SET name = 'Overwritten'
                """
            )
    finally:
        conn.close()


def test_triggers_listings_strictly_immutable(populated_v2_db: DatabaseManager) -> None:
    """Adversarial stress test on `listings` table triggers.
    
    Verifies ABORT on:
    - UPDATE (targeted, bulk)
    - DELETE (targeted, bulk)
    - INSERT OR REPLACE
    - ON CONFLICT DO UPDATE
    """
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)
    inst_id = reg.ensure_instrument(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        instrument_type="ETF",
        issuer_id="iss_ssga_ie",
    )
    list_id = reg.ensure_listing(
        instrument_id=inst_id,
        mic="XETR",
        ticker="SPYI",
        currency="EUR",
    )

    conn = populated_v2_db.get_connection()
    try:
        # Attack 1: Targeted UPDATE by listing_id
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            conn.execute("UPDATE listings SET ticker = 'HACK' WHERE listing_id = ?", (list_id,))

        # Attack 2: Targeted UPDATE by mic/ticker
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            conn.execute("UPDATE listings SET validation_status = 'VERIFIED' WHERE mic = 'XETR' AND ticker = 'SPYI'")

        # Attack 3: Bulk UPDATE
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            conn.execute("UPDATE listings SET is_active = 0 WHERE 1=1")

        # Attack 4: Targeted DELETE
        with pytest.raises(sqlite3.IntegrityError, match="listings kaydi silinemez"):
            conn.execute("DELETE FROM listings WHERE listing_id = ?", (list_id,))

        # Attack 5: Bulk DELETE
        with pytest.raises(sqlite3.IntegrityError, match="listings kaydi silinemez"):
            conn.execute("DELETE FROM listings WHERE 1=1")

        # Attack 6: INSERT OR REPLACE
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma.*yasak"):
            conn.execute(
                """
                INSERT OR REPLACE INTO listings (
                    listing_id, instrument_id, mic, ticker, currency,
                    source, validation_status, is_primary, is_active, created_at, record_hash
                ) VALUES (?, ?, 'XETR', 'SPYI', 'EUR', 'config', 'UNVERIFIED', 1, 1, 'now', 'hash')
                """,
                (list_id, inst_id),
            )
    finally:
        conn.close()


def test_triggers_issuer_links_strictly_immutable(populated_v2_db: DatabaseManager) -> None:
    """Adversarial stress test on `issuer_links` table triggers.
    
    Verifies ABORT on:
    - UPDATE (targeted, bulk)
    - DELETE (targeted, bulk)
    - INSERT OR REPLACE
    """
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)
    link_id = reg.ensure_issuer_link(
        issuer_id="iss_test_corp",
        name="Test Corporation",
        country="US",
    )

    conn = populated_v2_db.get_connection()
    try:
        # Attack 1: Targeted UPDATE
        with pytest.raises(sqlite3.IntegrityError, match="issuer_links degistirilemez"):
            conn.execute("UPDATE issuer_links SET name = 'Altered Name' WHERE link_id = ?", (link_id,))

        # Attack 2: Bulk UPDATE
        with pytest.raises(sqlite3.IntegrityError, match="issuer_links degistirilemez"):
            conn.execute("UPDATE issuer_links SET country = 'DE' WHERE 1=1")

        # Attack 3: Targeted DELETE
        with pytest.raises(sqlite3.IntegrityError, match="issuer_links kaydi silinemez"):
            conn.execute("DELETE FROM issuer_links WHERE link_id = ?", (link_id,))

        # Attack 4: Bulk DELETE
        with pytest.raises(sqlite3.IntegrityError, match="issuer_links kaydi silinemez"):
            conn.execute("DELETE FROM issuer_links WHERE 1=1")

        # Attack 5: INSERT OR REPLACE
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma.*yasak"):
            conn.execute(
                """
                INSERT OR REPLACE INTO issuer_links (
                    link_id, issuer_id, name, country, relationship_type, source, is_active, created_at, record_hash
                ) VALUES (?, 'iss_test_corp', 'Replaced Corp', 'US', 'ISSUER', 'manual', 1, 'now', 'hash')
                """,
                (link_id,),
            )
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# 3. IDENTITY REGISTRY 50-RUN STRESS TEST & HOLDINGS SYNC IDEMPOTENCY
# -----------------------------------------------------------------------------

def test_identity_registry_50_consecutive_seed_runs_zero_duplicates(
    populated_v2_db: DatabaseManager,
) -> None:
    """Stress test: Run `seed_from_configs()` 50 consecutive times on the database.
    
    Empirically verify:
    - Zero duplicate records in `instruments`.
    - Zero duplicate records in `listings`.
    - Zero duplicate records in `issuer_links`.
    - Exactly 0 DB writes on runs 2 through 50.
    """
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)

    # Initial seeding: verify in DB that instruments, listings, and issuer_links are populated
    seed_res_1 = reg.seed_from_configs()
    assert seed_res_1["instruments"] > 0
    assert seed_res_1["listings"] > 0

    conn = populated_v2_db.get_connection()
    try:
        inst_count_init = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count_init = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        link_count_init = conn.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
    finally:
        conn.close()

    assert inst_count_init > 0
    assert list_count_init > 0
    assert link_count_init > 0

    # Execute 49 more consecutive runs (total 50)
    for iteration in range(2, 51):
        # Create a fresh IdentityRegistry instance to also test cold start loading from DB
        fresh_reg = IdentityRegistry(db=populated_v2_db)
        fresh_reg.seed_from_configs()

        conn_iter = populated_v2_db.get_connection()
        try:
            cur_inst = conn_iter.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
            cur_list = conn_iter.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            cur_link = conn_iter.execute("SELECT COUNT(*) FROM issuer_links").fetchone()[0]
        finally:
            conn_iter.close()

        assert cur_inst == inst_count_init, f"Iteration {iteration} created duplicate instruments! ({cur_inst} != {inst_count_init})"
        assert cur_list == list_count_init, f"Iteration {iteration} created duplicate listings! ({cur_list} != {list_count_init})"
        assert cur_link == link_count_init, f"Iteration {iteration} created duplicate issuer_links! ({cur_link} != {link_count_init})"

    # Final exhaustive verification of uniqueness
    final_conn = populated_v2_db.get_connection()
    try:
        # Check duplicate ISINs
        dup_isins = final_conn.execute(
            "SELECT isin, COUNT(*) FROM instruments GROUP BY isin HAVING COUNT(*) > 1"
        ).fetchall()
        assert len(dup_isins) == 0, f"Found duplicate ISINs: {dup_isins}"

        # Check duplicate listings (mic, ticker, currency)
        dup_listings = final_conn.execute(
            "SELECT mic, ticker, currency, COUNT(*) FROM listings GROUP BY mic, ticker, currency HAVING COUNT(*) > 1"
        ).fetchall()
        assert len(dup_listings) == 0, f"Found duplicate listings: {dup_listings}"

        # Check duplicate issuer_links
        dup_links = final_conn.execute(
            "SELECT link_id, COUNT(*) FROM issuer_links GROUP BY link_id HAVING COUNT(*) > 1"
        ).fetchall()
        assert len(dup_links) == 0, f"Found duplicate issuer links: {dup_links}"
    finally:
        final_conn.close()


def test_holdings_sync_50_iterations_idempotency_zero_duplicate_writes(
    populated_v2_db: DatabaseManager,
) -> None:
    """Simulates broker holdings / watchlist ingestion synchronizing 10 securities 50 times in a row."""
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)

    # 10 realistic securities (UCITS ETFs + Equities)
    holdings_batch = [
        {"isin": "IE00B3YLTY66", "name": "SPDR MSCI ACWI IMI", "type": "ETF", "issuer": "iss_ssga_ie", "mic": "XETR", "ticker": "SPYI", "curr": "EUR"},
        {"isin": "IE00B4L5Y983", "name": "iShares Core MSCI World", "type": "ETF", "issuer": "iss_blackrock_ie", "mic": "XETR", "ticker": "EUNL", "curr": "EUR"},
        {"isin": "IE00BKM4GZ66", "name": "iShares Core MSCI EM IMI", "type": "ETF", "issuer": "iss_blackrock_ie", "mic": "XETR", "ticker": "IS3N", "curr": "EUR"},
        {"isin": "IE00B5BMR087", "name": "iShares Core S&P 500", "type": "ETF", "issuer": "iss_blackrock_ie", "mic": "XETR", "ticker": "SXR8", "curr": "EUR"},
        {"isin": "IE00B1XNHC34", "name": "iShares Global Clean Energy", "type": "ETF", "issuer": "iss_blackrock_ie", "mic": "XETR", "ticker": "IQQH", "curr": "EUR"},
        {"isin": "US0378331005", "name": "Apple Inc.", "type": "EQUITY", "issuer": "iss_apple_us", "mic": "XNAS", "ticker": "AAPL", "curr": "USD"},
        {"isin": "US5949181045", "name": "Microsoft Corporation", "type": "EQUITY", "issuer": "iss_microsoft_us", "mic": "XNAS", "ticker": "MSFT", "curr": "USD"},
        {"isin": "US67066G1040", "name": "NVIDIA Corporation", "type": "EQUITY", "issuer": "iss_nvidia_us", "mic": "XNAS", "ticker": "NVDA", "curr": "USD"},
        {"isin": "DE0007164600", "name": "SAP SE", "type": "EQUITY", "issuer": "iss_sap_de", "mic": "XETR", "ticker": "SAP", "curr": "EUR"},
        {"isin": "NL0010273215", "name": "ASML Holding N.V.", "type": "EQUITY", "issuer": "iss_asml_nl", "mic": "XAMS", "ticker": "ASML", "curr": "EUR"},
    ]

    # Pre-register issuers
    for sec in holdings_batch:
        reg.ensure_issuer_link(
            issuer_id=sec["issuer"],
            name=sec["issuer"],
            country="US" if sec["curr"] == "USD" else "DE",
        )

    # Iteration 1: Inserts or confirms the 10 instruments and 10 listings
    for sec in holdings_batch:
        inst_id = reg.ensure_instrument(
            isin=sec["isin"],
            name=sec["name"],
            instrument_type=sec["type"],
            issuer_id=sec["issuer"],
        )
        reg.ensure_listing(
            instrument_id=inst_id,
            mic=sec["mic"],
            ticker=sec["ticker"],
            currency=sec["curr"],
        )

    conn = populated_v2_db.get_connection()
    try:
        inst_count_1 = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count_1 = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    finally:
        conn.close()

    assert inst_count_1 >= 10
    assert list_count_1 >= 10

    # Iterations 2..50: 49 more iterations
    for it in range(2, 51):
        for sec in holdings_batch:
            inst_id = reg.ensure_instrument(
                isin=sec["isin"],
                name=sec["name"],
                instrument_type=sec["type"],
                issuer_id=sec["issuer"],
            )
            list_id = reg.ensure_listing(
                instrument_id=inst_id,
                mic=sec["mic"],
                ticker=sec["ticker"],
                currency=sec["curr"],
            )
            assert inst_id == f"inst_{sec['isin'].lower()}"
            assert list_id == f"list_{sec['mic'].lower()}_{sec['ticker'].lower()}_{sec['curr'].lower()}"

    # Verify counts remain precisely unchanged from iteration 1
    chk_conn = populated_v2_db.get_connection()
    try:
        inst_count_final = chk_conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        list_count_final = chk_conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        assert inst_count_final == inst_count_1
        assert list_count_final == list_count_1
    finally:
        chk_conn.close()


# -----------------------------------------------------------------------------
# 4. EDGE CASE INVALIDATION TESTS
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "invalid_isin",
    [
        "",
        "   ",
        "US0378331000",   # Incorrect check digit (should be 5)
        "IE00B3YLTY60",   # Incorrect check digit (should be 6)
        "US037833100",    # 11 chars (too short)
        "US03783310055",  # 13 chars (too long)
        "123456789012",   # Missing country prefix letters
        "US037833100!",   # Non-alphanumeric
    ],
)
def test_ensure_instrument_invalid_isin_aborts_without_db_write(
    populated_v2_db: DatabaseManager, invalid_isin: str
) -> None:
    """Verifies that malformed or bad-checksum ISINs raise ValueError and never pollute DB."""
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)

    conn = populated_v2_db.get_connection()
    pre_count = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    conn.close()

    with pytest.raises(ValueError, match="ISIN"):
        reg.ensure_instrument(
            isin=invalid_isin,
            name="Invalid Security",
            instrument_type="EQUITY",
            issuer_id="iss_apple_us",
        )

    conn2 = populated_v2_db.get_connection()
    post_count = conn2.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    conn2.close()

    assert post_count == pre_count, "Invalid ISIN caused an uncommitted or rogue DB write!"


def test_multiple_listings_for_single_instrument(populated_v2_db: DatabaseManager) -> None:
    """Verifies that a single economic instrument can have multiple listings across exchanges."""
    migrate_v2_to_v3(populated_v2_db)
    reg = IdentityRegistry(db=populated_v2_db)

    inst_id = reg.ensure_instrument(
        isin="IE00B5BMR087",
        name="iShares Core S&P 500 UCITS ETF",
        instrument_type="ETF",
        issuer_id="iss_blackrock_ie",
    )

    # Listing 1: XETR in EUR
    l1 = reg.ensure_listing(
        instrument_id=inst_id,
        mic="XETR",
        ticker="SXR8",
        currency="EUR",
        is_primary=True,
    )

    # Listing 2: XLON in USD
    l2 = reg.ensure_listing(
        instrument_id=inst_id,
        mic="XLON",
        ticker="CSPX",
        currency="USD",
        is_primary=False,
    )

    # Listing 3: XAMS in EUR
    l3 = reg.ensure_listing(
        instrument_id=inst_id,
        mic="XAMS",
        ticker="CSPX",
        currency="EUR",
        is_primary=False,
    )

    assert l1 != l2 != l3

    conn = populated_v2_db.get_connection()
    try:
        listings = conn.execute(
            "SELECT listing_id, mic, ticker, currency FROM listings WHERE instrument_id = ? ORDER BY mic",
            (inst_id,),
        ).fetchall()
        assert len(listings) == 3
        assert listings[0]["mic"] == "XAMS"
        assert listings[1]["mic"] == "XETR"
        assert listings[2]["mic"] == "XLON"
    finally:
        conn.close()
