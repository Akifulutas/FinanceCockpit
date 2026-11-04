"""Daily Forecast Generator (09:30 CET) - IP-5.

Generates intra-day price target, direction, and confidence forecasts for 5 ETFs + 5 Equities.
Applies a 0.10% deadband: |expected_return| < 0.10% produces FLAT direction.
Born-Sealed: Hashes each record before insertion; idempotent across multiple runs on the same date.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import logging
from typing import Any, Dict, List, Optional

from masa.audit.events import AuditLogger
from masa.forecast.models import ForecastDirection, ForecastEntry, PoolInstrument
from masa.forecast.pool import load_forecast_pool
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_forecast_hash

logger = logging.getLogger(__name__)

DEADBAND_THRESHOLD = Decimal("0.0010")  # 0.10%
DEADBAND_PCT = DEADBAND_THRESHOLD


class MissingQuoteError(RuntimeError):
    """Raised when no quote or price observation is available for an instrument."""
    pass


def _compute_model_delta(
    db: DatabaseManager,
    inst: PoolInstrument,
    target_date_str: str,
    model_id: str = "model_momentum_v1",
    cutoff_time: Optional[str] = None,
) -> Decimal:
    """Compute a deterministic model delta based on actual historical series points / quotes.
    
    Supports:
    - model_momentum_v1: Trend and momentum following with 0.50 dampener.
    - model_mean_reversion_v1: Z-score distance from 15-period mean.
    - model_macro_sentiment_v1: Beta-adjusted ACWI market return.
    - model_ensemble_v1: Weighted consensus of momentum, mean reversion, and macro.
    
    Uses intraday 1m/3m or daily series points.
    Never uses pseudo-random numbers or MD5 hashes.
    If insufficient points exist, returns 0.0000 (FLAT direction).
    """
    if model_id == "model_ensemble_v1":
        d_mom = _compute_model_delta(db, inst, target_date_str, "model_momentum_v1", cutoff_time)
        d_rev = _compute_model_delta(db, inst, target_date_str, "model_mean_reversion_v1", cutoff_time)
        d_macro = _compute_model_delta(db, inst, target_date_str, "model_macro_sentiment_v1", cutoff_time)
        return (d_mom * Decimal("0.40") + d_rev * Decimal("0.35") + d_macro * Decimal("0.25")).quantize(Decimal("0.0001"))

    conn = db.get_connection()
    try:
        # Check series_points for a single explicit timeframe (1m, 3m, or 1y) - never mix timeframes
        target_tf = None
        for tf in ("1m", "3m", "1y"):
            has_tf = conn.execute(
                "SELECT 1 FROM series_points WHERE series_key = ? LIMIT 1",
                (f"{inst.isin}:{tf}",),
            ).fetchone()
            if has_tf:
                target_tf = tf
                break

        if target_tf:
            if cutoff_time:
                rows = conn.execute(
                    """
                    SELECT value FROM series_points
                    WHERE series_key = ? AND point_time <= ?
                    ORDER BY point_time DESC LIMIT 20
                    """,
                    (f"{inst.isin}:{target_tf}", cutoff_time),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT value FROM series_points
                    WHERE series_key = ?
                    ORDER BY point_time DESC LIMIT 20
                    """,
                    (f"{inst.isin}:{target_tf}",),
                ).fetchall()

            if model_id == "model_mean_reversion_v1" and len(rows) >= 5:
                prices = [float(r[0]) for r in rows[:15]]
                current_p = prices[0]
                mean_p = sum(prices) / len(prices)
                variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
                std_p = variance ** 0.5
                if std_p > 0:
                    z = (current_p - mean_p) / std_p
                    if z > 1.0:
                        delta = max(-0.015, -0.004 * z)
                        return Decimal(str(round(delta, 4)))
                    elif z < -1.0:
                        delta = min(0.015, -0.004 * z)
                        return Decimal(str(round(delta, 4)))
                return Decimal("0.0000")

            if model_id == "model_macro_sentiment_v1":
                acwi_query = (
                    "SELECT value FROM series_points WHERE series_key = 'IE00B3YLTY66:1y' " +
                    ("AND point_time <= ? " if cutoff_time else "") +
                    "ORDER BY point_time DESC LIMIT 5"
                )
                acwi_rows = conn.execute(
                    acwi_query,
                    (cutoff_time,) if cutoff_time else (),
                ).fetchall()
                if len(acwi_rows) >= 2:
                    acwi_now = Decimal(str(acwi_rows[0][0]))
                    acwi_prev = Decimal(str(acwi_rows[-1][0]))
                    if acwi_prev > 0:
                        acwi_ret = (acwi_now - acwi_prev) / acwi_prev
                        betas = {
                            "IE00B3YLTY66": Decimal("1.00"),
                            "IE00BKM4GZ66": Decimal("1.15"),
                            "IE00BP3QZ825": Decimal("1.25"),
                            "IE00BP3QZB59": Decimal("0.85"),
                            "IE00B4L5Y983": Decimal("1.00"),
                        }
                        beta = betas.get(inst.isin, Decimal("1.30") if inst.asset_type == "EQUITY" else Decimal("1.00"))
                        d = (acwi_ret * beta * Decimal("0.40")).quantize(Decimal("0.0001"))
                        return max(Decimal("-0.0250"), min(Decimal("0.0250"), d))

            if len(rows) >= 2:
                p1 = Decimal(str(rows[0][0]))
                p0 = Decimal(str(rows[1][0]))
                if p0 > 0:
                    raw_delta = (p1 - p0) / p0
                    return (raw_delta * Decimal("0.50")).quantize(Decimal("0.0001"))

        # Fallback to recent quote observations if available
        q_rows = conn.execute(
            """
            SELECT computed_mid FROM quotes
            WHERE isin = ?
            ORDER BY quote_id DESC LIMIT 2
            """,
            (inst.isin,),
        ).fetchall()
        if len(q_rows) >= 2 and q_rows[0][0] and q_rows[1][0]:
            p1 = Decimal(str(q_rows[0][0]))
            p0 = Decimal(str(q_rows[1][0]))
            if p0 > 0:
                raw_delta = (p1 - p0) / p0
                return (raw_delta * Decimal("0.50")).quantize(Decimal("0.0001"))
    except Exception as e:
        logger.debug("Series point calculation skipped for %s: %s", inst.isin, e)
    finally:
        conn.close()

    # Deterministic fallback when no history: 0 delta (FLAT)
    return Decimal("0.0000")


def get_reference_price(
    db: DatabaseManager,
    isin: str,
    quotes_override: Optional[Dict[str, Decimal]] = None,
) -> Decimal:
    """Retrieve the latest reference price for an instrument."""
    if quotes_override and isin in quotes_override:
        return Decimal(str(quotes_override[isin]))

    conn = db.get_connection()
    try:
        # 1. Latest computed_mid from quotes
        row = conn.execute(
            "SELECT computed_mid FROM quotes WHERE isin = ? ORDER BY quote_id DESC LIMIT 1",
            (isin,),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        # 2. Latest unit_price_displayed from position_observations
        row = conn.execute(
            "SELECT unit_price_displayed FROM position_observations WHERE isin = ? ORDER BY position_id DESC LIMIT 1",
            (isin,),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        # 3. Latest value from series_points
        row = conn.execute(
            "SELECT value FROM series_points WHERE series_key LIKE ? ORDER BY point_time DESC LIMIT 1",
            (f"{isin}:%",),
        ).fetchone()
        if row and row[0]:
            return Decimal(str(row[0]))

        raise MissingQuoteError(f"Quote not found for ISIN {isin}")
    finally:
        conn.close()


def generate_daily_forecasts(
    db: DatabaseManager,
    target_date: Optional[date | str] = None,
    model_id: str = "model_momentum_v1",
    dry_run: bool = False,
    quotes_override: Optional[Dict[str, Decimal]] = None,
) -> List[ForecastEntry]:
    """Generate daily closing forecasts for all 10 pool instruments (09:30 CET)."""
    from masa.forecast.pool import load_forecast_pool, seed_pool_instruments
    from masa.calendar.adapter import CalendarAdapter
    from zoneinfo import ZoneInfo

    if isinstance(target_date, str):
        target_date_str = target_date
    elif isinstance(target_date, (date, datetime)):
        target_date_str = target_date.strftime("%Y-%m-%d")
    else:
        target_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 0. Calendar Check: XETR trading session check
    cal = CalendarAdapter("XETR")
    if not cal.is_market_session(target_date_str) and not dry_run and quotes_override is None:
        logger.info("Bugün Xetra seansı kapalı (tatil/hafta sonu), tahmin üretimi atlandı: %s", target_date_str)
        return []

    # Ensure all 10 pool instruments are seeded into instruments and listings tables (prevents FK error)
    try:
        seed_pool_instruments(db)
    except Exception as e:
        logger.debug("seed_pool_instruments error: %s", e)

    pool = load_forecast_pool()
    instruments = pool.all_instruments()

    now_utc = datetime.now(timezone.utc)
    now_utc_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Late run tag (morning window expected ~09:30-10:00 CET)
    try:
        now_cet = now_utc.astimezone(ZoneInfo("Europe/Berlin"))
        is_late_run = (now_cet.hour > 10) or (now_cet.hour == 10 and now_cet.minute > 30)
    except Exception:
        is_late_run = False

    results: List[ForecastEntry] = []

    conn = db.get_connection()
    try:
        # Empirical Confidence Calculation (Audit Requirement: Suppressed if N < 30)
        perf_row = conn.execute(
            "SELECT COUNT(*) as n, SUM(direction_hit) as hits FROM v_forecast_performance WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        n_settled = int(perf_row[0]) if perf_row and perf_row[0] else 0
        if n_settled >= 30:
            hits = int(perf_row[1]) if perf_row and perf_row[1] else 0
            confidence_pct = ((Decimal(str(hits)) / Decimal(str(n_settled))) * Decimal("100")).quantize(Decimal("0.01"))
        else:
            confidence_pct = Decimal("0.00")  # Suppressed when N < 30

        for inst in instruments:
            # 1. Idempotency check: does a forecast already exist for (isin, target_date, model_id)?
            existing = conn.execute(
                "SELECT * FROM forecast_entries WHERE isin = ? AND target_date = ? AND model_id = ?",
                (inst.isin, target_date_str, model_id),
            ).fetchone()

            if existing:
                results.append(ForecastEntry.from_db_row(existing))
                continue

            # 2. Get reference price
            ref_price = get_reference_price(db, inst.isin, quotes_override=quotes_override)

            # 3. Model target calculation
            delta = _compute_model_delta(db, inst, target_date_str, model_id=model_id)
            target_price = (ref_price * (Decimal("1") + delta)).quantize(Decimal("0.0001"))

            # 4. Deadband direction evaluation (|delta| < 0.10% -> FLAT)
            if abs(delta) < DEADBAND_THRESHOLD:
                direction = ForecastDirection.FLAT
            elif delta > 0:
                direction = ForecastDirection.UP
            else:
                direction = ForecastDirection.DOWN

            forecast_id = f"fc_{target_date_str}_{inst.isin}_{model_id}"

            # 5. Born-Sealed hash computation
            row_dict_for_hash = {
                "confidence_pct": str(confidence_pct),
                "created_at": now_utc_str,
                "direction": direction.value,
                "forecast_id": forecast_id,
                "forecast_type": "DAILY_CLOSE",
                "isin": inst.isin,
                "model_id": model_id,
                "reference_price": str(ref_price),
                "target_date": target_date_str,
                "target_price": str(target_price),
            }
            rec_hash = compute_forecast_hash(row_dict_for_hash)

            entry = ForecastEntry(
                forecast_id=forecast_id,
                isin=inst.isin,
                target_date=target_date_str,
                forecast_type="DAILY_CLOSE",
                direction=direction,
                reference_price=ref_price,
                target_price=target_price,
                confidence_pct=confidence_pct,
                model_id=model_id,
                created_at=now_utc_str,
                record_hash=rec_hash,
            )

            # 6. Insert if not dry run
            if not dry_run:
                with db.transaction() as tx:
                    tx.execute(
                        """
                        INSERT INTO forecast_entries (
                            forecast_id, isin, target_date, forecast_type, direction,
                            reference_price, target_price, confidence_pct, model_id,
                            created_at, record_hash
                        ) VALUES (
                            :forecast_id, :isin, :target_date, :forecast_type, :direction,
                            :reference_price, :target_price, :confidence_pct, :model_id,
                            :created_at, :record_hash
                        )
                        """,
                        entry.to_db_row(),
                    )

                try:
                    AuditLogger(db).log_event(
                        actor="system",
                        action="FORECAST_GENERATED",
                        entity_type="forecast",
                        entity_id=forecast_id,
                        payload={
                            "isin": inst.isin,
                            "symbol": inst.sembol,
                            "target_date": target_date_str,
                            "direction": direction.value,
                            "ref_price": str(ref_price),
                            "target_price": str(target_price),
                            "record_hash": rec_hash,
                            "late_run": is_late_run,
                        },
                    )
                except Exception as exc:
                    logger.warning(f"Audit log yazılamadı: {exc}")

            results.append(entry)
    finally:
        conn.close()

    return results
