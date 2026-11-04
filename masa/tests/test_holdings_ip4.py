"""Comprehensive verification tests for Work Package 4 (İP-4).

Tests:
1. iShares CSV parsing (dynamic header detection, comma decimal, percentage normalization, asset classes).
2. SPDR XLSX/CSV parsing (openpyxl extraction, header/footnote filtering, non-inflation).
3. Holdings loader & database persistence (idempotency, raw_objects, audit logging, file archival).
4. Append-only triggers enforcement (6 triggers on holdings_sets and holding_items).
5. Cryptographic record hashes (canonical JSON + SHA-256).
6. Pairwise overlap math (sum(min(wA, wB)), symmetry, self-overlap, 3-tier matching).
7. Top 25 consolidated stock exposure and exact accounting identity (100% reconciliation).
8. Staleness verification (45-day threshold).
9. CLI commands (`sepet yukle`, `sepet listele`, `sepet ortusme`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sqlite3
import pytest

import openpyxl

from masa.calc.overlap import (
    ConstituentHolding,
    FundHoldings,
    build_overlap_matrix,
    calculate_consolidated_exposure,
    calculate_pairwise_overlap,
    check_staleness,
    get_constituent_match_key,
    load_all_active_holdings,
    load_fund_holdings_from_db,
    match_constituents,
    normalize_constituent_name,
)
from masa.holdings.ishares_parser import ISharesParser
from masa.holdings.loader import HoldingsLoader
from masa.holdings.models import AssetClass, HoldingsValidationError, ParsedHoldingItem
from masa.holdings.spdr_parser import SPDRParser
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_holding_item_hash, compute_holdings_set_hash


# =============================================================================
# Realistic Fixtures
# =============================================================================

ISHARES_SAMPLE_CSV = """iShares Core MSCI EM IMI UCITS ETF
Stand vom 20.Okt.2026
Nettoinventarwert: 15.000.000.000 USD
Emittententicker;Wertpapiername;ISIN;Gewichtung (%);Assetklasse;Sektor;Standort;Handelswährung;Anteile;Marktwert
2330;TAIWAN SEMICONDUCTOR MANUFACTURING;TW0002330008;8,45;Aktien;Information Technology;Taiwan;TWD;12.500.000;1.267.500.000
700;TENCENT HOLDINGS LTD;KYG875721634;4,12;Aktien;Communication;China;HKD;8.200.000;618.000.000
005930;SAMSUNG ELECTRONICS LTD;KR7005930003;3,80;Aktien;Information Technology;South Korea;KRW;9.100.000;570.000.000
9988;ALIBABA GROUP HOLDING LTD;KYG017191142;2,60;Aktien;Consumer Discretionary;China;HKD;15.000.000;390.000.000
USD;USD CASH;;1,20;Barmittel;Cash;United States;USD;180.000.000;180.000.000
FUT;MSCI EM FUT DEC26;;-0,15;Derivate;Futures;United States;USD;1.000;-22.500.000
Gesamt;;;100,02;;;;;
"""

ISHARES_INFLATED_CSV = """iShares Test Fund
Stand vom 20.Okt.2026
Ticker;Name;ISIN;Weight (%)
AAPL;APPLE INC;US0378331005;60,00
MSFT;MICROSOFT CORP;US5949181045;55,00
"""


def create_spdr_sample_xlsx_bytes() -> bytes:
    """Generate in-memory realistic SPDR XLSX workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Holdings"

    ws.append(["SPDR MSCI ACWI IMI UCITS ETF (Acc)"])
    ws.append(["Holdings as of 22-Oct-2026"])
    ws.append([])
    # Header row
    ws.append(["Ticker", "Name", "Identifier", "Weight (%)", "Shares Held", "Local Market Value", "Sector", "Country", "Local Currency"])
    # Holdings
    ws.append(["AAPL", "Apple Inc.", "US0378331005", 4.25, 1250000, 250000000, "Information Technology", "United States", "USD"])
    ws.append(["MSFT", "Microsoft Corporation", "US5949181045", 3.80, 950000, 220000000, "Information Technology", "United States", "USD"])
    ws.append(["NVDA", "NVIDIA Corporation", "US67066G1040", 3.10, 800000, 180000000, "Information Technology", "United States", "USD"])
    ws.append(["GOOGL", "Alphabet Inc. Class A", "US02079K3059", 2.15, 600000, 120000000, "Communication Services", "United States", "USD"])
    ws.append(["2330", "Taiwan Semiconductor Manufacturing Co.", "TW0002330008", 1.85, 1500000, 105000000, "Information Technology", "Taiwan", "TWD"])
    ws.append(["CASH", "US DOLLAR", None, 0.75, 45000000, 45000000, "Cash", "United States", "USD"])
    # Trailer / Footnote
    ws.append(["Total", "", "", 15.90, "", "", "", "", ""])
    ws.append(["* Holdings are subject to change. Source: State Street Global Advisors."])

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# =============================================================================
# Unit Tests: Parsers
# =============================================================================

def test_ishares_parser_success():
    parsed = ISharesParser.parse(
        content=ISHARES_SAMPLE_CSV,
        isin="IE00BKM4GZ66",
        source_file_name="EIMI.csv",
    )
    assert parsed.isin == "IE00BKM4GZ66"
    assert parsed.provider == "iShares"
    assert parsed.as_of_date == date(2026, 10, 20)
    assert parsed.total_records == 6  # Total row is filtered out
    # 8.45 + 4.12 + 3.80 + 2.60 + 1.20 - 0.15 = 20.02 / 100 = 0.2002
    assert parsed.total_weight_pct == Decimal("0.2002")
    assert parsed.total_weight_pct <= Decimal("1.0001")

    # Check asset classes
    eq_items = [i for i in parsed.items if i.asset_class == AssetClass.EQUITY.value]
    cash_items = [i for i in parsed.items if i.asset_class == AssetClass.CASH.value]
    deriv_items = [i for i in parsed.items if i.asset_class == AssetClass.DERIVATIVE.value]

    assert len(eq_items) == 4
    assert len(cash_items) == 1
    assert len(deriv_items) == 1

    # Check TSMC item
    tsmc = eq_items[0]
    assert tsmc.constituent_name == "TAIWAN SEMICONDUCTOR MANUFACTURING"
    assert tsmc.constituent_isin == "TW0002330008"
    assert tsmc.weight_pct == Decimal("0.0845")
    assert tsmc.country == "Taiwan"
    assert tsmc.currency == "TWD"


def test_ishares_parser_rejects_inflated_weights():
    with pytest.raises(HoldingsValidationError, match="1.0001"):
        ISharesParser.parse(
            content=ISHARES_INFLATED_CSV,
            isin="IE00BKM4GZ66",
        )


def test_spdr_parser_xlsx_success():
    xlsx_bytes = create_spdr_sample_xlsx_bytes()
    parsed = SPDRParser.parse(
        content=xlsx_bytes,
        isin="IE00B3YLTY66",
        source_file_name="SPYI.xlsx",
    )
    assert parsed.isin == "IE00B3YLTY66"
    assert parsed.provider == "SPDR"
    assert parsed.as_of_date == date(2026, 10, 22)
    assert parsed.total_records == 6  # 5 equity + 1 cash

    # 4.25 + 3.80 + 3.10 + 2.15 + 1.85 + 0.75 = 15.90 / 100 = 0.1590
    assert parsed.total_weight_pct == Decimal("0.1590")
    assert parsed.total_weight_pct <= Decimal("1.0001")

    # Check Apple
    aapl = parsed.items[0]
    assert aapl.constituent_name == "Apple Inc."
    assert aapl.constituent_isin == "US0378331005"
    assert aapl.constituent_ticker == "AAPL"
    assert aapl.weight_pct == Decimal("0.0425")
    assert aapl.sector == "Information Technology"


# =============================================================================
# Database & Loader Integration Tests
# =============================================================================

def test_holdings_loader_persistence_and_idempotency(tmp_path: Path):
    db_file = tmp_path / "test_holdings.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    loader = HoldingsLoader(db, base_dir=tmp_path)

    # Put a sample file in inbox
    inbox_file = loader.inbox_dir / "IE00BKM4GZ66_holdings.csv"
    inbox_file.write_text(ISHARES_SAMPLE_CSV, encoding="utf-8")

    # Ingest from inbox
    res = loader.ingest_file(inbox_file, isin="IE00BKM4GZ66")
    assert res.success is True
    assert res.status == "INGESTED"
    assert res.set_id is not None
    assert res.record_count == 6

    # Verify original moved from inbox to processed with 0600
    assert not inbox_file.exists()
    assert res.archived_path is not None
    assert res.archived_path.exists()
    file_mode = oct(os.stat(res.archived_path).st_mode)[-3:]
    assert file_mode == "600"

    # Check DB rows
    conn = db.get_connection()
    try:
        set_row = conn.execute("SELECT * FROM holdings_sets WHERE set_id = ?", (res.set_id,)).fetchone()
        assert set_row is not None
        assert set_row["isin"] == "IE00BKM4GZ66"
        assert set_row["total_records"] == 6

        # Check cryptographic hash match
        recomputed_set_hash = compute_holdings_set_hash(set_row)
        assert set_row["record_hash"] == recomputed_set_hash

        items = conn.execute("SELECT * FROM holding_items WHERE set_id = ? ORDER BY item_order", (res.set_id,)).fetchall()
        assert len(items) == 6
        for item in items:
            recomputed_item_hash = compute_holding_item_hash(item)
            assert item["record_hash"] == recomputed_item_hash

        # Check raw_objects persistence
        raw_row = conn.execute("SELECT * FROM raw_objects WHERE command = ?", (inbox_file.name,)).fetchone()
        assert raw_row is not None
        assert raw_row["record_count"] == 6

        # Check audit event
        audit_row = conn.execute("SELECT * FROM audit_events WHERE action = 'HOLDINGS_SET_INGESTED' AND entity_id = ?", (res.set_id,)).fetchone()
        assert audit_row is not None
    finally:
        conn.close()

    # Re-uploading the same file must be idempotent (DUPLICATE_SKIPPED)
    res_dup = loader.ingest_file(res.archived_path, isin="IE00BKM4GZ66")
    assert res_dup.success is True
    assert res_dup.status == "DUPLICATE_SKIPPED"


def test_holdings_append_only_triggers(tmp_path: Path):
    db_file = tmp_path / "test_triggers.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    # Verify at least 48 triggers (57 after IP-5)
    conn = db.get_connection()
    try:
        trig_count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        assert trig_count >= 48

        # Insert a valid holdings_set
        now_iso = datetime.now(timezone.utc).isoformat()
        set_data = {
            "set_id": "hs_test1",
            "isin": "IE00BKM4GZ66",
            "as_of_date": "2026-10-20",
            "source_file": "test.csv",
            "provider": "iShares",
            "total_records": 1,
            "total_weight_pct": "0.10",
            "created_at": now_iso,
        }
        set_hash = compute_holdings_set_hash(set_data)
        set_data["record_hash"] = set_hash
        conn.execute(
            """
            INSERT INTO holdings_sets (set_id, isin, as_of_date, source_file, provider, total_records, total_weight_pct, record_hash, created_at)
            VALUES (:set_id, :isin, :as_of_date, :source_file, :provider, :total_records, :total_weight_pct, :record_hash, :created_at)
            """,
            set_data,
        )

        item_data = {
            "item_id": "hi_test1_1",
            "set_id": "hs_test1",
            "constituent_isin": "US0378331005",
            "constituent_ticker": "AAPL",
            "constituent_name": "Apple Inc.",
            "weight_pct": "0.10",
            "shares_held": "100",
            "market_value": "20000",
            "currency": "USD",
            "sector": "Tech",
            "country": "US",
            "asset_class": "EQUITY",
            "item_order": 1,
            "created_at": now_iso,
        }
        item_hash = compute_holding_item_hash(item_data)
        item_data["record_hash"] = item_hash
        conn.execute(
            """
            INSERT INTO holding_items (item_id, set_id, constituent_isin, constituent_ticker, constituent_name, weight_pct, shares_held, market_value, currency, sector, country, asset_class, item_order, record_hash, created_at)
            VALUES (:item_id, :set_id, :constituent_isin, :constituent_ticker, :constituent_name, :weight_pct, :shares_held, :market_value, :currency, :sector, :country, :asset_class, :item_order, :record_hash, :created_at)
            """,
            item_data,
        )

        # 1. UPDATE on holdings_sets must abort
        with pytest.raises(sqlite3.IntegrityError, match="holdings_sets degistirilemez"):
            conn.execute("UPDATE holdings_sets SET total_records = 2 WHERE set_id = 'hs_test1'")

        # 2. DELETE on holdings_sets must abort
        with pytest.raises(sqlite3.IntegrityError, match="holdings_sets kaydi silinemez"):
            conn.execute("DELETE FROM holdings_sets WHERE set_id = 'hs_test1'")

        # 3. OVERWRITE on holdings_sets must abort
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
            conn.execute("INSERT OR REPLACE INTO holdings_sets (set_id, isin, as_of_date, source_file, provider, total_records, total_weight_pct, record_hash, created_at) VALUES ('hs_test1', 'IE00BKM4GZ66', '2026-10-20', 'test.csv', 'iShares', 1, '0.10', 'fakehash', 'now')")

        # 4. UPDATE on holding_items must abort
        with pytest.raises(sqlite3.IntegrityError, match="holding_items degistirilemez"):
            conn.execute("UPDATE holding_items SET weight_pct = '0.20' WHERE item_id = 'hi_test1_1'")

        # 5. DELETE on holding_items must abort
        with pytest.raises(sqlite3.IntegrityError, match="holding_items kaydi silinemez"):
            conn.execute("DELETE FROM holding_items WHERE item_id = 'hi_test1_1'")

        # 6. OVERWRITE on holding_items must abort
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
            conn.execute("INSERT INTO holding_items (item_id, set_id, constituent_isin, constituent_ticker, constituent_name, weight_pct, shares_held, market_value, currency, sector, country, asset_class, item_order, record_hash, created_at) VALUES ('hi_test1_1', 'hs_test1', 'US0378331005', 'AAPL', 'Apple Inc.', '0.10', '100', '20000', 'USD', 'Tech', 'US', 'EQUITY', 1, 'otherhash', 'now')")

    finally:
        conn.close()


# =============================================================================
# Unit Tests: Analytics & Overlap Math
# =============================================================================

def test_normalize_constituent_name():
    assert normalize_constituent_name("Apple Inc.") == "apple"
    assert normalize_constituent_name("Microsoft Corporation") == "microsoft"
    assert normalize_constituent_name("Tencent Holdings Ltd.") == "tencent"
    assert normalize_constituent_name("Alphabet Inc. Class A") == "alphabet"
    assert normalize_constituent_name("Alphabet Inc. - Class C") == "alphabet"
    assert normalize_constituent_name("SAP SE") == "sap"


def test_3tier_constituent_matching():
    # Tier 1: Dual class cross reference (Alphabet A and C)
    item_a = ConstituentHolding(holding_isin="US02079K3059", name="Alphabet Inc. Class A", weight=Decimal("0.02"))
    item_c = ConstituentHolding(holding_isin="US02079K1079", name="Alphabet Inc. Class C", weight=Decimal("0.01"))
    assert match_constituents(item_a, item_c) == "ENTITY:US_ALPHABET"

    # Tier 1: TSMC ADR and Ordinary
    tsmc_adr = ConstituentHolding(holding_isin="US8740391003", name="TSMC ADR", weight=Decimal("0.03"))
    tsmc_ord = ConstituentHolding(holding_isin="TW0002330008", name="Taiwan Semiconductor Mfg", weight=Decimal("0.03"))
    assert match_constituents(tsmc_adr, tsmc_ord) == "ENTITY:TW_TSMC"

    # Distinct ISINs must not match even if names look similar
    aapl = ConstituentHolding(holding_isin="US0378331005", name="Apple Inc.", weight=Decimal("0.05"))
    msft = ConstituentHolding(holding_isin="US5949181045", name="Apple Inc.", weight=Decimal("0.05"))
    assert match_constituents(aapl, msft) is None

    # Tier 2: Ticker matching when ISIN missing
    no_isin_1 = ConstituentHolding(holding_isin=None, ticker="ASML.AS", name="ASML Holding", weight=Decimal("0.02"))
    no_isin_2 = ConstituentHolding(holding_isin=None, ticker="ASML", name="ASML Inc.", weight=Decimal("0.02"))
    assert match_constituents(no_isin_1, no_isin_2) == "TICKER:ASML"

    # Tier 3: Name matching when ISIN and ticker missing
    no_id_1 = ConstituentHolding(holding_isin=None, ticker=None, name="Novo Nordisk A/S", weight=Decimal("0.02"))
    no_id_2 = ConstituentHolding(holding_isin=None, ticker=None, name="Novo Nordisk Inc.", weight=Decimal("0.02"))
    assert match_constituents(no_id_1, no_id_2) == "NAME:novo nordisk"


def test_pairwise_overlap_known_answers():
    # Fund A: AAPL (50%), MSFT (30%), AMZN (20%)
    fund_a = FundHoldings(
        isin="FUND_A",
        fund_name="Fund A",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("1.00"),
        cash_weight=Decimal("0.00"),
        derivative_weight=Decimal("0.00"),
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.50")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.30")),
            ConstituentHolding(holding_isin="US0231351067", ticker="AMZN", name="Amazon.com Inc.", weight=Decimal("0.20")),
        ],
    )

    # Fund B: AAPL (20%), MSFT (40%), GOOG (40%)
    fund_b = FundHoldings(
        isin="FUND_B",
        fund_name="Fund B",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("1.00"),
        cash_weight=Decimal("0.00"),
        derivative_weight=Decimal("0.00"),
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.20")),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.40")),
            ConstituentHolding(holding_isin="US02079K3059", ticker="GOOGL", name="Alphabet Inc.", weight=Decimal("0.40")),
        ],
    )

    # Overlap = min(0.50, 0.20) + min(0.30, 0.40) = 0.20 + 0.30 = 0.50
    res_ab = calculate_pairwise_overlap(fund_a, fund_b)
    res_ba = calculate_pairwise_overlap(fund_b, fund_a)

    assert res_ab.overlap_score == Decimal("0.50")
    assert res_ba.overlap_score == Decimal("0.50")  # Symmetry
    assert res_ab.shared_count == 2

    # Self overlap = 1.00
    res_aa = calculate_pairwise_overlap(fund_a, fund_a)
    assert res_aa.overlap_score == Decimal("1.00")

    # Matrix
    matrix = build_overlap_matrix([fund_a, fund_b])
    assert matrix.matrix[0][0] == Decimal("1.00")
    assert matrix.matrix[1][1] == Decimal("1.00")
    assert matrix.matrix[0][1] == Decimal("0.50")
    assert matrix.matrix[1][0] == Decimal("0.50")


def test_consolidated_top25_accounting_identity():
    # Fund A (Weight: 60%): AAPL (50%), MSFT (30%), AMZN (15%), CASH (5%)
    # Equity coverage: 95%, Cash: 5%
    fund_a = FundHoldings(
        isin="FUND_A",
        fund_name="Fund A",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("0.95"),
        cash_weight=Decimal("0.05"),
        derivative_weight=Decimal("0.00"),
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.50"), sector="Tech", country="US"),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.30"), sector="Tech", country="US"),
            ConstituentHolding(holding_isin="US0231351067", ticker="AMZN", name="Amazon.com Inc.", weight=Decimal("0.15"), sector="Cons", country="US"),
            ConstituentHolding(holding_isin=None, ticker="CASH", name="USD Cash", weight=Decimal("0.05"), asset_class=AssetClass.CASH.value),
        ],
    )

    # Fund B (Weight: 40%): AAPL (20%), MSFT (40%), GOOG (35%), CASH (5%)
    fund_b = FundHoldings(
        isin="FUND_B",
        fund_name="Fund B",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("0.95"),
        cash_weight=Decimal("0.05"),
        derivative_weight=Decimal("0.00"),
        holdings=[
            ConstituentHolding(holding_isin="US0378331005", ticker="AAPL", name="Apple Inc.", weight=Decimal("0.20"), sector="Tech", country="US"),
            ConstituentHolding(holding_isin="US5949181045", ticker="MSFT", name="Microsoft Corp.", weight=Decimal("0.40"), sector="Tech", country="US"),
            ConstituentHolding(holding_isin="US02079K3059", ticker="GOOGL", name="Alphabet Inc.", weight=Decimal("0.35"), sector="Comm", country="US"),
            ConstituentHolding(holding_isin=None, ticker="CASH", name="USD Cash", weight=Decimal("0.05"), asset_class=AssetClass.CASH.value),
        ],
    )

    fund_weights = {"FUND_A": Decimal("0.60"), "FUND_B": Decimal("0.40")}
    summary, breakdown = calculate_consolidated_exposure(
        funds=[fund_a, fund_b],
        fund_weights=fund_weights,
        portfolio_cash_weight=Decimal("0.00"),
        portfolio_total_eur=Decimal("10000.00"),
    )

    # Check consolidated stock weights:
    # AAPL: 0.60 * 0.50 + 0.40 * 0.20 = 0.30 + 0.08 = 0.38 (38%)
    # MSFT: 0.60 * 0.30 + 0.40 * 0.40 = 0.18 + 0.16 = 0.34 (34%)
    # GOOG: 0.40 * 0.35 = 0.14 (14%)
    # AMZN: 0.60 * 0.15 = 0.09 (9%)
    # Cash: 0.60 * 0.05 + 0.40 * 0.05 = 0.03 + 0.02 = 0.05 (5%)
    # Total: 0.38 + 0.34 + 0.14 + 0.09 + 0.05 = 1.00 (100%)

    assert len(summary.top_stocks) == 4
    assert summary.top_stocks[0].ticker == "AAPL"
    assert summary.top_stocks[0].portfolio_weight == Decimal("0.38")
    assert summary.top_stocks[0].valuation_eur == Decimal("3800.00")

    assert summary.top_stocks[1].ticker == "MSFT"
    assert summary.top_stocks[1].portfolio_weight == Decimal("0.34")

    assert summary.top_stocks[2].ticker == "GOOGL"
    assert summary.top_stocks[2].portfolio_weight == Decimal("0.14")

    assert summary.top_stocks[3].ticker == "AMZN"
    assert summary.top_stocks[3].portfolio_weight == Decimal("0.09")

    # Accounting Identity: Top25 + Other + Uncovered + Cash == 1.0000
    assert summary.cash_weight == Decimal("0.05")
    assert summary.is_fully_reconciled is True
    assert summary.total_reconciled_weight == Decimal("1.00")


def test_staleness_check():
    today = date.today()
    fresh_date = today - timedelta(days=20)
    stale_date = today - timedelta(days=50)

    is_stale_1, age_1 = check_staleness(fresh_date, ref_date=today)
    assert is_stale_1 is False
    assert age_1 == 20

    is_stale_2, age_2 = check_staleness(stale_date, ref_date=today)
    assert is_stale_2 is True
    assert age_2 == 50


# =============================================================================
# CLI Tests
# =============================================================================

def test_cli_sepet_workflow(tmp_path: Path, monkeypatch):
    from masa.cli import main

    db_path = tmp_path / "test_cli.db"
    db = DatabaseManager(db_path)
    db.initialize_schema()

    # Monkeypatch DatabaseManager in CLI
    monkeypatch.setattr("masa.cli.DatabaseManager", lambda: db)
    monkeypatch.setattr("masa.holdings.loader.DatabaseManager", lambda: db)
    monkeypatch.setattr("masa.calc.overlap.DatabaseManager", lambda: db)

    # Prepare sample file
    sample_file = tmp_path / "IE00BKM4GZ66_EIMI.csv"
    sample_file.write_text(ISHARES_SAMPLE_CSV, encoding="utf-8")

    # 1. Test `masa sepet yukle <dosya>`
    with pytest.raises(SystemExit) as exc_yukle:
        main(["sepet", "yukle", str(sample_file)])
    assert exc_yukle.value.code == 0

    # 2. Test `masa sepet listele`
    with pytest.raises(SystemExit) as exc_list:
        main(["sepet", "listele"])
    assert exc_list.value.code == 0

    # 3. Test `masa sepet ortusme --json`
    with pytest.raises(SystemExit) as exc_ort:
        main(["sepet", "ortusme", "--json", "--hedef"])
    assert exc_ort.value.code == 0


def test_empty_files_handling():
    with pytest.raises(HoldingsValidationError, match="boş"):
        ISharesParser.parse("", isin="IE00BKM4GZ66")

    with pytest.raises(HoldingsValidationError, match="boş"):
        SPDRParser.parse("", isin="IE00B3YLTY66")


def test_spdr_csv_parsing():
    spdr_csv = """SPDR MSCI World UCITS ETF
Holdings as of 25-Oct-2026
Ticker,Name,Identifier,Weight (%),Sector,Country,Currency
AAPL,Apple Inc.,US0378331005,5.10,Information Technology,United States,USD
MSFT,Microsoft Corp.,US5949181045,4.20,Information Technology,United States,USD
Total,,,9.30,,,
"""
    parsed = SPDRParser.parse(spdr_csv, isin="IE00BFY0GT14")
    assert parsed.provider == "SPDR"
    assert parsed.total_records == 2
    assert parsed.total_weight_pct == Decimal("0.0930")
    assert parsed.as_of_date == date(2026, 10, 25)


def test_top25_with_more_than_25_stocks():
    # Construct a fund with 35 distinct stocks
    items = []
    # 35 stocks each 2% = 70% total
    for i in range(1, 36):
        items.append(
            ConstituentHolding(
                holding_isin=f"US{i:010d}",
                ticker=f"STK{i}",
                name=f"Stock Company {i}",
                weight=Decimal("0.02"),
                sector="Technology" if i % 2 == 0 else "Healthcare",
                country="United States",
            )
        )
    # Remaining 30% is cash
    items.append(
        ConstituentHolding(
            holding_isin=None,
            ticker="CASH",
            name="Cash Position",
            weight=Decimal("0.30"),
            asset_class=AssetClass.CASH.value,
        )
    )

    fund = FundHoldings(
        isin="IE00BIGFND01",
        fund_name="Big Diversified Fund",
        as_of_date=date(2026, 10, 20),
        total_weight=Decimal("1.00"),
        equity_weight=Decimal("0.70"),
        cash_weight=Decimal("0.30"),
        derivative_weight=Decimal("0.00"),
        holdings=items,
    )

    summary, breakdown = calculate_consolidated_exposure(
        funds=[fund],
        fund_weights={"IE00BIGFND01": Decimal("1.00")},
        portfolio_total_eur=Decimal("100000.00"),
    )

    assert len(summary.top_stocks) == 25
    # Top 25: 25 * 0.02 = 0.50 (50%)
    assert summary.top25_weight == Decimal("0.50")
    # Other stocks: 10 * 0.02 = 0.20 (20%)
    assert summary.other_stocks_weight == Decimal("0.20")
    # Cash: 0.30 (30%)
    assert summary.cash_weight == Decimal("0.30")
    # Exact accounting identity
    assert summary.is_fully_reconciled is True
    assert summary.total_reconciled_weight == Decimal("1.00")


def test_loader_rejected_file_handling(tmp_path: Path):
    db_file = tmp_path / "test_reject.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()

    loader = HoldingsLoader(db, base_dir=tmp_path)

    bad_file = tmp_path / "invalid_basket.csv"
    bad_file.write_text("gibberish without columns\n12345", encoding="utf-8")

    res = loader.ingest_file(bad_file, isin="IE00BKM4GZ66")
    assert res.success is False
    assert res.status == "FAILED"

    # Verify error log written to rejected directory
    rejected_errs = list(loader.rejected_dir.glob("*.err"))
    assert len(rejected_errs) == 1
    err_content = rejected_errs[0].read_text()
    assert "Hata:" in err_content


