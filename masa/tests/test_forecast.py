"""Comprehensive test suite for Daily Forecast and Settlement Engine (IP-5)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import sqlite3
import pytest

from masa.cli import main
from masa.forecast.generator import MissingQuoteError, generate_daily_forecasts, get_reference_price
from masa.forecast.metrics import calculate_performance_metrics
from masa.forecast.models import (
    ForecastDirection,
    ForecastEntry,
    ForecastPerformanceMetrics,
    PoolInstrument,
    SettlementEntry,
)
from masa.forecast.pool import load_forecast_pool
from masa.forecast.settlement import settle_daily_forecasts
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_forecast_hash, compute_settlement_hash


@pytest.fixture
def test_db(tmp_path):
    """Create an isolated test database initialized with Schema v3."""
    db_file = tmp_path / "test_forecast.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()
    registry = IdentityRegistry(db=db)
    registry.seed_from_configs()
    return db


@pytest.fixture
def mock_quotes():
    """Mock reference quotes for all 10 pool instruments."""
    return {
        "IE00B3YLTY66": Decimal("10.50"),
        "IE00BKM4GZ66": Decimal("4.80"),
        "IE00BP3QZ825": Decimal("18.20"),
        "IE00BP3QZB59": Decimal("6.35"),
        "IE00B4L5Y983": Decimal("95.40"),
        "US0378331005": Decimal("215.00"),
        "US5949181045": Decimal("395.00"),
        "US67066G1040": Decimal("130.00"),
        "NL0010273215": Decimal("725.00"),
        "DE0007164600": Decimal("218.00"),
    }


class TestForecastPool:
    def test_pool_loading_and_counts(self):
        pool = load_forecast_pool()
        assert len(pool.etf) == 5
        assert len(pool.hisse) == 5
        assert len(pool.all_instruments()) == 10

        # Check ETF instruments
        for isin, inst in pool.etf.items():
            assert inst.asset_type == "ETF"
            assert inst.para_birimi == "EUR"
            assert inst.isin == isin

        # Check Equity instruments
        for isin, inst in pool.hisse.items():
            assert inst.asset_type == "EQUITY"
            assert inst.para_birimi == "EUR"
            assert inst.isin == isin


class TestForecastGenerator:
    def test_generate_forecasts_born_sealed(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        forecasts = generate_daily_forecasts(
            test_db,
            target_date=target_d,
            model_id="model_momentum_v1",
            quotes_override=mock_quotes,
        )
        assert len(forecasts) == 10

        for f in forecasts:
            assert f.target_date == target_d
            assert f.model_id == "model_momentum_v1"
            assert f.reference_price > 0
            assert f.target_price > 0
            assert f.direction in (ForecastDirection.UP, ForecastDirection.DOWN, ForecastDirection.FLAT)

            # Check Born-Sealed hash integrity
            row_dict = {
                "confidence_pct": str(f.confidence_pct),
                "created_at": f.created_at,
                "direction": f.direction.value,
                "forecast_id": f.forecast_id,
                "forecast_type": f.forecast_type,
                "isin": f.isin,
                "model_id": f.model_id,
                "reference_price": str(f.reference_price),
                "target_date": f.target_date,
                "target_price": str(f.target_price),
            }
            expected_hash = compute_forecast_hash(row_dict)
            assert f.record_hash == expected_hash

    def test_forecast_generator_idempotency(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        f1 = generate_daily_forecasts(
            test_db,
            target_date=target_d,
            model_id="model_momentum_v1",
            quotes_override=mock_quotes,
        )
        assert len(f1) == 10

        # Calling again on same date and model must return existing without duplicate insertions
        f2 = generate_daily_forecasts(
            test_db,
            target_date=target_d,
            model_id="model_momentum_v1",
            quotes_override=mock_quotes,
        )
        assert len(f2) == 10
        assert [x.forecast_id for x in f1] == [x.forecast_id for x in f2]

        conn = test_db.get_connection()
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM forecast_entries").fetchone()[0]
            assert cnt == 10
        finally:
            conn.close()

    def test_forecast_generator_dry_run(self, test_db, mock_quotes):
        target_d = "2026-11-03"
        forecasts = generate_daily_forecasts(
            test_db,
            target_date=target_d,
            model_id="model_momentum_v1",
            dry_run=True,
            quotes_override=mock_quotes,
        )
        assert len(forecasts) == 10

        conn = test_db.get_connection()
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM forecast_entries WHERE target_date = ?", (target_d,)).fetchone()[0]
            assert cnt == 0  # Dry run did not commit
        finally:
            conn.close()

    def test_missing_quote_raises_domain_exception(self, test_db):
        """Verify MissingQuoteError is raised when quote is absent and no fake price is fabricated."""
        with pytest.raises(MissingQuoteError, match="Quote not found for ISIN"):
            get_reference_price(test_db, "IE00B3YLTY66")

        with pytest.raises(MissingQuoteError, match="Quote not found for ISIN"):
            generate_daily_forecasts(test_db, target_date="2026-11-04")


class TestSettlementEngine:
    def test_settlement_execution_and_accuracy(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        forecasts = generate_daily_forecasts(
            test_db,
            target_date=target_d,
            model_id="model_momentum_v1",
            quotes_override=mock_quotes,
        )

        # Build actual closing prices
        close_prices = {}
        for f in forecasts:
            # Let actual price equal target price for hit, or deviate
            close_prices[f.isin] = f.target_price

        settled = settle_daily_forecasts(
            test_db,
            settlement_date=target_d,
            price_overrides=close_prices,
        )
        assert len(settled) == 10

        for s in settled:
            assert s.settlement_date == target_d
            assert s.error_eur == Decimal("0.0000")
            assert s.error_pct == Decimal("0.0000")
            assert s.direction_hit == 1

            # Check Born-Sealed settlement hash integrity
            row_dict = {
                "actual_close_price": str(s.actual_close_price),
                "direction_hit": s.direction_hit,
                "error_eur": str(s.error_eur),
                "error_pct": str(s.error_pct),
                "forecast_id": s.forecast_id,
                "isin": s.isin,
                "settled_at": s.settled_at,
                "settlement_date": s.settlement_date,
                "settlement_id": s.settlement_id,
            }
            expected_hash = compute_settlement_hash(row_dict)
            assert s.record_hash == expected_hash

    def test_settlement_unsettled_view(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        generate_daily_forecasts(
            test_db,
            target_date=target_d,
            quotes_override=mock_quotes,
        )

        conn = test_db.get_connection()
        try:
            unsettled_cnt = conn.execute("SELECT COUNT(*) FROM v_forecasts_unsettled").fetchone()[0]
            assert unsettled_cnt == 10
        finally:
            conn.close()

        # Settle only 1 instrument
        one_isin = "IE00B3YLTY66"
        settle_daily_forecasts(
            test_db,
            settlement_date=target_d,
            price_overrides={one_isin: Decimal("10.60")},
        )

        conn = test_db.get_connection()
        try:
            unsettled_cnt = conn.execute("SELECT COUNT(*) FROM v_forecasts_unsettled").fetchone()[0]
            assert unsettled_cnt == 9
            settled_cnt = conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
            assert settled_cnt == 1
        finally:
            conn.close()

    def test_single_settlement_per_forecast_constraint(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        generate_daily_forecasts(test_db, target_date=target_d, quotes_override=mock_quotes)
        settle_daily_forecasts(test_db, settlement_date=target_d, price_overrides=mock_quotes)

        # Attempt to insert a second settlement on the same forecast_id directly
        conn = test_db.get_connection()
        try:
            first_s = conn.execute("SELECT * FROM settlements LIMIT 1").fetchone()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_duplicate_attempt', ?, 'IE00B3YLTY66', '2026-11-02',
                        '10.50', '0.00', '0.00', 1, '2026-11-02T18:00:00Z', 'fakehashdup0000000000000000000000000000000000000000000000000000'
                    )
                    """,
                    (first_s["forecast_id"],),
                )
        finally:
            conn.close()


class TestForecastImmutabilityTriggers:
    def test_forecast_entries_immutability(self, test_db, mock_quotes):
        generate_daily_forecasts(test_db, target_date="2026-11-02", quotes_override=mock_quotes)

        conn = test_db.get_connection()
        try:
            f = conn.execute("SELECT * FROM forecast_entries LIMIT 1").fetchone()

            # UPDATE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries degistirilemez"):
                conn.execute("UPDATE forecast_entries SET target_price = '999.00' WHERE forecast_id = ?", (f["forecast_id"],))

            # DELETE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries kaydi silinemez"):
                conn.execute("DELETE FROM forecast_entries WHERE forecast_id = ?", (f["forecast_id"],))

            # INSERT OR REPLACE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, '2026-11-02', 'DAILY_CLOSE', 'UP',
                        '10.00', '11.00', '65.0', 'model_momentum_v1',
                        '2026-11-02T09:30:00Z', ?
                    )
                    """,
                    (f["forecast_id"], f["isin"], f["record_hash"]),
                )
        finally:
            conn.close()

    def test_settlements_immutability(self, test_db, mock_quotes):
        generate_daily_forecasts(test_db, target_date="2026-11-02", quotes_override=mock_quotes)
        settle_daily_forecasts(test_db, settlement_date="2026-11-02", price_overrides=mock_quotes)

        conn = test_db.get_connection()
        try:
            s = conn.execute("SELECT * FROM settlements LIMIT 1").fetchone()

            # UPDATE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="settlements degistirilemez"):
                conn.execute("UPDATE settlements SET direction_hit = 0 WHERE settlement_id = ?", (s["settlement_id"],))

            # DELETE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="settlements kaydi silinemez"):
                conn.execute("DELETE FROM settlements WHERE settlement_id = ?", (s["settlement_id"],))

            # INSERT OR REPLACE prohibited
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', '2026-11-02',
                        '10.50', '0.00', '0.00', 1, '2026-11-02T18:00:00Z', ?
                    )
                    """,
                    (s["settlement_id"], s["forecast_id"], s["record_hash"]),
                )
        finally:
            conn.close()


class TestForecastMetricsScorecard:
    def test_metrics_empty(self, test_db):
        metrics = calculate_performance_metrics(test_db)
        assert metrics.total_forecasts == 0
        assert metrics.settled_count == 0
        assert metrics.hit_rate_pct == Decimal("0.00")
        assert metrics.is_small_sample is True
        assert "Henüz uzlaşmış tahmin bulunmuyor" in (metrics.warning_message or "")

    def test_metrics_with_settled_data(self, test_db, mock_quotes):
        target_d = "2026-11-02"
        forecasts = generate_daily_forecasts(test_db, target_date=target_d, quotes_override=mock_quotes)

        # 7 hits, 3 misses
        actual_prices = {}
        for i, f in enumerate(forecasts):
            if i < 7:
                actual_prices[f.isin] = f.target_price  # hit
            else:
                # invert direction
                if f.direction == ForecastDirection.UP:
                    actual_prices[f.isin] = f.reference_price * Decimal("0.90")  # big DOWN
                else:
                    actual_prices[f.isin] = f.reference_price * Decimal("1.10")  # big UP

        settle_daily_forecasts(test_db, settlement_date=target_d, price_overrides=actual_prices)

        metrics = calculate_performance_metrics(test_db)
        assert metrics.settled_count == 10
        assert metrics.hit_rate_pct == Decimal("70.00")
        assert metrics.is_small_sample is True
        assert "en az 30 gözlem gereklidir" in metrics.warning_message
        assert metrics.etf_hit_rate_pct is not None
        assert metrics.stock_hit_rate_pct is not None


class TestForecastCLI:
    def test_cli_tahmin_commands_e2e(self, test_db, mock_quotes, monkeypatch, capsys):
        monkeypatch.setenv("MASA_DB_PATH", str(test_db.db_path))

        # Seed quotes table so get_reference_price finds prices without override
        conn = test_db.get_connection()
        try:
            snap_id = "snap_test_quotes_001"
            conn.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, run_id, snapshot_type, collection_started_at,
                    collection_completed_at, source, item_count, quality_status,
                    connector_version, prev_hash, curr_hash, created_at
                ) VALUES (
                    ?, 'run_test', 'quotes', '2026-11-02T09:00:00Z',
                    '2026-11-02T09:01:00Z', 'test', 10, 'VALID',
                    '1.0', '0'*64, 'hash_snap_test_001', '2026-11-02T09:01:00Z'
                )
                """,
                (snap_id,),
            )
            for isin, price in mock_quotes.items():
                conn.execute(
                    """
                    INSERT INTO quotes (
                        snapshot_id, isin, currency, bid, ask, computed_mid,
                        spread, spread_pct, quote_timestamp, retrieved_at,
                        source, quality_status, record_hash
                    ) VALUES (
                        ?, ?, 'EUR', ?, ?, ?,
                        '0.02', '0.001', '2026-11-02T09:00:00Z', '2026-11-02T09:00:00Z',
                        'test', 'VALID', ?
                    )
                    """,
                    (snap_id, isin, str(price - Decimal("0.01")), str(price + Decimal("0.01")), str(price), f"hash_{isin}"),
                )
            conn.commit()
        finally:
            conn.close()

        # 1. uret
        with pytest.raises(SystemExit) as exc:
            main(["tahmin", "uret", "--tarih", "2026-11-02"])
        assert exc.value.code == 0
        out1 = capsys.readouterr().out
        assert "10 tahmin başarıyla" in out1

        # 2. listele
        with pytest.raises(SystemExit) as exc:
            main(["tahmin", "listele"])
        assert exc.value.code == 0
        out2 = capsys.readouterr().out
        assert "AÇIK/BEKLİYOR" in out2

        # Seed evening closing quotes (timestamped after 17:30 CET, e.g. 17:40 CET / 16:40 UTC)
        conn = test_db.get_connection()
        try:
            close_snap_id = "snap_test_quotes_close_002"
            conn.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, run_id, snapshot_type, collection_started_at,
                    collection_completed_at, source, item_count, quality_status,
                    connector_version, prev_hash, curr_hash, created_at
                ) VALUES (
                    ?, 'run_test_close', 'quotes', '2026-11-02T16:40:00Z',
                    '2026-11-02T16:41:00Z', 'test', 10, 'VALID',
                    '1.0', '0'*64, 'hash_snap_test_close_002', '2026-11-02T16:41:00Z'
                )
                """,
                (close_snap_id,),
            )
            for isin, price in mock_quotes.items():
                close_p = price + Decimal("0.05")
                conn.execute(
                    """
                    INSERT INTO quotes (
                        snapshot_id, isin, currency, bid, ask, computed_mid,
                        spread, spread_pct, quote_timestamp, retrieved_at,
                        source, quality_status, record_hash
                    ) VALUES (
                        ?, ?, 'EUR', ?, ?, ?,
                        '0.02', '0.001', '2026-11-02T16:40:00Z', '2026-11-02T16:40:00Z',
                        'test', 'VALID', ?
                    )
                    """,
                    (close_snap_id, isin, str(close_p - Decimal("0.01")), str(close_p + Decimal("0.01")), str(close_p), f"hash_close_{isin}"),
                )
            conn.commit()
        finally:
            conn.close()

        # 3. uzlas
        with pytest.raises(SystemExit) as exc:
            main(["tahmin", "uzlas", "--tarih", "2026-11-02"])
        assert exc.value.code == 0
        out3 = capsys.readouterr().out
        assert "10 tahmin uzlaştırıldı ve mühürlendi" in out3

        # 4. karne
        with pytest.raises(SystemExit) as exc:
            main(["tahmin", "karne"])
        assert exc.value.code == 0
        out4 = capsys.readouterr().out
        assert "TAHMİN BAŞARI KARNESİ" in out4
        assert "Hit Rate" in out4
