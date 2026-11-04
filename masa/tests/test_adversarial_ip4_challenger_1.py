"""Adversarial Challenge Test Suite for Work Package 4 (İP-4: ETF Sepeti Yükleyicisi).

Authored by challenger_ip4_1 (Empirical Challenger Agent).
Adversarially stress-tests:
1. Corrupted/Malformed CSV & XLSX files (truncated files, binary garbage, missing headers, 100 empty lines before header, malformed numbers).
2. Weight Anomaly Attacks: Weights totaling > 1.0001 (e.g. 101%, 1.0002, 200%) MUST raise HoldingsValidationError and never insert into DB.
3. Negative Weights & Asset Classes: Negative equity weights vs valid negative derivative weights (e.g. currency forwards).
4. Path Traversal & File System Safety: Testing path traversal inputs, symlinks, or unauthorized locations.
5. Idempotency & Duplicate Re-Upload: Uploading identical file twice produces DUPLICATE_SKIPPED without duplicate DB rows or trigger aborts.
6. Immutability Trigger Stress: Attempting direct UPDATE or DELETE on `holdings_sets` and `holding_items` must trigger ABORT.
7. Fund ISIN Validation: Testing invalid fund ISINs (non-12-char, non-alphanumeric, Luhn mod-10 violations).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import pytest

import openpyxl

from masa.holdings.ishares_parser import ISharesParser, clean_decimal
from masa.holdings.loader import HoldingsLoader
from masa.holdings.models import AssetClass, HoldingsValidationError
from masa.holdings.spdr_parser import SPDRParser
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_holding_item_hash, compute_holdings_set_hash


# =============================================================================
# Helper Fixtures & Generators
# =============================================================================

def create_corrupt_spdr_xlsx(total_weight_pct: float = 150.0) -> bytes:
    """Generate SPDR XLSX with anomalous weights."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SPDR Test Fund"])
    ws.append(["Holdings as of 20-Oct-2026"])
    ws.append(["Ticker", "Name", "Identifier", "Weight (%)"])
    ws.append(["AAPL", "Apple Inc.", "US0378331005", total_weight_pct / 2])
    ws.append(["MSFT", "Microsoft Corp.", "US5949181045", total_weight_pct / 2])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# =============================================================================
# 1. Corrupted & Malformed CSV & XLSX Files
# =============================================================================

class TestCorruptedAndMalformedFiles:
    """Adversarial stress-testing of file corruption and malformed payloads."""

    def test_empty_and_whitespace_only_csv(self):
        """Empty or whitespace-only files must be rejected immediately."""
        with pytest.raises(HoldingsValidationError, match="boş"):
            ISharesParser.parse("", isin="IE00BKM4GZ66")

        with pytest.raises(HoldingsValidationError, match="boş"):
            ISharesParser.parse("   \n\n\t  \n  ", isin="IE00BKM4GZ66")

        with pytest.raises(HoldingsValidationError, match="boş"):
            SPDRParser.parse("", isin="IE00B3YLTY66")

    def test_single_byte_and_truncated_files(self):
        """Single-byte or truncated files must raise HoldingsValidationError."""
        with pytest.raises(HoldingsValidationError):
            ISharesParser.parse("x", isin="IE00BKM4GZ66")

        with pytest.raises(HoldingsValidationError):
            SPDRParser.parse("x", isin="IE00B3YLTY66")

    def test_binary_garbage_payload(self):
        """Random binary garbage must not cause unhandled crashes or code execution."""
        garbage_bytes = b"\x00\xff\xfe\x01\x88\x99\xde\xad\xbe\xef" * 50

        with pytest.raises(HoldingsValidationError):
            ISharesParser.parse(garbage_bytes, isin="IE00BKM4GZ66")

        with pytest.raises(Exception):
            # SPDRParser with .xlsx extension should safely fail on corrupt zip/xlsx
            SPDRParser.parse(garbage_bytes, isin="IE00B3YLTY66", source_file_name="corrupt.xlsx")

    def test_missing_required_headers(self):
        """Files missing essential headers (Name or Weight) must be rejected."""
        # Missing Weight
        csv_no_weight = "Ticker;Name;ISIN;Price\nAAPL;Apple Inc.;US0378331005;150.00\n"
        with pytest.raises(HoldingsValidationError, match="başlık satırı"):
            ISharesParser.parse(csv_no_weight, isin="IE00BKM4GZ66")

        # Missing Name
        csv_no_name = "Ticker;ISIN;Gewichtung (%)\nAAPL;US0378331005;5,00\n"
        with pytest.raises(HoldingsValidationError, match="başlık satırı"):
            ISharesParser.parse(csv_no_name, isin="IE00BKM4GZ66")

    def test_100_empty_lines_before_header_csv(self):
        """100 empty lines before the actual CSV header must be handled gracefully."""
        csv_data = "\n" * 100 + (
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;5,00\n"
        )
        parsed = ISharesParser.parse(csv_data, isin="IE00BKM4GZ66")
        assert parsed.total_records == 1
        assert parsed.items[0].constituent_ticker == "AAPL"
        assert parsed.items[0].weight_pct == Decimal("0.05")

    def test_malformed_numbers_handling(self):
        """Special and corrupt numbers (NaN, Infinity, multi-commas) must not corrupt state."""
        # clean_decimal returns None for non-finite values
        assert clean_decimal("NaN") is None
        assert clean_decimal("Infinity") is None
        assert clean_decimal("-Infinity") is None
        assert clean_decimal("1.2.3.4") is None
        assert clean_decimal("invalid_num") is None
        assert clean_decimal(None) is None

        # When all items have malformed weights, parser must raise HoldingsValidationError
        csv_nan = (
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;NaN\n"
            "MSFT;Microsoft Corp.;US5949181045;Infinity\n"
        )
        with pytest.raises(HoldingsValidationError, match="geçerli sepet satırı bulunamadı"):
            ISharesParser.parse(csv_nan, isin="IE00BKM4GZ66")


# =============================================================================
# 2. Weight Anomaly Attacks (> 1.0001)
# =============================================================================

class TestWeightAnomalyAttacks:
    """Adversarial attacks attempting to inflate or inject weights exceeding 1.0001."""

    def test_ishares_weights_totaling_101_percent(self):
        """101% total weight must raise HoldingsValidationError."""
        csv_101 = (
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;51,00\n"
            "MSFT;Microsoft Corp.;US5949181045;50,00\n"
        )
        with pytest.raises(HoldingsValidationError, match="1.0001"):
            ISharesParser.parse(csv_101, isin="IE00BKM4GZ66")

    def test_ishares_weights_totaling_1_0002(self):
        """100.02% (1.0002) total weight must raise HoldingsValidationError."""
        csv_100_02 = (
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;50,01\n"
            "MSFT;Microsoft Corp.;US5949181045;50,01\n"
        )
        with pytest.raises(HoldingsValidationError, match="1.0001"):
            ISharesParser.parse(csv_100_02, isin="IE00BKM4GZ66")

    def test_ishares_weights_totaling_200_percent(self):
        """200% total weight must raise HoldingsValidationError."""
        csv_200 = (
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;100,00\n"
            "MSFT;Microsoft Corp.;US5949181045;100,00\n"
        )
        with pytest.raises(HoldingsValidationError, match="1.0001"):
            ISharesParser.parse(csv_200, isin="IE00BKM4GZ66")

    def test_spdr_xlsx_weight_anomaly_rejected(self):
        """SPDR XLSX with 150% weight must raise HoldingsValidationError."""
        xlsx_bytes = create_corrupt_spdr_xlsx(total_weight_pct=150.0)
        with pytest.raises(HoldingsValidationError, match="1.0001"):
            SPDRParser.parse(xlsx_bytes, isin="IE00B3YLTY66")

    def test_inflated_basket_never_inserted_into_db(self, tmp_path: Path):
        """Baskets with total_weight > 1.0001 must NEVER insert any rows into holdings_sets or holding_items."""
        db_file = tmp_path / "test_anomaly.db"
        db = DatabaseManager(db_file)
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        bad_file = tmp_path / "inflated.csv"
        bad_file.write_text(
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;70,00\n"
            "MSFT;Microsoft Corp.;US5949181045;40,00\n",
            encoding="utf-8",
        )

        res = loader.ingest_file(bad_file, isin="IE00BKM4GZ66")
        assert res.success is False
        assert res.status == "FAILED"
        assert "1.0001" in str(res.error_message)

        # Check DB: must be 0 rows
        conn = db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) FROM holdings_sets").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM holding_items").fetchone()[0] == 0
        finally:
            conn.close()

        # Check rejected directory has .err file
        err_files = list(loader.rejected_dir.glob("*.err"))
        assert len(err_files) == 1
        assert "1.0001" in err_files[0].read_text()


# =============================================================================
# 3. Negative Weights & Asset Classes
# =============================================================================

class TestNegativeWeightsAndAssetClasses:
    """Stress tests on negative weights across equity vs derivative/cash asset classes."""

    def test_valid_negative_derivative_weight_accepted(self):
        """Derivatives with negative weights (short positions, futures, forwards) must be accepted."""
        csv_data = (
            "Ticker;Name;ISIN;Gewichtung (%);Assetklasse\n"
            "AAPL;Apple Inc.;US0378331005;5,00;Aktien\n"
            "EUR_FWD;EUR/USD FWD 2026;;-0,50;Derivate\n"
        )
        parsed = ISharesParser.parse(csv_data, isin="IE00BKM4GZ66")
        assert parsed.total_records == 2
        fwd_item = [i for i in parsed.items if i.asset_class == AssetClass.DERIVATIVE.value][0]
        assert fwd_item.weight_pct == Decimal("-0.0050")
        assert parsed.total_derivative_weight == Decimal("-0.0050")

    def test_valid_negative_cash_offset_accepted(self):
        """Cash offset / collateral liabilities with negative weight must be classified as CASH."""
        csv_data = (
            "Ticker;Name;ISIN;Gewichtung (%);Assetklasse\n"
            "AAPL;Apple Inc.;US0378331005;5,00;Aktien\n"
            "CASH;Cash Offset USD;;-0,20;Barmittel\n"
        )
        parsed = ISharesParser.parse(csv_data, isin="IE00BKM4GZ66")
        assert parsed.total_records == 2
        cash_item = [i for i in parsed.items if i.asset_class == AssetClass.CASH.value][0]
        assert cash_item.weight_pct == Decimal("-0.0020")
        assert parsed.total_cash_weight == Decimal("-0.0020")

    def test_negative_equity_weight_must_be_rejected(self):
        """Physical equities in long UCITS ETFs cannot have negative weights.

        CHALLENGE: If an equity line has negative weight, this indicates corrupted data
        or an invalid short equity position in a long fund. The parser must reject it.
        """
        csv_negative_equity = (
            "Ticker;Name;ISIN;Gewichtung (%);Assetklasse\n"
            "AAPL;Apple Inc.;US0378331005;-5,00;Aktien\n"
            "MSFT;Microsoft Corp.;US5949181045;10,00;Aktien\n"
        )
        # BUG VULNERABILITY CHECK:
        # Physical equities in long UCITS ETFs cannot have negative weights.
        # If this raises HoldingsValidationError, the invariant is upheld.
        with pytest.raises(HoldingsValidationError, match="(?i)negatif.*hisse|negative.*equity"):
            ISharesParser.parse(csv_negative_equity, isin="IE00BKM4GZ66")


# =============================================================================
# 4. Path Traversal & File System Safety
# =============================================================================

class TestPathTraversalAndFileSystemSafety:
    """Stress tests on directory escapes, unauthorized paths, symlinks, and permissions."""

    def test_path_traversal_attempts_fail_safely(self, tmp_path: Path):
        """Path traversal patterns (../../etc/passwd) must not leak data or crash."""
        db = DatabaseManager(tmp_path / "test_pt.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        res = loader.ingest_file("../../../../../etc/passwd", isin="IE00BKM4GZ66")
        assert res.success is False
        assert res.status in ("FAILED", "FILE_NOT_FOUND")

    def test_directory_passed_as_file(self, tmp_path: Path):
        """Passing a directory instead of a file must fail safely."""
        db = DatabaseManager(tmp_path / "test_dir.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        res = loader.ingest_file(tmp_path, isin="IE00BKM4GZ66")
        assert res.success is False
        assert res.status == "FAILED"

    def test_broken_symlink_fails_gracefully(self, tmp_path: Path):
        """Broken symlinks must result in FILE_NOT_FOUND without unhandled crash."""
        db = DatabaseManager(tmp_path / "test_sym.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        broken_sym = tmp_path / "broken_link.csv"
        try:
            broken_sym.symlink_to(tmp_path / "non_existent_file.csv")
            res = loader.ingest_file(broken_sym, isin="IE00BKM4GZ66")
            assert res.success is False
            assert res.status == "FILE_NOT_FOUND"
        finally:
            if broken_sym.is_symlink() or broken_sym.exists():
                broken_sym.unlink(missing_ok=True)

    def test_strict_posix_permissions(self, tmp_path: Path):
        """Holdings directories (0700) and files (0600) must adhere to strict POSIX security."""
        db = DatabaseManager(tmp_path / "test_perm.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        for d in [loader.inbox_dir, loader.processed_dir, loader.rejected_dir]:
            mode = oct(os.stat(d).st_mode)[-3:]
            assert mode == "700", f"Directory {d} permissions must be 0700, got {mode}"

        sample_file = tmp_path / "valid.csv"
        sample_file.write_text(
            "Ticker;Name;ISIN;Gewichtung (%)\nAAPL;Apple Inc.;US0378331005;5,00\n",
            encoding="utf-8",
        )
        res = loader.ingest_file(sample_file, isin="IE00BKM4GZ66")
        assert res.success is True
        assert res.archived_path is not None
        archived_mode = oct(os.stat(res.archived_path).st_mode)[-3:]
        assert archived_mode == "600", f"Archived file permissions must be 0600, got {archived_mode}"


# =============================================================================
# 5. Idempotency & Duplicate Re-Upload
# =============================================================================

class TestIdempotencyAndReUpload:
    """Stress tests on idempotency, duplicate skipping, and re-uploading updated baskets."""

    def test_identical_file_reupload_skips_without_abort(self, tmp_path: Path):
        """Uploading the exact same file twice produces DUPLICATE_SKIPPED with 0 DB side-effects."""
        db = DatabaseManager(tmp_path / "test_idemp.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        sample_file = tmp_path / "IE00BKM4GZ66_holdings.csv"
        sample_file.write_text(
            "Ticker;Name;ISIN;Gewichtung (%)\nAAPL;Apple Inc.;US0378331005;5,00\n",
            encoding="utf-8",
        )

        # Upload 1
        res1 = loader.ingest_file(sample_file, isin="IE00BKM4GZ66", archive=False)
        assert res1.success is True
        assert res1.status == "INGESTED"
        original_set_id = res1.set_id

        # Upload 2 (identical file)
        res2 = loader.ingest_file(sample_file, isin="IE00BKM4GZ66", archive=False)
        assert res2.success is True
        assert res2.status == "DUPLICATE_SKIPPED"
        assert res2.set_id == original_set_id

        # Verify DB has exactly 1 set and 1 item
        conn = db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) FROM holdings_sets").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM holding_items").fetchone()[0] == 1
        finally:
            conn.close()

    def test_same_filename_new_content_daily_update_not_blocked(self, tmp_path: Path):
        """A new file with the SAME filename but NEW content / date must NOT be skipped as duplicate.

        CHALLENGE: iShares and SPDR websites always use standard names like 'holdings.csv'
        or 'EIMI.csv'. If loader checks 's.source_file = path.name', subsequent daily baskets
        will be silently skipped!
        """
        db = DatabaseManager(tmp_path / "test_daily.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        # Day 1 file named 'holdings.csv'
        day1_file = tmp_path / "holdings.csv"
        day1_file.write_text(
            "Stand vom 20.Okt.2026\n"
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;5,00\n",
            encoding="utf-8",
        )
        res1 = loader.ingest_file(day1_file, isin="IE00BKM4GZ66", archive=False)
        assert res1.success is True
        assert res1.status == "INGESTED"

        # Day 2 file ALSO named 'holdings.csv' with NEW content and NEW date
        day2_file = tmp_path / "holdings.csv"
        day2_file.write_text(
            "Stand vom 21.Okt.2026\n"
            "Ticker;Name;ISIN;Gewichtung (%)\n"
            "AAPL;Apple Inc.;US0378331005;6,00\n",
            encoding="utf-8",
        )
        res2 = loader.ingest_file(day2_file, isin="IE00BKM4GZ66", archive=False)

        # CHALLENGE ASSERTION:
        # Day 2 has different content (SHA-256) and as_of_date.
        # It must NOT be skipped as DUPLICATE_SKIPPED!
        assert res2.status == "INGESTED", (
            f"VULNERABILITY: New basket with identical filename was blocked as {res2.status}. "
            "Deduplication must check payload_sha256 or (isin, as_of_date, sha256), NOT raw filename!"
        )


# =============================================================================
# 6. Immutability Trigger Stress
# =============================================================================

class TestImmutabilityTriggers:
    """Stress tests on SQLite append-only triggers for holdings_sets and holding_items."""

    @pytest.fixture
    def populated_db(self, tmp_path: Path):
        db_file = tmp_path / "test_immut.db"
        db = DatabaseManager(db_file)
        db.initialize_schema()

        now_iso = datetime.now(timezone.utc).isoformat()
        set_row = {
            "set_id": "hs_sealed_1",
            "isin": "IE00BKM4GZ66",
            "as_of_date": "2026-10-20",
            "source_file": "sealed.csv",
            "provider": "iShares",
            "total_records": 1,
            "total_weight_pct": "0.05",
            "created_at": now_iso,
        }
        set_row["record_hash"] = compute_holdings_set_hash(set_row)

        item_row = {
            "item_id": "hi_sealed_1_1",
            "set_id": "hs_sealed_1",
            "constituent_isin": "US0378331005",
            "constituent_ticker": "AAPL",
            "constituent_name": "Apple Inc.",
            "weight_pct": "0.05",
            "shares_held": "100",
            "market_value": "15000",
            "currency": "USD",
            "sector": "Information Technology",
            "country": "United States",
            "asset_class": "EQUITY",
            "item_order": 1,
            "created_at": now_iso,
        }
        item_row["record_hash"] = compute_holding_item_hash(item_row)

        with db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO holdings_sets (set_id, isin, as_of_date, source_file, provider, total_records, total_weight_pct, record_hash, created_at)
                VALUES (:set_id, :isin, :as_of_date, :source_file, :provider, :total_records, :total_weight_pct, :record_hash, :created_at)
                """,
                set_row,
            )
            tx.execute(
                """
                INSERT INTO holding_items (item_id, set_id, constituent_isin, constituent_ticker, constituent_name, weight_pct, shares_held, market_value, currency, sector, country, asset_class, item_order, record_hash, created_at)
                VALUES (:item_id, :set_id, :constituent_isin, :constituent_ticker, :constituent_name, :weight_pct, :shares_held, :market_value, :currency, :sector, :country, :asset_class, :item_order, :record_hash, :created_at)
                """,
                item_row,
            )
        return db

    def test_direct_update_on_holdings_sets_aborts(self, populated_db):
        """Direct UPDATE on holdings_sets must abort with IntegrityError."""
        conn = populated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="holdings_sets degistirilemez"):
                conn.execute("UPDATE holdings_sets SET provider = 'Attacker' WHERE set_id = 'hs_sealed_1'")
        finally:
            conn.close()

    def test_direct_delete_on_holdings_sets_aborts(self, populated_db):
        """Direct DELETE on holdings_sets must abort with IntegrityError."""
        conn = populated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="holdings_sets kaydi silinemez"):
                conn.execute("DELETE FROM holdings_sets WHERE set_id = 'hs_sealed_1'")
        finally:
            conn.close()

    def test_direct_update_on_holding_items_aborts(self, populated_db):
        """Direct UPDATE on holding_items must abort with IntegrityError."""
        conn = populated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="holding_items degistirilemez"):
                conn.execute("UPDATE holding_items SET weight_pct = '0.9999' WHERE item_id = 'hi_sealed_1_1'")
        finally:
            conn.close()

    def test_direct_delete_on_holding_items_aborts(self, populated_db):
        """Direct DELETE on holding_items must abort with IntegrityError."""
        conn = populated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="holding_items kaydi silinemez"):
                conn.execute("DELETE FROM holding_items WHERE item_id = 'hi_sealed_1_1'")
        finally:
            conn.close()

    def test_overwrite_via_insert_or_replace_aborts(self, populated_db):
        """INSERT OR REPLACE (or INSERT OR IGNORE overwrite) must trigger abort."""
        conn = populated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO holdings_sets (set_id, isin, as_of_date, source_file, provider, total_records, total_weight_pct, record_hash, created_at)
                    VALUES ('hs_sealed_1', 'IE00BKM4GZ66', '2026-10-20', 'fake.csv', 'iShares', 1, '0.05', 'h_fake', '2026-10-20T00:00:00Z')
                    """
                )
        finally:
            conn.close()

    def test_transaction_rollback_preserves_state(self, populated_db):
        """Trigger abort inside a transaction must roll back all prior uncommitted statements."""
        try:
            with populated_db.transaction() as tx:
                # 1. Valid insert of raw_object
                tx.execute(
                    """
                    INSERT INTO raw_objects (source, command, payload_sha256, payload_text, retrieved_at, record_count, created_at)
                    VALUES ('test', 'cmd', 'fake_sha', 'text', 'now', 1, 'now')
                    """
                )
                # 2. Illegal update that triggers abort
                tx.execute("UPDATE holdings_sets SET provider = 'Hacked' WHERE set_id = 'hs_sealed_1'")
        except sqlite3.IntegrityError:
            pass

        # Verify transaction completely rolled back (raw_objects should have 0 rows)
        conn = populated_db.get_connection()
        try:
            raw_count = conn.execute("SELECT COUNT(*) FROM raw_objects WHERE payload_sha256 = 'fake_sha'").fetchone()[0]
            assert raw_count == 0, "Transaction must have rolled back completely!"
        finally:
            conn.close()


# =============================================================================
# 7. Fund ISIN Integrity & Luhn Validation
# =============================================================================

class TestFundISINValidation:
    """Stress tests on fund ISIN format and Luhn modulus-10 check."""

    def test_invalid_fund_isin_rejected(self, tmp_path: Path):
        """Invalid fund ISINs (malformed, non-12-char, Luhn violation) must be rejected.

        CHALLENGE: Currently loader accepts arbitrary strings as ISIN (e.g. 'NOT_AN_ISIN').
        It must validate the fund ISIN using ISO 6166 / Luhn mod-10.
        """
        db = DatabaseManager(tmp_path / "test_isin.db")
        db.initialize_schema()
        loader = HoldingsLoader(db, base_dir=tmp_path)

        sample_file = tmp_path / "valid.csv"
        sample_file.write_text(
            "Ticker;Name;ISIN;Gewichtung (%)\nAAPL;Apple Inc.;US0378331005;5,00\n",
            encoding="utf-8",
        )

        # 1. Non-ISIN string
        res = loader.ingest_file(sample_file, isin="INVALID_ISIN")
        assert res.success is False, (
            f"VULNERABILITY: Loader accepted invalid ISIN 'INVALID_ISIN' into database!"
        )

        # 2. 12-character string with invalid Luhn check digit (US0000000000 -> check digit should be 7)
        res_luhn = loader.ingest_file(sample_file, isin="US0000000000")
        assert res_luhn.success is False, (
            f"VULNERABILITY: Loader accepted ISIN with invalid Luhn check digit 'US0000000000' into database!"
        )
