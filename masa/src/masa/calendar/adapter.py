"""Exchange calendar adapter with zero-assumption fallback."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional, Union
import exchange_calendars as xcals
import pandas as pd

from masa.calendar.models import MarketSessionState, QuoteAgeAssessment


class CalendarAdapter:
    """Thread-safe adapter wrapping exchange-calendars with strict validation."""

    SUPPORTED_MIC = "XETR"

    def __init__(self, venue_mic: str = SUPPORTED_MIC, default_exchange: Optional[str] = None) -> None:
        selected = default_exchange or venue_mic or self.SUPPORTED_MIC
        self._venue_mic = selected.upper()
        self._calendar = xcals.get_calendar(self._venue_mic)
        self._version = getattr(xcals, "__version__", "unknown")

    @property
    def venue_mic(self) -> str:
        return self._venue_mic

    @property
    def calendar_version(self) -> str:
        return self._version

    def is_market_session(self, dt_or_str: Union[str, datetime, date]) -> bool:
        """Check if XETR has an active trading session on the given date (excludes weekends and holidays)."""
        if isinstance(dt_or_str, (datetime, date)):
            d_str = dt_or_str.strftime("%Y-%m-%d")
        else:
            d_str = str(dt_or_str).strip()[:10]
        try:
            return bool(self._calendar.is_session(d_str))
        except Exception:
            return False

    def is_market_open(self, dt: datetime) -> bool:
        """Check if XETR is open for regular trading at the given UTC datetime."""
        if dt.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (preferably UTC)")
        utc_dt = dt.astimezone(timezone.utc)
        return bool(self._calendar.is_trading_minute(pd.Timestamp(utc_dt)))

    def assess_quote_freshness(
        self,
        quote_time: datetime,
        snapshot_time: datetime,
        venue_mic: Optional[str] = None,
        max_open_age_seconds: float = 900.0,
        max_unverified_age_seconds: float = 86400.0 * 7,
    ) -> QuoteAgeAssessment:
        """Evaluate quote freshness without ever assuming exchange calendar for unknown sources.

        Args:
            quote_time: Timestamp from the quote provider (must be timezone-aware).
            snapshot_time: Timestamp of observation/ingestion (must be timezone-aware).
            venue_mic: Exchange MIC (e.g. 'XETR'). If None, empty, 'UNKNOWN', or 'CONSOLIDATED',
                       no calendar assumptions are made.
            max_open_age_seconds: Freshness threshold in seconds when market is OPEN (default 15m).
            max_unverified_age_seconds: Maximum tolerable age for unverified/unknown sources (default 7 days).

        Returns:
            QuoteAgeAssessment: Detailed audit object.

        Raises:
            ValueError: If quote_time > snapshot_time (future quote rejected).
            ValueError: If either timestamp is timezone-naive.
        """
        # Strict timezone-awareness check
        if quote_time.tzinfo is None or snapshot_time.tzinfo is None:
            raise ValueError("Both quote_time and snapshot_time must be timezone-aware")

        q_utc = quote_time.astimezone(timezone.utc)
        s_utc = snapshot_time.astimezone(timezone.utc)

        # Enforce temporal causality: reject future quotes
        if q_utc > s_utc:
            raise ValueError(
                f"Future quote rejected: quote_time ({q_utc.isoformat()}) "
                f"is ahead of snapshot_time ({s_utc.isoformat()}). "
                "Kotasyon zamani gozlem zamanindan ileride olamaz."
            )

        age_seconds = (s_utc - q_utc).total_seconds()

        # Zero-Assumption Rule: Never assume XETR if venue is unknown, consolidated, or None
        clean_mic = venue_mic.strip().upper() if (venue_mic and isinstance(venue_mic, str)) else None
        if clean_mic in (None, "", "UNKNOWN", "CONSOLIDATED"):
            return QuoteAgeAssessment(
                quote_time=q_utc,
                snapshot_time=s_utc,
                age_seconds=age_seconds,
                session_state=MarketSessionState.UNKNOWN,
                venue_mic=None,
                is_stale=age_seconds > max_unverified_age_seconds,
                calendar_name=None,
                calendar_version=self._version,
                diagnostic_note=(
                    "Quote venue is unknown or consolidated; XETR calendar NOT assumed. "
                    f"Absolute age is {age_seconds:.1f}s."
                ),
            )

        # If venue is explicitly specified but not supported by this adapter
        if clean_mic != self._venue_mic:
            return QuoteAgeAssessment(
                quote_time=q_utc,
                snapshot_time=s_utc,
                age_seconds=age_seconds,
                session_state=MarketSessionState.UNKNOWN,
                venue_mic=clean_mic,
                is_stale=age_seconds > max_unverified_age_seconds,
                calendar_name=None,
                calendar_version=self._version,
                diagnostic_note=(
                    f"Venue '{clean_mic}' is not supported by {self._venue_mic} adapter; "
                    "session state left UNKNOWN."
                ),
            )

        # Venue is verified XETR
        s_ts = pd.Timestamp(s_utc)
        is_open = bool(self._calendar.is_trading_minute(s_ts))

        if is_open:
            is_stale = age_seconds > max_open_age_seconds
            note = (
                f"Market {self._venue_mic} is OPEN at snapshot time. "
                f"Quote age is {age_seconds:.1f}s (threshold: {max_open_age_seconds}s). "
                f"Freshness status: {'STALE' if is_stale else 'FRESH'}."
            )
            return QuoteAgeAssessment(
                quote_time=q_utc,
                snapshot_time=s_utc,
                age_seconds=age_seconds,
                session_state=MarketSessionState.OPEN,
                venue_mic=clean_mic,
                is_stale=is_stale,
                calendar_name=self._venue_mic,
                calendar_version=self._version,
                diagnostic_note=note,
            )
        else:
            # Market is closed (weekend, holiday, or off-hours)
            prev_close_ts = self._calendar.previous_close(s_ts)
            prev_close_utc = prev_close_ts.to_pydatetime().astimezone(timezone.utc)

            # A quote generated for or at the last session close (with 30m auction margin) is valid
            is_from_last_session = q_utc >= (prev_close_utc - timedelta(minutes=30))
            is_stale = not is_from_last_session

            note = (
                f"Market {self._venue_mic} is CLOSED at snapshot time. "
                f"Most recent session close was {prev_close_utc.isoformat()}. "
                f"Quote is from {'most recent session close (VALID)' if is_from_last_session else 'an earlier expired session (STALE)'}."
            )
            return QuoteAgeAssessment(
                quote_time=q_utc,
                snapshot_time=s_utc,
                age_seconds=age_seconds,
                session_state=MarketSessionState.CLOSED,
                venue_mic=clean_mic,
                is_stale=is_stale,
                calendar_name=self._venue_mic,
                calendar_version=self._version,
                diagnostic_note=note,
            )

    def evaluate_freshness(
        self,
        quote_timestamp: datetime,
        retrieved_at: datetime,
        exchange: Optional[str] = None,
        stale_threshold_seconds: float = 900.0,
    ) -> QuoteAgeAssessment:
        """Compatibility wrapper for evaluate_freshness."""
        return self.assess_quote_freshness(
            quote_time=quote_timestamp,
            snapshot_time=retrieved_at,
            venue_mic=exchange,
            max_open_age_seconds=stale_threshold_seconds,
        )


# Compatibility alias
TradingCalendarAdapter = CalendarAdapter
