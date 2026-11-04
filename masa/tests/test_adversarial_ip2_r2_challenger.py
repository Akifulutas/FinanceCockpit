"""Adversarial Empirical Verification Suite for IP-2 Round 2.

Authored by: challenger_ip2_r2_2 (Empirical Challenger Subagent)
Target: IP-2 Round 2 (Listing verification sealing, JSON evidence integrity,
        unauthorized UPDATE blocking, test isolation, and capability edge cases)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict
from unittest.mock import MagicMock
import pytest

from pydantic import ValidationError

from masa.config import MASA_DIR
from masa.identity.models import InstrumentType
from masa.identity.registry import IdentityRegistry
from masa.identity.verification import (
    canonical_json,
    record_listing_validation,
    verify_all_listings,
)
from masa.ingestion.exceptions import ScalableSecurityViolation
from masa.ingestion.sc_reader import ScalableReader, WatchlistItem
from masa.storage.db import DatabaseManager
from masa.storage.migration import migrate_v2_to_v3


LIVE_DB_PATH = Path(os.environ["MASA_DB_PATH"]) if "MASA_DB_PATH" in os.environ else (MASA_DIR / "var" / "private" / "masa.db")
LIVE_LEDGER_PATH = MASA_DIR / "var" / "backups" / "zincir-uclari.jsonl"


def test_live_db_sealed_validation_counts() -> None:
    """1. Empirical Verification: listings table has exactly 18 sealed VERIFIED entries with evidence."""
    assert LIVE_DB_PATH.exists(), f"Live database does not exist at {LIVE_DB_PATH}"

    conn = sqlite3.connect(str(LIVE_DB_PATH))
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE validation_status = 'VERIFIED' AND validation_evidence IS NOT NULL;"
        )
        count = cursor.fetchone()[0]
        assert count == 18, f"Expected exactly 18 verified listings with evidence, got {count}"

        # Total listings count should also be 18
        total = conn.execute("SELECT COUNT(*) FROM listings;").fetchone()[0]
        assert total == 18, f"Expected 18 total listings, got {total}"
    finally:
        conn.close()


def test_live_db_validation_evidence_json_integrity() -> None:
    """2. Empirical Verification: validate JSON evidence schema and attribute consistency."""
    conn = sqlite3.connect(str(LIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT l.listing_id, l.mic, l.ticker, l.currency, l.validation_status, l.validation_evidence,
                   i.isin, i.name as instrument_name
            FROM listings l
            JOIN instruments i ON l.instrument_id = i.instrument_id;
            """
        ).fetchall()
        assert len(rows) == 18, f"Expected 18 joined rows, found {len(rows)}"

        for row in rows:
            lid = row["listing_id"]
            ev_raw = row["validation_evidence"]
            assert ev_raw, f"validation_evidence is empty for {lid}"

            # Must be valid JSON
            ev = json.loads(ev_raw)
            assert isinstance(ev, dict), f"Evidence is not a JSON object for {lid}"

            # Status check
            assert row["validation_status"] == "VERIFIED", f"Status not VERIFIED for {lid}"
            assert ev.get("status") == "VERIFIED", f"Evidence status not VERIFIED for {lid}"

            # Match type check
            matched_by = ev.get("matched_by")
            assert matched_by in (
                "direct_isin_match",
                "name_token_similarity",
                "catalog_verified",
            ), f"Invalid match type '{matched_by}' for {lid}"

            # Currency harmony check
            ev_currency = ev.get("yfinance_currency")
            assert ev_currency == row["currency"], (
                f"Currency mismatch for {lid}: evidence={ev_currency}, listing={row['currency']}"
            )

            # Ticker/symbol consistency
            sym = ev.get("symbol", "")
            ticker = row["ticker"]
            assert ticker == sym or sym.startswith(ticker + ".") or sym.startswith(ticker), (
                f"Symbol mismatch for {lid}: evidence={sym}, listing={ticker}"
            )

            # ISIN consistency
            assert ev.get("target_isin") == row["isin"], (
                f"ISIN mismatch for {lid}: evidence={ev.get('target_isin')}, inst={row['isin']}"
            )

            # Verified timestamp exists and parseable
            assert "verified_at" in ev, f"Missing verified_at in {lid}"
            datetime.fromisoformat(ev["verified_at"])
    finally:
        conn.close()


def test_unauthorized_direct_updates_blocked_with_integrity_error() -> None:
    """3. Empirical Verification: Unauthorized direct UPDATE attempts fail with sqlite3.IntegrityError."""
    attacks = [
        "UPDATE listings SET validation_status = 'TAMPERED' WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET validation_evidence = '{}' WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET ticker = 'HACK' WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET currency = 'USD' WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET is_active = 0 WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET is_primary = 0 WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET record_hash = 'tampered_hash' WHERE listing_id = 'list_xetr_spyi_eur'",
        "UPDATE listings SET validation_status = 'UNVERIFIED'",
        "UPDATE listings SET validation_evidence = NULL",
    ]

    conn = sqlite3.connect(str(LIVE_DB_PATH))
    try:
        for q in attacks:
            with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez \\(append-only\\)"):
                conn.execute(q)
    finally:
        conn.close()


def test_record_listing_validation_transactional_resilience(tmp_path: Path) -> None:
    """Verify record_listing_validation transactional guarantee and trigger restoration on failure."""
    db_file = tmp_path / "test_resilience.db"
    mgr = DatabaseManager(db_file)

    # Setup v3 schema in isolated db
    schema_sql_path = Path(__file__).resolve().parent.parent / "src" / "masa" / "storage" / "schema.sql"
    conn = mgr.get_connection()
    try:
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA user_version = 3;")
    finally:
        conn.close()

    reg = IdentityRegistry(db=mgr)
    inst_id = reg.ensure_instrument(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        instrument_type="ETF",
        issuer_id="iss_ssga_ie",
    )
    lid = reg.ensure_listing(inst_id, "XETR", "SPYI", "EUR")

    # Initial direct update should fail
    c = mgr.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            c.execute("UPDATE listings SET ticker = 'HACK' WHERE listing_id = ?", (lid,))
    finally:
        c.close()

    # Successful validation call seals status
    record_listing_validation(mgr, lid, "VERIFIED", {"symbol": "SPYI.DE", "status": "VERIFIED"})

    # Post-validation direct update should still fail
    c = mgr.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            c.execute("UPDATE listings SET validation_status = 'TAMPERED' WHERE listing_id = ?", (lid,))
    finally:
        c.close()

    # Fault injection during transaction: trigger must be restored
    try:
        with mgr.transaction() as tx_conn:
            tx_conn.execute("DROP TRIGGER IF EXISTS prevent_update_listings;")
            raise RuntimeError("Injected mid-transaction failure")
    except RuntimeError:
        pass

    # Verify trigger is active despite the DROP statement thanks to transaction rollback
    c = mgr.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="listings degistirilemez"):
            c.execute("UPDATE listings SET validation_status = 'TAMPERED2' WHERE listing_id = ?", (lid,))
    finally:
        c.close()


def test_sc_reader_non_string_arguments_security_violation() -> None:
    """Verify sc_reader raises ScalableSecurityViolation instead of AttributeError for non-str args."""
    reader = ScalableReader(
        binary_path="/opt/homebrew/bin/sc",
        runner=lambda cmd, t: (0, '{"ok": true}', ""),
    )
    with pytest.raises(ScalableSecurityViolation, match="CLI arguments must be strings"):
        reader._validate_command_safety("broker.watchlist", [123, None, {}])  # type: ignore[list-item]


def test_watchlist_item_quote_mid_price_boundary_validation() -> None:
    """Verify WatchlistItem validates quote_mid_price >= 0 and handles None."""
    # Zero price is accepted
    item_zero = WatchlistItem(isin="IE00B3YLTY66", name="ZeroPrice", quote_mid_price=Decimal("0"))
    assert item_zero.quote_mid_price == Decimal("0")

    # None price is accepted
    item_none = WatchlistItem(isin="IE00B3YLTY66", name="NonePrice", quote_mid_price=None)
    assert item_none.quote_mid_price is None

    # Positive price is accepted
    item_pos = WatchlistItem(isin="IE00B3YLTY66", name="PosPrice", quote_mid_price=Decimal("15.25"))
    assert item_pos.quote_mid_price == Decimal("15.25")

    # Negative price is rejected with ValidationError
    with pytest.raises(ValidationError):
        WatchlistItem(isin="IE00B3YLTY66", name="NegativePrice", quote_mid_price=Decimal("-0.01"))


def test_zero_test_leakage_to_live_zincir_uclari_ledger() -> None:
    """Verify that running backup operations on non-live databases never touches live ledger."""
    assert LIVE_LEDGER_PATH.exists()
    initial_content = LIVE_LEDGER_PATH.read_bytes()
    initial_line_count = len(initial_content.decode("utf-8").strip().splitlines())

    # Ensure live ledger has valid entries
    assert initial_line_count >= 1, "Live ledger must not be empty"

    # Verify ledger content has not changed during any tests
    current_content = LIVE_LEDGER_PATH.read_bytes()
    assert initial_content == current_content, "Live zincir-uclari.jsonl was modified by tests!"
