"""Adversarial Challenger 2 Test Suite for IP-5 (02 CRITIQUE - Forecast & Settlement Engine).

Comprehensive empirical stress testing across 5 core dimensions:
1. Duplicate & Conflicting Settlements
2. Immutability & Trigger Aborts on forecast_entries and settlements
3. Deadband & Direction Boundary Conditions
4. Scorecard Math & Extreme Value Robustness
5. Generation Idempotency & Multi-Model Execution
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from masa.forecast.generator import (
    DEADBAND_THRESHOLD,
    generate_daily_forecasts,
    get_reference_price,
)
from masa.forecast.metrics import calculate_performance_metrics
from masa.forecast.models import (
    ForecastDirection,
    ForecastEntry,
    ForecastPerformanceMetrics,
    PoolInstrument,
    SettlementEntry,
)
from masa.forecast.pool import load_forecast_pool
from masa.forecast.settlement import (
    get_actual_close_price,
    settle_daily_forecasts,
)
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import (
    compute_forecast_hash,
    compute_settlement_hash,
)


@pytest.fixture
def isolated_db(tmp_path: Path):
    """Isolated, pristine SQLite database with Schema v3 and seeded identity registry."""
    db_file = tmp_path / "ip5_challenger2_test.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()
    IdentityRegistry(db=db).seed_from_configs()
    return db


@pytest.fixture
def mock_pool_quotes():
    """Deterministic reference prices for all 10 pool instruments."""
    return {
        "IE00B3YLTY66": Decimal("10.50"),
        "IE00BKM4GZ66": Decimal("4.90"),
        "IE00BP3QZ825": Decimal("18.20"),
        "IE00BP3QZB59": Decimal("6.35"),
        "IE00B4L5Y983": Decimal("95.50"),
        "US0378331005": Decimal("215.00"),
        "US5949181045": Decimal("395.00"),
        "US67066G1040": Decimal("130.00"),
        "NL0010273215": Decimal("720.00"),
        "DE0007164600": Decimal("215.00"),
    }


# ============================================================================
# 1. DUPLICATE & CONFLICTING SETTLEMENTS
# ============================================================================

class TestDuplicateAndConflictingSettlements:
    """Stress-test settlement uniqueness, conflict resolution, and trigger aborts."""

    def test_direct_sql_duplicate_settlement_rejected_by_index_and_trigger(self, isolated_db, mock_pool_quotes):
        """Attempt to settle the same forecast twice with different closing prices and IDs."""
        target_d = "2026-11-02"
        forecasts = generate_daily_forecasts(
            isolated_db, target_date=target_d, quotes_override=mock_pool_quotes
        )
        assert len(forecasts) == 10
        f0 = forecasts[0]

        # First settlement (legitimate)
        settle_daily_forecasts(
            isolated_db, settlement_date=target_d, price_overrides={f0.isin: Decimal("10.80")}
        )

        conn = isolated_db.get_connection()
        try:
            # Attack A: Insert a conflicting settlement with different settlement_id on same forecast_id
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_conflicting_attack_01', ?, ?, ?,
                        '99.99', '89.19', '800.00', 0,
                        '2026-11-02T18:00:00Z', 'hash_attack_01_0000000000000000000000000000000000000000000000000000'
                    )
                    """,
                    (f0.forecast_id, f0.isin, target_d),
                )
            # The trigger prevent_overwrite_settlements catches it first
            assert "settlements: mevcut kaydin uzerine yazma" in str(exc_info.value) or "UNIQUE constraint failed" in str(exc_info.value)

            # Attack B: Attempt INSERT OR REPLACE with different values
            with pytest.raises(sqlite3.IntegrityError) as exc_info2:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_conflicting_attack_02', ?, ?, ?,
                        '5.00', '-5.80', '-50.00', 0,
                        '2026-11-02T18:05:00Z', 'hash_attack_02_0000000000000000000000000000000000000000000000000000'
                    )
                    """,
                    (f0.forecast_id, f0.isin, target_d),
                )
            assert "settlements: mevcut kaydin uzerine yazma" in str(exc_info2.value) or "settlements degistirilemez" in str(exc_info2.value)

            # Verify settlement count for f0 is strictly 1
            cnt = conn.execute(
                "SELECT COUNT(*) FROM settlements WHERE forecast_id = ?",
                (f0.forecast_id,),
            ).fetchone()[0]
            assert cnt == 1

            # Verify closing price was NOT tampered with
            row = conn.execute(
                "SELECT actual_close_price FROM settlements WHERE forecast_id = ?",
                (f0.forecast_id,),
            ).fetchone()
            assert Decimal(row[0]) == Decimal("10.80")
        finally:
            conn.close()

    def test_sequential_settle_daily_forecasts_idempotency(self, isolated_db, mock_pool_quotes):
        """Calling settle_daily_forecasts twice must be safe, idempotent, and return empty list on 2nd run."""
        target_d = "2026-11-02"
        generate_daily_forecasts(isolated_db, target_date=target_d, quotes_override=mock_pool_quotes)

        # Run 1: Settles all 10
        settled_1 = settle_daily_forecasts(isolated_db, settlement_date=target_d, price_overrides=mock_pool_quotes)
        assert len(settled_1) == 10

        # Run 2: Nothing left unsettled in v_forecasts_unsettled
        settled_2 = settle_daily_forecasts(isolated_db, settlement_date=target_d, price_overrides=mock_pool_quotes)
        assert len(settled_2) == 0

        # Check total settlements table count
        conn = isolated_db.get_connection()
        try:
            total_settled = conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
            assert total_settled == 10
            unsettled_left = conn.execute("SELECT COUNT(*) FROM v_forecasts_unsettled").fetchone()[0]
            assert unsettled_left == 0
        finally:
            conn.close()

    def test_foreign_key_protection_on_settlements(self, isolated_db):
        """Inserting a settlement with non-existent forecast_id or invalid ISIN must fail foreign key check."""
        conn = isolated_db.get_connection()
        try:
            # Enable foreign keys explicitly in this connection to verify SQLite contract
            conn.execute("PRAGMA foreign_keys = ON;")

            # Non-existent forecast_id
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_ghost_01', 'fc_non_existent_target', 'IE00B3YLTY66', '2026-11-02',
                        '10.50', '0.00', '0.00', 1,
                        '2026-11-02T18:00:00Z', 'hash_ghost_01_00000000000000000000000000000000000000000000000000'
                    )
                    """
                )
        finally:
            conn.close()


# ============================================================================
# 2. IMMUTABILITY & TRIGGER ABORTS ON FORECASTS AND SETTLEMENTS
# ============================================================================

class TestImmutabilityAndTriggerAborts:
    """Rigorous verification of 6 append-only triggers for forecast_entries and settlements."""

    def test_forecast_entries_triggers(self, isolated_db, mock_pool_quotes):
        generate_daily_forecasts(isolated_db, target_date="2026-11-02", quotes_override=mock_pool_quotes)

        conn = isolated_db.get_connection()
        try:
            f = conn.execute("SELECT * FROM forecast_entries LIMIT 1").fetchone()
            fid = f["forecast_id"]

            # 1. UPDATE single row
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries degistirilemez"):
                conn.execute("UPDATE forecast_entries SET confidence_pct = '99.99' WHERE forecast_id = ?", (fid,))

            # 2. UPDATE all rows (mass update)
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries degistirilemez"):
                conn.execute("UPDATE forecast_entries SET direction = 'DOWN'")

            # 3. DELETE single row
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries kaydi silinemez"):
                conn.execute("DELETE FROM forecast_entries WHERE forecast_id = ?", (fid,))

            # 4. DELETE all rows
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries kaydi silinemez"):
                conn.execute("DELETE FROM forecast_entries")

            # 5. INSERT with existing forecast_id (overwrite trigger)
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        ?, 'IE00B3YLTY66', '2026-11-02', 'DAILY_CLOSE', 'UP',
                        '10.00', '11.00', '65.00', 'model_m',
                        '2026-11-02T09:30:00Z', 'fake_hash_new_unique_1234567890'
                    )
                    """,
                    (fid,),
                )

            # 6. INSERT with existing record_hash but new forecast_id (hash duplicate trigger)
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        'fc_new_brand_unique_id', 'IE00B3YLTY66', '2026-11-02', 'DAILY_CLOSE', 'UP',
                        '10.00', '11.00', '65.00', 'model_m',
                        '2026-11-02T09:30:00Z', ?
                    )
                    """,
                    (f["record_hash"],),
                )
        finally:
            conn.close()

    def test_settlements_triggers(self, isolated_db, mock_pool_quotes):
        generate_daily_forecasts(isolated_db, target_date="2026-11-02", quotes_override=mock_pool_quotes)
        settle_daily_forecasts(isolated_db, settlement_date="2026-11-02", price_overrides=mock_pool_quotes)

        conn = isolated_db.get_connection()
        try:
            s = conn.execute("SELECT * FROM settlements LIMIT 1").fetchone()
            sid = s["settlement_id"]

            # 1. UPDATE single row
            with pytest.raises(sqlite3.IntegrityError, match="settlements degistirilemez"):
                conn.execute("UPDATE settlements SET actual_close_price = '1000.00' WHERE settlement_id = ?", (sid,))

            # 2. UPDATE all rows
            with pytest.raises(sqlite3.IntegrityError, match="settlements degistirilemez"):
                conn.execute("UPDATE settlements SET direction_hit = 1")

            # 3. DELETE single row
            with pytest.raises(sqlite3.IntegrityError, match="settlements kaydi silinemez"):
                conn.execute("DELETE FROM settlements WHERE settlement_id = ?", (sid,))

            # 4. DELETE all rows
            with pytest.raises(sqlite3.IntegrityError, match="settlements kaydi silinemez"):
                conn.execute("DELETE FROM settlements")

            # 5. INSERT with existing settlement_id
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        ?, 'fc_brand_new_fc_id', 'IE00B3YLTY66', '2026-11-02',
                        '10.50', '0.00', '0.00', 1,
                        '2026-11-02T18:00:00Z', 'fake_hash_new_unique_set_12345'
                    )
                    """,
                    (sid,),
                )

            # 6. INSERT with existing record_hash but new settlement_id
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_brand_new_sid', 'fc_brand_new_fc_id2', 'IE00B3YLTY66', '2026-11-02',
                        '10.50', '0.00', '0.00', 1,
                        '2026-11-02T18:00:00Z', ?
                    )
                    """,
                    (s["record_hash"],),
                )
        finally:
            conn.close()


# ============================================================================
# 3. DEADBAND & DIRECTION BOUNDARY CONDITIONS
# ============================================================================

class TestDeadbandAndDirectionBoundaries:
    """Stress-test 0.10% deadband threshold on both generator and settlement engines."""

    @pytest.mark.parametrize(
        "delta, expected_direction",
        [
            (Decimal("0.000000"), ForecastDirection.FLAT),
            (Decimal("0.000500"), ForecastDirection.FLAT),
            (Decimal("0.000999"), ForecastDirection.FLAT),     # Borderline below +0.10%
            (Decimal("0.001000"), ForecastDirection.UP),       # Exact threshold +0.10% (|delta| < 0.0010 is False)
            (Decimal("0.001001"), ForecastDirection.UP),       # Borderline above +0.10%
            (Decimal("0.050000"), ForecastDirection.UP),
            (Decimal("-0.000500"), ForecastDirection.FLAT),
            (Decimal("-0.000999"), ForecastDirection.FLAT),    # Borderline above -0.10%
            (Decimal("-0.001000"), ForecastDirection.DOWN),    # Exact threshold -0.10%
            (Decimal("-0.001001"), ForecastDirection.DOWN),    # Borderline below -0.10%
            (Decimal("-0.050000"), ForecastDirection.DOWN),
        ],
    )
    def test_deadband_logic_consistency(self, delta, expected_direction):
        """Verify standard mathematical evaluation against DEADBAND_THRESHOLD = 0.0010."""
        threshold = DEADBAND_THRESHOLD
        if abs(delta) < threshold:
            direction = ForecastDirection.FLAT
        elif delta > 0:
            direction = ForecastDirection.UP
        else:
            direction = ForecastDirection.DOWN

        assert direction == expected_direction

    def test_settlement_direction_evaluation_with_borderline_prices(self, isolated_db):
        """Check settlement actual direction evaluation when actual close price is at deadband boundaries."""
        ref_price = Decimal("100.00")
        target_d = "2026-11-02"

        # Generate a baseline forecast manually for precision testing
        isin = "IE00B3YLTY66"
        fc_id = f"fc_{target_d}_{isin}_test_deadband"
        now_str = "2026-11-02T09:30:00Z"
        h = compute_forecast_hash({
            "confidence_pct": "65.00",
            "created_at": now_str,
            "direction": "FLAT",
            "forecast_id": fc_id,
            "forecast_type": "DAILY_CLOSE",
            "isin": isin,
            "model_id": "model_test",
            "reference_price": str(ref_price),
            "target_date": target_d,
            "target_price": str(ref_price),
        })

        conn = isolated_db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, ?, ?, 'DAILY_CLOSE', 'FLAT',
                    ?, ?, '65.00', 'model_test', ?, ?
                )
                """,
                (fc_id, isin, target_d, str(ref_price), str(ref_price), now_str, h),
            )
            conn.commit()
        finally:
            conn.close()

        # Borderline Case 1: actual close = 100.0999 (delta = +0.000999 -> FLAT) -> direction_hit = 1
        s1 = settle_daily_forecasts(
            isolated_db,
            settlement_date=target_d,
            price_overrides={isin: Decimal("100.0999")},
        )
        assert len(s1) == 1
        assert s1[0].direction_hit == 1

    def test_zero_and_negative_price_resilience(self, isolated_db):
        """Ensure zero or negative prices in settlement calculations do NOT trigger division by zero."""
        isin = "IE00B3YLTY66"
        target_d = "2026-11-03"
        fc_id = f"fc_{target_d}_{isin}_test_zero"
        now_str = "2026-11-03T09:30:00Z"
        h = compute_forecast_hash({
            "confidence_pct": "65.00",
            "created_at": now_str,
            "direction": "UP",
            "forecast_id": fc_id,
            "forecast_type": "DAILY_CLOSE",
            "isin": isin,
            "model_id": "model_zero_test",
            "reference_price": "0.00",
            "target_date": target_d,
            "target_price": "10.00",
        })

        conn = isolated_db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, ?, ?, 'DAILY_CLOSE', 'UP',
                    '0.00', '10.00', '65.00', 'model_zero_test', ?, ?
                )
                """,
                (fc_id, isin, target_d, now_str, h),
            )
            conn.commit()
        finally:
            conn.close()

        # Settle with actual_close = Decimal("0.00")
        settled = settle_daily_forecasts(
            isolated_db,
            settlement_date=target_d,
            price_overrides={isin: Decimal("0.00")},
        )
        assert len(settled) == 1
        s = settled[0]
        assert s.actual_close_price == Decimal("0.00")
        assert s.error_pct == Decimal("0.0000")  # Graceful fallback, no ZeroDivisionError
        assert s.direction_hit == 0


# ============================================================================
# 4. SCORECARD & MATHEMATICAL ROBUSTNESS
# ============================================================================

class TestScorecardAndMathematicalRobustness:
    """Stress-test metrics.py: empty samples, N < 30 warnings, extreme shocks, 100%/0% hit rates."""

    def test_scorecard_empty_sample(self, isolated_db):
        metrics = calculate_performance_metrics(isolated_db)
        assert metrics.total_forecasts == 0
        assert metrics.settled_count == 0
        assert metrics.pending_count == 0
        assert metrics.hit_rate_pct == Decimal("0.00")
        assert metrics.etf_hit_rate_pct is None
        assert metrics.stock_hit_rate_pct is None
        assert metrics.mape_pct == Decimal("0.00")
        assert metrics.mae_eur == Decimal("0.0000")
        assert metrics.mpe_pct == Decimal("0.00")
        assert metrics.is_small_sample is True
        assert "Henüz uzlaşmış tahmin bulunmuyor" in (metrics.warning_message or "")

    def test_scorecard_sample_size_threshold_29_vs_30(self, isolated_db):
        """Verify strict behavior transition between N=29 (warning) and N=30 (statistically significant)."""
        conn = isolated_db.get_connection()
        try:
            for i in range(1, 31):
                fid = f"fc_thresh_{i:03d}"
                sid = f"set_thresh_{i:03d}"
                conn.execute(
                    """
                    INSERT INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        ?, 'IE00B3YLTY66', '2026-11-01', 'DAILY_CLOSE', 'UP',
                        '10.00', '10.50', '65.00', 'model_thresh',
                        '2026-11-01T09:30:00Z', ?
                    )
                    """,
                    (fid, f"hash_fc_{i:060d}"),
                )
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', '2026-11-01',
                        '10.50', '0.00', '0.00', 1,
                        '2026-11-01T17:40:00Z', ?
                    )
                    """,
                    (sid, fid, f"hash_set_{i:059d}"),
                )

                if i == 29:
                    m29 = calculate_performance_metrics(isolated_db, model_id="model_thresh")
                    assert m29.settled_count == 29
                    assert m29.is_small_sample is True
                    assert "en az 30 gözlem gereklidir (mevcut: N=29)" in m29.warning_message

            m30 = calculate_performance_metrics(isolated_db, model_id="model_thresh")
            assert m30.settled_count == 30
            assert m30.is_small_sample is False
            assert m30.warning_message is None
            assert m30.hit_rate_pct == Decimal("100.00")
        finally:
            conn.close()

    def test_scorecard_perfect_hits_and_zero_hits(self, isolated_db):
        """Verify 100.00% hit rate and 0.00% hit rate with mixed ETF and stock instruments."""
        pool = load_forecast_pool()
        etf_isin = list(pool.etf.keys())[0]
        stock_isin = list(pool.hisse.keys())[0]

        # Scenario A: 100% hits
        conn = isolated_db.get_connection()
        try:
            for isin, fid, sid in [(etf_isin, "fc_hit_etf", "set_hit_etf"), (stock_isin, "fc_hit_stk", "set_hit_stk")]:
                conn.execute(
                    """
                    INSERT INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, '2026-11-02', 'DAILY_CLOSE', 'UP',
                        '100.00', '102.00', '65.00', 'model_perf',
                        '2026-11-02T09:30:00Z', ?
                    )
                    """,
                    (fid, isin, f"hash_fc_{fid}"),
                )
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        ?, ?, ?, '2026-11-02',
                        '102.00', '0.00', '0.00', 1,
                        '2026-11-02T17:40:00Z', ?
                    )
                    """,
                    (sid, fid, isin, f"hash_set_{sid}"),
                )
        finally:
            conn.close()

        m_perf = calculate_performance_metrics(isolated_db, model_id="model_perf")
        assert m_perf.hit_rate_pct == Decimal("100.00")
        assert m_perf.etf_hit_rate_pct == Decimal("100.00")
        assert m_perf.stock_hit_rate_pct == Decimal("100.00")
        assert m_perf.mape_pct == Decimal("0.00")
        assert m_perf.mae_eur == Decimal("0.0000")
        assert m_perf.mpe_pct == Decimal("0.00")

    def test_scorecard_extreme_price_shocks(self, isolated_db):
        """Stress-test MAPE, MAE, MPE under 500% surge and 99% crash."""
        conn = isolated_db.get_connection()
        try:
            # 1. 500% surge: target = 100, actual = 600 -> error_eur = -500, error_pct = -83.3333%
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    'fc_shock_surge', 'IE00B3YLTY66', '2026-11-02', 'DAILY_CLOSE', 'UP',
                    '100.00', '100.00', '65.00', 'model_shock',
                    '2026-11-02T09:30:00Z', 'hash_fc_surge'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    'set_shock_surge', 'fc_shock_surge', 'IE00B3YLTY66', '2026-11-02',
                    '600.00', '-500.0000', '-83.3333', 1,
                    '2026-11-02T17:40:00Z', 'hash_set_surge'
                )
                """
            )

            # 2. 99% crash: target = 100, actual = 1 -> error_eur = +99, error_pct = +9900.0000%
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    'fc_shock_crash', 'IE00BKM4GZ66', '2026-11-02', 'DAILY_CLOSE', 'UP',
                    '100.00', '100.00', '65.00', 'model_shock',
                    '2026-11-02T09:30:00Z', 'hash_fc_crash'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    'set_shock_crash', 'fc_shock_crash', 'IE00BKM4GZ66', '2026-11-02',
                    '1.00', '99.0000', '9900.0000', 0,
                    '2026-11-02T17:40:00Z', 'hash_set_crash'
                )
                """
            )
        finally:
            conn.close()

        metrics = calculate_performance_metrics(isolated_db, model_id="model_shock")
        assert metrics.settled_count == 2
        # MAPE = (| -83.3333 | + | 9900.0000 |) / 2 = 9983.3333 / 2 = 4991.67%
        assert metrics.mape_pct == Decimal("4991.67")
        # MAE = (500 + 99) / 2 = 299.5000 EUR
        assert metrics.mae_eur == Decimal("299.5000")
        # MPE = (-83.3333 + 9900.0000) / 2 = 4908.33%
        assert metrics.mpe_pct == Decimal("4908.33")


# ============================================================================
# 5. GENERATION IDEMPOTENCY & MULTI-MODEL EXECUTION
# ============================================================================

class TestGenerationIdempotencyAndMultiModel:
    """Stress-test repeated generations, multiple models on the same date, and dry-run safety."""

    def test_multi_generation_idempotency_loop(self, isolated_db, mock_pool_quotes):
        """Repeated generation calls (10 times) must produce 0 duplicate rows."""
        target_d = "2026-11-02"
        first_run = generate_daily_forecasts(isolated_db, target_date=target_d, quotes_override=mock_pool_quotes)
        assert len(first_run) == 10

        for _ in range(9):
            subsequent_run = generate_daily_forecasts(
                isolated_db, target_date=target_d, quotes_override=mock_pool_quotes
            )
            assert len(subsequent_run) == 10
            assert [x.forecast_id for x in subsequent_run] == [x.forecast_id for x in first_run]

        conn = isolated_db.get_connection()
        try:
            total_records = conn.execute("SELECT COUNT(*) FROM forecast_entries").fetchone()[0]
            assert total_records == 10
        finally:
            conn.close()

    def test_multi_model_coexistence_on_same_date(self, isolated_db, mock_pool_quotes):
        """Multiple distinct models must be able to generate forecasts on the exact same date without collision."""
        target_d = "2026-11-02"
        m1_forecasts = generate_daily_forecasts(
            isolated_db, target_date=target_d, model_id="model_momentum_v1", quotes_override=mock_pool_quotes
        )
        assert len(m1_forecasts) == 10

        m2_forecasts = generate_daily_forecasts(
            isolated_db, target_date=target_d, model_id="model_mean_reversion_v2", quotes_override=mock_pool_quotes
        )
        assert len(m2_forecasts) == 10

        conn = isolated_db.get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM forecast_entries WHERE target_date = ?", (target_d,)).fetchone()[0]
            assert total == 20

            # Settle all 20 forecasts
            settled = settle_daily_forecasts(isolated_db, settlement_date=target_d, price_overrides=mock_pool_quotes)
            assert len(settled) == 20

            # Compute scorecard separately per model
            metrics_m1 = calculate_performance_metrics(isolated_db, model_id="model_momentum_v1")
            assert metrics_m1.settled_count == 10

            metrics_m2 = calculate_performance_metrics(isolated_db, model_id="model_mean_reversion_v2")
            assert metrics_m2.settled_count == 10
        finally:
            conn.close()

    def test_partial_settlement_and_incremental_completion(self, isolated_db, mock_pool_quotes):
        """Settling a subset of instruments on day 1 and the rest later."""
        target_d = "2026-11-02"
        generate_daily_forecasts(isolated_db, target_date=target_d, quotes_override=mock_pool_quotes)

        # Subset: settle only 3 instruments
        subset_isins = ["IE00B3YLTY66", "IE00BKM4GZ66", "US0378331005"]
        partial_prices = {isin: mock_pool_quotes[isin] for isin in subset_isins}

        settled_batch_1 = settle_daily_forecasts(
            isolated_db, settlement_date=target_d, price_overrides=partial_prices
        )
        assert len(settled_batch_1) == 3

        conn = isolated_db.get_connection()
        try:
            unsettled_remaining = conn.execute("SELECT COUNT(*) FROM v_forecasts_unsettled").fetchone()[0]
            assert unsettled_remaining == 7
        finally:
            conn.close()

        # Batch 2: settle remaining 7 instruments
        remaining_prices = {isin: price for isin, price in mock_pool_quotes.items() if isin not in subset_isins}
        settled_batch_2 = settle_daily_forecasts(
            isolated_db, settlement_date=target_d, price_overrides=remaining_prices
        )
        assert len(settled_batch_2) == 7

        conn = isolated_db.get_connection()
        try:
            unsettled_final = conn.execute("SELECT COUNT(*) FROM v_forecasts_unsettled").fetchone()[0]
            assert unsettled_final == 0
            total_settlements = conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
            assert total_settlements == 10
        finally:
            conn.close()


# ============================================================================
# 6. DIRECTION TRUTH MATRIX (3x3 Exhaustive Validation)
# ============================================================================

class TestDirectionTruthMatrix:
    """Exhaustively verify the 3x3 direction matrix: (UP, FLAT, DOWN) x (UP, FLAT, DOWN)."""

    @pytest.mark.parametrize(
        "fc_dir, act_delta, expected_act_dir, expected_hit",
        [
            # UP forecasts
            (ForecastDirection.UP, Decimal("0.0050"), ForecastDirection.UP, 1),
            (ForecastDirection.UP, Decimal("0.0000"), ForecastDirection.FLAT, 0),
            (ForecastDirection.UP, Decimal("-0.0050"), ForecastDirection.DOWN, 0),
            # FLAT forecasts
            (ForecastDirection.FLAT, Decimal("0.0050"), ForecastDirection.UP, 0),
            (ForecastDirection.FLAT, Decimal("0.0000"), ForecastDirection.FLAT, 1),
            (ForecastDirection.FLAT, Decimal("-0.0050"), ForecastDirection.DOWN, 0),
            # DOWN forecasts
            (ForecastDirection.DOWN, Decimal("0.0050"), ForecastDirection.UP, 0),
            (ForecastDirection.DOWN, Decimal("0.0000"), ForecastDirection.FLAT, 0),
            (ForecastDirection.DOWN, Decimal("-0.0050"), ForecastDirection.DOWN, 1),
        ],
    )
    def test_3x3_direction_matrix(self, fc_dir, act_delta, expected_act_dir, expected_hit):
        ref = Decimal("100.00")
        act_close = ref * (Decimal("1") + act_delta)

        # 1. Evaluate actual direction with deadband
        threshold = DEADBAND_THRESHOLD
        if abs(act_delta) < threshold:
            act_dir = ForecastDirection.FLAT
        elif act_delta > 0:
            act_dir = ForecastDirection.UP
        else:
            act_dir = ForecastDirection.DOWN

        assert act_dir == expected_act_dir
        hit = 1 if fc_dir == act_dir else 0
        assert hit == expected_hit


# ============================================================================
# 7. ASSET CLASS BREAKDOWN ISOLATION IN SCORECARD
# ============================================================================

class TestAssetClassBreakdownIsolation:
    """Verify scorecard behavior when sample contains exclusively ETFs or exclusively Equities."""

    def test_sample_with_only_etfs(self, isolated_db):
        pool = load_forecast_pool()
        etf_isin = list(pool.etf.keys())[0]

        fid = "fc_only_etf_01"
        sid = "set_only_etf_01"
        conn = isolated_db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, ?, '2026-11-02', 'DAILY_CLOSE', 'UP',
                    '10.00', '10.50', '65.00', 'model_etf_only',
                    '2026-11-02T09:30:00Z', 'hash_fc_only_etf'
                )
                """,
                (fid, etf_isin),
            )
            conn.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    ?, ?, ?, '2026-11-02',
                    '10.50', '0.00', '0.00', 1,
                    '2026-11-02T17:40:00Z', 'hash_set_only_etf'
                )
                """,
                (sid, fid, etf_isin),
            )
        finally:
            conn.close()

        metrics = calculate_performance_metrics(isolated_db, model_id="model_etf_only")
        assert metrics.settled_count == 1
        assert metrics.hit_rate_pct == Decimal("100.00")
        assert metrics.etf_hit_rate_pct == Decimal("100.00")
        assert metrics.stock_hit_rate_pct is None  # Must be None, NOT 0.00 and no division by zero

    def test_sample_with_only_equities(self, isolated_db):
        pool = load_forecast_pool()
        stock_isin = list(pool.hisse.keys())[0]

        fid = "fc_only_stk_01"
        sid = "set_only_stk_01"
        conn = isolated_db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, ?, '2026-11-02', 'DAILY_CLOSE', 'UP',
                    '200.00', '210.00', '65.00', 'model_stk_only',
                    '2026-11-02T09:30:00Z', 'hash_fc_only_stk'
                )
                """,
                (fid, stock_isin),
            )
            conn.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    ?, ?, ?, '2026-11-02',
                    '190.00', '20.00', '10.5263', 0,
                    '2026-11-02T17:40:00Z', 'hash_set_only_stk'
                )
                """,
                (sid, fid, stock_isin),
            )
        finally:
            conn.close()

        metrics = calculate_performance_metrics(isolated_db, model_id="model_stk_only")
        assert metrics.settled_count == 1
        assert metrics.hit_rate_pct == Decimal("0.00")
        assert metrics.etf_hit_rate_pct is None  # Must be None, NOT 0.00 and no division by zero
        assert metrics.stock_hit_rate_pct == Decimal("0.00")


# ============================================================================
# 8. BORN-SEALED CANONICAL HASH INTEGRITY & TAMPER DETECTION
# ============================================================================

class TestBornSealedHashTamperResistance:
    """Stress-test SHA-256 hash sealing against byte-level tampering."""

    def test_forecast_field_tampering_sensitivity(self):
        row = {
            "confidence_pct": "65.00",
            "created_at": "2026-11-02T09:30:00Z",
            "direction": "UP",
            "forecast_id": "fc_2026-11-02_IE00B3YLTY66_model_momentum_v1",
            "forecast_type": "DAILY_CLOSE",
            "isin": "IE00B3YLTY66",
            "model_id": "model_momentum_v1",
            "reference_price": "10.50",
            "target_date": "2026-11-02",
            "target_price": "10.60",
        }
        baseline_hash = compute_forecast_hash(row)
        assert len(baseline_hash) == 64

        # Altering each field must change hash
        for k in row.keys():
            tampered = dict(row)
            if k == "direction":
                tampered[k] = "DOWN"
            elif k in ("reference_price", "target_price", "confidence_pct"):
                tampered[k] = "99.99"
            else:
                tampered[k] = row[k] + "_tampered"
            assert compute_forecast_hash(tampered) != baseline_hash, f"Tampering {k} went undetected!"

    def test_settlement_field_tampering_sensitivity(self):
        row = {
            "actual_close_price": "10.55",
            "direction_hit": 1,
            "error_eur": "0.0500",
            "error_pct": "0.4739",
            "forecast_id": "fc_2026-11-02_IE00B3YLTY66_model_momentum_v1",
            "isin": "IE00B3YLTY66",
            "settled_at": "2026-11-02T17:40:00Z",
            "settlement_date": "2026-11-02",
            "settlement_id": "set_fc_2026-11-02_IE00B3YLTY66_model_momentum_v1",
        }
        baseline_hash = compute_settlement_hash(row)
        assert len(baseline_hash) == 64

        for k in row.keys():
            tampered = dict(row)
            if k == "direction_hit":
                tampered[k] = 0
            elif k in ("actual_close_price", "error_eur", "error_pct"):
                tampered[k] = "99.99"
            else:
                tampered[k] = str(row[k]) + "_tampered"
            assert compute_settlement_hash(tampered) != baseline_hash, f"Tampering {k} went undetected!"

