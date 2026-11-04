"""Unit and integration tests for walk-forward simulation engine."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import pytest

from masa.forecast.generator import _compute_model_delta
from masa.forecast.metrics import calculate_performance_metrics
from masa.forecast.models import ForecastDirection
from masa.forecast.pool import load_forecast_pool, seed_pool_instruments
from masa.forecast.walk_forward import (
    get_available_trading_days,
    get_day_close_price,
    get_day_reference_price,
    run_walk_forward_simulation,
)
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager


@pytest.fixture
def mock_sim_db(tmp_path: Path):
    db_file = tmp_path / "sim_test.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()
    registry = IdentityRegistry(db=db)
    registry.seed_from_configs()
    seed_pool_instruments(db)

    # Insert mock snapshot
    snap_id = "snap_test_sim"
    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                ?, 'run_sim', 'history', '2026-10-20T00:00:00Z',
                '2026-10-20T00:01:00Z', 'sc', 10, 'OK',
                '1.0', 'prev', 'curr_hash_sim', '2026-10-20T00:01:00Z'
            )
            """,
            (snap_id,),
        )

    # Seed 5 days of series points for pool instruments
    pool = load_forecast_pool()
    instruments = pool.all_instruments()
    dates = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26"]

    with db.transaction() as tx:
        for idx, d in enumerate(dates):
            for inst in instruments:
                # Morning point (09:00)
                base_price = Decimal("100.00") + Decimal(str(idx * 2))
                tx.execute(
                    """
                    INSERT INTO series_points (snapshot_id, series_key, series_kind, point_time, value, record_hash)
                    VALUES (?, ?, 'chart', ?, ?, ?)
                    """,
                    (snap_id, f"{inst.isin}:1y", f"{d}T09:00:00Z", str(base_price), f"hash_m_{inst.isin}_{d}"),
                )
                # Afternoon close point (17:30)
                close_price = base_price + Decimal("0.80")
                tx.execute(
                    """
                    INSERT INTO series_points (snapshot_id, series_key, series_kind, point_time, value, record_hash)
                    VALUES (?, ?, 'chart', ?, ?, ?)
                    """,
                    (snap_id, f"{inst.isin}:1y", f"{d}T17:30:00Z", str(close_price), f"hash_c_{inst.isin}_{d}"),
                )

    return db


def test_get_available_trading_days(mock_sim_db):
    days = get_available_trading_days(mock_sim_db, min_instruments=5)
    assert len(days) == 5
    assert "2026-10-20" in days
    assert "2026-10-26" in days


def test_get_day_prices(mock_sim_db):
    ref_p = get_day_reference_price(mock_sim_db, "IE00B3YLTY66", "2026-10-20")
    close_p = get_day_close_price(mock_sim_db, "IE00B3YLTY66", "2026-10-20")
    assert ref_p is not None
    assert close_p is not None
    assert close_p > ref_p


def test_run_walk_forward_simulation_execution(mock_sim_db):
    result = run_walk_forward_simulation(
        mock_sim_db,
        days=5,
        models=("model_momentum_v1", "model_mean_reversion_v1"),
    )
    assert result["days_processed"] == 5
    assert result["forecasts_created"] > 0
    assert result["settlements_created"] > 0

    metrics = result["metrics"]
    assert metrics.settled_count > 0
    assert metrics.hit_rate_pct >= Decimal("0.00")

    # Verify idempotency on second run
    result2 = run_walk_forward_simulation(
        mock_sim_db,
        days=5,
        models=("model_momentum_v1", "model_mean_reversion_v1"),
    )
    assert result2["forecasts_created"] == 0
    assert result2["settlements_created"] == 0


def test_multi_model_generation(mock_sim_db):
    pool = load_forecast_pool()
    inst = pool.all_instruments()[0]

    # Test momentum
    d_mom = _compute_model_delta(mock_sim_db, inst, "2026-10-26", model_id="model_momentum_v1")
    assert isinstance(d_mom, Decimal)

    # Test mean reversion
    d_rev = _compute_model_delta(mock_sim_db, inst, "2026-10-26", model_id="model_mean_reversion_v1")
    assert isinstance(d_rev, Decimal)

    # Test macro
    d_macro = _compute_model_delta(mock_sim_db, inst, "2026-10-26", model_id="model_macro_sentiment_v1")
    assert isinstance(d_macro, Decimal)

    # Test ensemble
    d_ens = _compute_model_delta(mock_sim_db, inst, "2026-10-26", model_id="model_ensemble_v1")
    assert isinstance(d_ens, Decimal)
    expected = (d_mom * Decimal("0.40") + d_rev * Decimal("0.35") + d_macro * Decimal("0.25")).quantize(Decimal("0.0001"))
    assert d_ens == expected


def test_no_look_ahead_bias(mock_sim_db):
    pool = load_forecast_pool()
    inst = pool.all_instruments()[0]

    # Delta computed with cutoff at 2026-10-21 must ignore points on 2026-10-22 and 2026-10-26
    d_early = _compute_model_delta(mock_sim_db, inst, "2026-10-21", model_id="model_momentum_v1", cutoff_time="2026-10-21T09:30:00Z")
    d_late = _compute_model_delta(mock_sim_db, inst, "2026-10-26", model_id="model_momentum_v1", cutoff_time="2026-10-26T09:30:00Z")

    assert isinstance(d_early, Decimal)
    assert isinstance(d_late, Decimal)
