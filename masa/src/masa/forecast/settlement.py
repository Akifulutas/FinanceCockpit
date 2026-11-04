"""Evening Forecast Settlement Engine (17:40 CET) - IP-5.

Compares morning target forecasts against actual 17:00 CET closing prices.
Computes error_eur, error_pct, actual market direction (with 0.10% deadband),
and direction_hit (1 or 0).
Born-Sealed: Hashes each record before insertion; ensures single settlement per forecast.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional

from masa.audit.events import AuditLogger
from masa.forecast.generator import MissingQuoteError
from masa.forecast.models import ForecastDirection, SettlementEntry
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_settlement_hash

logger = logging.getLogger(__name__)

DEADBAND_THRESHOLD = Decimal("0.0010")  # 0.10%


def get_actual_close_price(
    db: DatabaseManager,
    isin: str,
    price_overrides: Optional[Dict[str, Decimal]] = None,
    settlement_date_str: Optional[str] = None,
) -> Optional[Decimal]:
    """Retrieve actual market closing price (17:40 Scalable price) for settlement."""
    if price_overrides is not None:
        if isin in price_overrides:
            return Decimal(str(price_overrides[isin]))
        return None

    from datetime import time
    from zoneinfo import ZoneInfo
    import pandas as pd

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT computed_mid, quote_timestamp FROM quotes WHERE isin = ? ORDER BY quote_id DESC LIMIT 1",
            (isin,),
        ).fetchone()
        if row and row[0]:
            if row[1] and settlement_date_str:
                try:
                    q_dt = pd.Timestamp(row[1]).to_pydatetime()
                    q_cet = q_dt.astimezone(ZoneInfo("Europe/Berlin"))
                    if q_cet.strftime("%Y-%m-%d") != settlement_date_str:
                        logger.warning(
                            "Kotasyon tarihi (%s) uzlaşma tarihiyle (%s) eşleşmiyor, uzlaşma atlandı: %s",
                            q_cet.strftime("%Y-%m-%d"), settlement_date_str, isin
                        )
                        return None
                    if q_cet.time() < time(17, 30):
                        logger.warning(
                            "Fiyat zaman damgası 17:30 CET öncesine ait (%s), seans kapanış fiyatı oluşmadığı için uzlaşma atlandı: %s",
                            q_cet.strftime("%H:%M:%S"), isin
                        )
                        return None
                except Exception as ex:
                    logger.debug("Quote timestamp parsing skipped: %s", ex)

            return Decimal(str(row[0]))

        raise MissingQuoteError(f"Quote not found for ISIN {isin}")
    finally:
        conn.close()


def settle_daily_forecasts(
    db: DatabaseManager,
    settlement_date: Optional[date | str] = None,
    price_overrides: Optional[Dict[str, Decimal]] = None,
) -> List[SettlementEntry]:
    """Settle open forecasts for the specified target date."""
    from masa.calendar.adapter import CalendarAdapter
    from zoneinfo import ZoneInfo

    if isinstance(settlement_date, str):
        settlement_date_str = settlement_date
    elif isinstance(settlement_date, (date, datetime)):
        settlement_date_str = settlement_date.strftime("%Y-%m-%d")
    else:
        settlement_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Calendar check: skip settlement on XETR holidays / weekends
    cal = CalendarAdapter("XETR")
    if not cal.is_market_session(settlement_date_str) and price_overrides is None:
        logger.info("Bugün Xetra seansı kapalı (tatil/hafta sonu), uzlaşma atlandı: %s", settlement_date_str)
        return []

    now_utc = datetime.now(timezone.utc)
    now_utc_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        now_cet = now_utc.astimezone(ZoneInfo("Europe/Berlin"))
        is_late_run = (now_cet.hour > 18) or (now_cet.hour == 18 and now_cet.minute > 30)
    except Exception:
        is_late_run = False

    conn = db.get_connection()
    try:
        # Fetch open forecasts for this target date from v_forecasts_unsettled
        open_forecasts = conn.execute(
            "SELECT * FROM v_forecasts_unsettled WHERE target_date = ?",
            (settlement_date_str,),
        ).fetchall()
    finally:
        conn.close()

    settled_entries: List[SettlementEntry] = []

    for f_row in open_forecasts:
        forecast_id = f_row["forecast_id"]
        isin = f_row["isin"]
        forecast_direction = ForecastDirection(f_row["direction"])
        ref_price = Decimal(str(f_row["reference_price"]))
        target_price = Decimal(str(f_row["target_price"]))

        try:
            actual_close = get_actual_close_price(db, isin, price_overrides=price_overrides, settlement_date_str=settlement_date_str)
        except MissingQuoteError:
            actual_close = None

        if actual_close is None:
            logger.warning(f"Kapanış fiyatı bulunamadı, uzlaşma atlandı: {isin} (forecast: {forecast_id})")
            continue

        # 1. Error calculations
        error_eur = (target_price - actual_close).quantize(Decimal("0.0001"))
        if actual_close > 0:
            error_pct = (((target_price - actual_close) / actual_close) * Decimal("100")).quantize(Decimal("0.0001"))
        else:
            error_pct = Decimal("0.0000")

        # 2. Actual direction evaluation (0.10% deadband)
        if ref_price > 0:
            actual_delta = (actual_close - ref_price) / ref_price
        else:
            actual_delta = Decimal("0")

        if abs(actual_delta) < DEADBAND_THRESHOLD:
            actual_direction = ForecastDirection.FLAT
        elif actual_delta > 0:
            actual_direction = ForecastDirection.UP
        else:
            actual_direction = ForecastDirection.DOWN

        direction_hit = 1 if forecast_direction == actual_direction else 0
        settlement_id = f"set_{forecast_id}"

        # 3. Born-Sealed hash computation
        row_dict_for_hash = {
            "actual_close_price": str(actual_close),
            "direction_hit": direction_hit,
            "error_eur": str(error_eur),
            "error_pct": str(error_pct),
            "forecast_id": forecast_id,
            "isin": isin,
            "settled_at": now_utc_str,
            "settlement_date": settlement_date_str,
            "settlement_id": settlement_id,
        }
        rec_hash = compute_settlement_hash(row_dict_for_hash)

        entry = SettlementEntry(
            settlement_id=settlement_id,
            forecast_id=forecast_id,
            isin=isin,
            settlement_date=settlement_date_str,
            actual_close_price=actual_close,
            error_eur=error_eur,
            error_pct=error_pct,
            direction_hit=direction_hit,
            settled_at=now_utc_str,
            record_hash=rec_hash,
        )

        # 4. Insert into settlements
        with db.transaction() as tx:
            # Check unique forecast constraint idempotently
            already_settled = tx.execute(
                "SELECT 1 FROM settlements WHERE forecast_id = ?",
                (forecast_id,),
            ).fetchone()
            if already_settled:
                continue

            tx.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    :settlement_id, :forecast_id, :isin, :settlement_date,
                    :actual_close_price, :error_eur, :error_pct, :direction_hit,
                    :settled_at, :record_hash
                )
                """,
                entry.to_db_row(),
            )

        # 5. Audit event
        try:
            AuditLogger(db).log_event(
                actor="system",
                action="SETTLEMENT_SEALED",
                entity_type="settlement",
                entity_id=settlement_id,
                payload={
                    "forecast_id": forecast_id,
                    "isin": isin,
                    "settlement_date": settlement_date_str,
                    "actual_close": str(actual_close),
                    "close_source": "17:40 Scalable fiyatı",
                    "error_eur": str(error_eur),
                    "error_pct": str(error_pct),
                    "direction_hit": direction_hit,
                    "record_hash": rec_hash,
                    "late_run": is_late_run,
                },
            )
        except Exception as exc:
            logger.warning(f"Audit log yazılamadı: {exc}")

        settled_entries.append(entry)

    return settled_entries
