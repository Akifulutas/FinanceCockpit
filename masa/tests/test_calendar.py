"""Tests for trading calendar adapter, zero-assumption policy, and quote freshness."""

from datetime import datetime, timezone, timedelta
import pytest

from masa.calendar import CalendarAdapter, MarketSessionState, TradingCalendarAdapter


class TestCalendarAdapter:
    """Verify exchange-calendars adapter rules and zero-assumption fallback."""

    def test_unknown_exchange_never_assumes_xetr(self) -> None:
        adapter = CalendarAdapter()

        quote_time = datetime(2026, 10, 30, 9, 30, 0, tzinfo=timezone.utc)
        snapshot_time = datetime(2026, 10, 30, 9, 31, 0, tzinfo=timezone.utc)

        for unverified_venue in [None, "", "UNKNOWN", "CONSOLIDATED", "consolidated"]:
            res = adapter.assess_quote_freshness(
                quote_time=quote_time,
                snapshot_time=snapshot_time,
                venue_mic=unverified_venue,
            )

            assert res.session_state == MarketSessionState.UNKNOWN
            assert res.session_status == "UNKNOWN"
            assert res.venue_mic is None
            assert res.exchange_used is None
            assert res.age_seconds == 60.0
            assert res.is_stale is False
            assert "XETR calendar NOT assumed" in res.diagnostic_note

    def test_future_quote_rejected_with_value_error(self) -> None:
        adapter = CalendarAdapter()

        quote_time = datetime(2026, 10, 30, 10, 10, 0, tzinfo=timezone.utc)
        snapshot_time = datetime(2026, 10, 30, 10, 5, 0, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="Future quote rejected|ileride"):
            adapter.assess_quote_freshness(quote_time=quote_time, snapshot_time=snapshot_time)

    def test_naive_timestamp_rejected_with_value_error(self) -> None:
        adapter = CalendarAdapter()

        naive_time = datetime(2026, 10, 30, 10, 0, 0)
        aware_time = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.assess_quote_freshness(quote_time=naive_time, snapshot_time=aware_time)

        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.assess_quote_freshness(quote_time=aware_time, snapshot_time=naive_time)

        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.is_market_open(naive_time)

    def test_verified_xetr_open_session_freshness(self) -> None:
        adapter = CalendarAdapter(venue_mic="XETR")

        # Friday 2026-10-30 at 10:00 UTC is during regular Xetra trading hours (08:00 - 16:30 CET / 09:00 - 17:30 CEST)
        # Note: In late October, Berlin is either UTC+1 or UTC+2; 10:00 UTC is midday in Frankfurt
        snapshot_time = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
        is_open = adapter.is_market_open(snapshot_time)
        assert is_open is True

        # Fresh quote: 2 minutes old (threshold default is 15m)
        quote_time_fresh = snapshot_time - timedelta(minutes=2)
        res_fresh = adapter.assess_quote_freshness(
            quote_time=quote_time_fresh,
            snapshot_time=snapshot_time,
            venue_mic="XETR",
        )
        assert res_fresh.session_state == MarketSessionState.OPEN
        assert res_fresh.venue_mic == "XETR"
        assert res_fresh.is_stale is False
        assert res_fresh.age_seconds == 120.0

        # Stale quote: 20 minutes old (threshold default is 15m)
        quote_time_stale = snapshot_time - timedelta(minutes=20)
        res_stale = adapter.assess_quote_freshness(
            quote_time=quote_time_stale,
            snapshot_time=snapshot_time,
            venue_mic="XETR",
        )
        assert res_stale.session_state == MarketSessionState.OPEN
        assert res_stale.is_stale is True
        assert res_stale.age_seconds == 1200.0

    def test_verified_xetr_closed_session_last_close_valid(self) -> None:
        adapter = CalendarAdapter(venue_mic="XETR")

        # Sunday 2026-11-01 at 12:00 UTC: market is strictly closed
        snapshot_time = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert adapter.is_market_open(snapshot_time) is False

        # Previous regular session close was Friday 2026-10-30 at session close
        # A quote matching Friday's close is valid
        # Let's inspect previous_close from calendar directly
        import pandas as pd
        prev_close_ts = adapter._calendar.previous_close(pd.Timestamp(snapshot_time))
        prev_close_dt = prev_close_ts.to_pydatetime().astimezone(timezone.utc)

        # Quote at previous close is fresh / valid
        res_valid = adapter.assess_quote_freshness(
            quote_time=prev_close_dt,
            snapshot_time=snapshot_time,
            venue_mic="XETR",
        )
        assert res_valid.session_state == MarketSessionState.CLOSED
        assert res_valid.is_stale is False

        # Quote from 2 weeks earlier is stale
        quote_expired = prev_close_dt - timedelta(days=14)
        res_expired = adapter.assess_quote_freshness(
            quote_time=quote_expired,
            snapshot_time=snapshot_time,
            venue_mic="XETR",
        )
        assert res_expired.session_state == MarketSessionState.CLOSED
        assert res_expired.is_stale is True

    def test_evaluate_freshness_compatibility_wrapper(self) -> None:
        adapter = TradingCalendarAdapter(default_exchange="XETR")

        quote_time = datetime(2026, 10, 30, 9, 30, 0, tzinfo=timezone.utc)
        retrieved_at = datetime(2026, 10, 30, 9, 31, 0, tzinfo=timezone.utc)

        res = adapter.evaluate_freshness(
            quote_timestamp=quote_time,
            retrieved_at=retrieved_at,
            exchange=None,
        )

        assert res.session_status == "UNKNOWN"
        assert res.exchange_used is None
        assert res.age_seconds == 60.0
        assert res.is_stale is False
