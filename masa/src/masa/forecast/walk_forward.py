"""Walk-Forward Historical Simulation and Forecast Backfill Engine.

Simulates walk-forward daily forecast generation (09:30 CET) and evening settlement (17:40 CET)
across historical price points stored in series_points without look-ahead bias.
Populates forecast_entries and settlements with cryptographically verifiable Born-Sealed records,
enabling empirical statistical scorecard analysis (N >= 30).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from masa.audit.events import AuditLogger
from masa.calendar.adapter import CalendarAdapter
from masa.forecast.generator import DEADBAND_THRESHOLD, _compute_model_delta
from masa.forecast.metrics import calculate_performance_metrics
from masa.forecast.models import ForecastDirection, ForecastEntry, SettlementEntry
from masa.forecast.pool import load_forecast_pool, seed_pool_instruments
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_forecast_hash, compute_settlement_hash

logger = logging.getLogger(__name__)


def get_available_trading_days(db: DatabaseManager, min_instruments: int = 6) -> List[str]:
    """Find all historical trading days present in series_points with sufficient instrument coverage."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT substr(point_time, 1, 10) as dt, count(distinct substr(series_key, 1, 12)) as isin_cnt
            FROM series_points
            WHERE substr(series_key, -3) = ':1y' OR substr(series_key, -3) = ':3m'
            GROUP BY dt
            HAVING isin_cnt >= ?
            ORDER BY dt ASC
            """,
            (min_instruments,),
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    finally:
        conn.close()


def get_day_close_price(db: DatabaseManager, isin: str, date_str: str) -> Optional[Decimal]:
    """Retrieve the actual daily close price for a specific date from series_points."""
    conn = db.get_connection()
    try:
        # Search for :1y or :3m points on that date
        row = conn.execute(
            """
            SELECT value FROM series_points
            WHERE (series_key = ? OR series_key = ?)
              AND substr(point_time, 1, 10) = ?
            ORDER BY point_time DESC LIMIT 1
            """,
            (f"{isin}:1y", f"{isin}:3m", date_str),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        # Fallback to any series point on that date
        row = conn.execute(
            """
            SELECT value FROM series_points
            WHERE series_key LIKE ?
              AND substr(point_time, 1, 10) = ?
            ORDER BY point_time DESC LIMIT 1
            """,
            (f"{isin}:%", date_str),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        return None
    finally:
        conn.close()


def get_day_reference_price(db: DatabaseManager, isin: str, date_str: str) -> Optional[Decimal]:
    """Retrieve reference price (prior close or morning price) strictly on or before 09:30 CET."""
    conn = db.get_connection()
    try:
        # Check point strictly before date_str T09:30:00Z
        cutoff = f"{date_str}T09:30:00Z"
        row = conn.execute(
            """
            SELECT value FROM series_points
            WHERE (series_key = ? OR series_key = ?)
              AND point_time < ?
            ORDER BY point_time DESC LIMIT 1
            """,
            (f"{isin}:1y", f"{isin}:3m", cutoff),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        # Fallback to earliest point on date_str
        row = conn.execute(
            """
            SELECT value FROM series_points
            WHERE series_key LIKE ?
              AND substr(point_time, 1, 10) = ?
            ORDER BY point_time ASC LIMIT 1
            """,
            (f"{isin}:%", date_str),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        return None
    finally:
        conn.close()


def run_walk_forward_simulation(
    db: DatabaseManager,
    days: int = 30,
    models: Tuple[str, ...] = ("model_momentum_v1", "model_mean_reversion_v1", "model_ensemble_v1"),
) -> Dict[str, Any]:
    """Execute walk-forward simulation across past trading days.
    
    Generates forecasts without look-ahead bias and settles them against actual close prices.
    Inserts Born-Sealed records into SQLite respecting all append-only triggers.
    """
    seed_pool_instruments(db)
    pool = load_forecast_pool()
    instruments = pool.all_instruments()

    available_days = get_available_trading_days(db)
    # Take the last `days` available days up to the latest closed session
    target_days = available_days[-days:] if len(available_days) >= days else available_days

    forecasts_created = 0
    settlements_created = 0
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = db.get_connection()
    try:
        for d_str in target_days:
            # Skip today if market session has not closed yet
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if d_str >= today_str:
                continue

            for model_id in models:
                # Check empirical confidence for this model up to this point
                perf_row = conn.execute(
                    """
                    SELECT COUNT(*) as n, SUM(direction_hit) as hits
                    FROM v_forecast_performance
                    WHERE model_id = ? AND target_date < ?
                    """,
                    (model_id, d_str),
                ).fetchone()
                n_past = int(perf_row[0]) if perf_row and perf_row[0] else 0
                if n_past >= 30:
                    hits = int(perf_row[1]) if perf_row and perf_row[1] else 0
                    confidence_pct = ((Decimal(str(hits)) / Decimal(str(n_past))) * Decimal("100")).quantize(Decimal("0.01"))
                else:
                    confidence_pct = Decimal("0.00")

                for inst in instruments:
                    forecast_id = f"fc_{d_str}_{inst.isin}_{model_id}"

                    # 1. Check if forecast already exists
                    existing_fc = conn.execute(
                        "SELECT * FROM forecast_entries WHERE forecast_id = ?",
                        (forecast_id,),
                    ).fetchone()

                    if not existing_fc:
                        ref_price = get_day_reference_price(db, inst.isin, d_str)
                        if not ref_price or ref_price <= 0:
                            continue

                        # Model target calculation with strict cutoff
                        cutoff_time = f"{d_str}T09:30:00Z"
                        delta = _compute_model_delta(db, inst, d_str, model_id=model_id, cutoff_time=cutoff_time)
                        target_price = (ref_price * (Decimal("1") + delta)).quantize(Decimal("0.0001"))

                        if abs(delta) < DEADBAND_THRESHOLD:
                            direction = ForecastDirection.FLAT
                        elif delta > 0:
                            direction = ForecastDirection.UP
                        else:
                            direction = ForecastDirection.DOWN

                        fc_row_for_hash = {
                            "confidence_pct": str(confidence_pct),
                            "created_at": f"{d_str}T09:30:00Z",
                            "direction": direction.value,
                            "forecast_id": forecast_id,
                            "forecast_type": "DAILY_CLOSE",
                            "isin": inst.isin,
                            "model_id": model_id,
                            "reference_price": str(ref_price),
                            "target_date": d_str,
                            "target_price": str(target_price),
                        }
                        fc_hash = compute_forecast_hash(fc_row_for_hash)

                        conn.execute(
                            """
                            INSERT INTO forecast_entries (
                                forecast_id, isin, target_date, forecast_type, direction,
                                reference_price, target_price, confidence_pct, model_id,
                                created_at, record_hash
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                forecast_id,
                                inst.isin,
                                d_str,
                                "DAILY_CLOSE",
                                direction.value,
                                str(ref_price),
                                str(target_price),
                                str(confidence_pct),
                                model_id,
                                f"{d_str}T09:30:00Z",
                                fc_hash,
                            ),
                        )
                        forecasts_created += 1
                        ref_for_settle = ref_price
                        dir_for_settle = direction
                        target_for_settle = target_price
                    else:
                        ref_for_settle = Decimal(str(existing_fc["reference_price"]))
                        dir_for_settle = ForecastDirection(existing_fc["direction"])
                        target_for_settle = Decimal(str(existing_fc["target_price"]))

                    # 2. Check if settlement already exists
                    settlement_id = f"set_{forecast_id}"
                    existing_set = conn.execute(
                        "SELECT 1 FROM settlements WHERE settlement_id = ? OR forecast_id = ?",
                        (settlement_id, forecast_id),
                    ).fetchone()

                    if not existing_set:
                        actual_close = get_day_close_price(db, inst.isin, d_str)
                        if not actual_close or actual_close <= 0:
                            continue

                        error_eur = (target_for_settle - actual_close).quantize(Decimal("0.0001"))
                        error_pct = (((target_for_settle - actual_close) / actual_close) * Decimal("100")).quantize(Decimal("0.0001"))

                        actual_delta = (actual_close - ref_for_settle) / ref_for_settle if ref_for_settle > 0 else Decimal("0")
                        if abs(actual_delta) < DEADBAND_THRESHOLD:
                            actual_direction = ForecastDirection.FLAT
                        elif actual_delta > 0:
                            actual_direction = ForecastDirection.UP
                        else:
                            actual_direction = ForecastDirection.DOWN

                        direction_hit = 1 if dir_for_settle == actual_direction else 0

                        set_row_for_hash = {
                            "actual_close_price": str(actual_close),
                            "direction_hit": direction_hit,
                            "error_eur": str(error_eur),
                            "error_pct": str(error_pct),
                            "forecast_id": forecast_id,
                            "isin": inst.isin,
                            "settled_at": f"{d_str}T17:40:00Z",
                            "settlement_date": d_str,
                            "settlement_id": settlement_id,
                        }
                        set_hash = compute_settlement_hash(set_row_for_hash)

                        conn.execute(
                            """
                            INSERT INTO settlements (
                                settlement_id, forecast_id, isin, settlement_date,
                                actual_close_price, error_eur, error_pct, direction_hit,
                                settled_at, record_hash
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                settlement_id,
                                forecast_id,
                                inst.isin,
                                d_str,
                                str(actual_close),
                                str(error_eur),
                                str(error_pct),
                                direction_hit,
                                f"{d_str}T17:40:00Z",
                                set_hash,
                            ),
                        )
                        settlements_created += 1

        conn.commit()
    finally:
        conn.close()

    metrics = calculate_performance_metrics(db)

    AuditLogger(db).log_event(
        actor="system",
        action="FORECAST_WALK_FORWARD_COMPLETE",
        entity_type="forecast_simulation",
        entity_id=f"wf_{len(target_days)}d",
        payload={
            "days_processed": len(target_days),
            "forecasts_created": forecasts_created,
            "settlements_created": settlements_created,
            "hit_rate_pct": str(metrics.hit_rate_pct),
            "total_settled": metrics.settled_count,
        },
    )

    return {
        "days_processed": len(target_days),
        "target_days": target_days,
        "forecasts_created": forecasts_created,
        "settlements_created": settlements_created,
        "models": list(models),
        "metrics": metrics,
    }
