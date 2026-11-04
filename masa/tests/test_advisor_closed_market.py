"""Deterministic tests for closed market (weekend / holiday) quote handling in advisor (FAZ 0.9)."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest

from masa.advisor import assess
from masa.analytics import RiskMetrics
from masa.config import load_config
from masa.pipeline import SealedPosition, SealedRun


def test_closed_market_weekend_quote_valid():
    """On Sunday with quote from Friday close, quote is valid and not marked VERİ YETERSİZ for quote age."""
    cfg = load_config()

    # Sunday 2026-11-01 12:00 UTC (Market closed)
    # Friday close was 2026-10-30 16:30 UTC
    pos = SealedPosition(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        quantity=Decimal("10"),
        broker_value=Decimal("2000"),
        broker_mid=Decimal("200"),
        fifo_price=Decimal("180"),
        bid=Decimal("199.9"),
        ask=Decimal("200.1"),
        mid=Decimal("200.0"),
        spread_pct=Decimal("0.1"),
        quote_time="2026-10-30T16:30:00+00:00",
        quote_age_seconds=156600.0,
        quality="OUTDATED",  # Broker marked outdated because market closed
    )

    run = SealedRun(
        run_id="run_test_sunday",
        completed_at="2026-11-01T12:00:00+00:00",
        hashes={},
        quality="VALID",
        positions=[pos],
        cash=Decimal("100"),
        buying_power=Decimal("100"),
    )

    dummy_metrics = {
        "IE00B3YLTY66": RiskMetrics(
            points=250,
            start="2025-10-30",
            end="2026-10-30",
            periods_per_year=252.0,
            total_return=0.15,
            cagr=0.15,
            volatility=0.12,
            sharpe=1.2,
            sortino=1.5,
            max_drawdown=0.08,
            from_high=0.02,
            above_trend=True,
            trend_gap=0.05,
        )
    }

    assessments = assess(run, cfg, dummy_metrics)
    assert len(assessments) == 1
    a = assessments[0]

    # Must NOT be VERİ YETERSİZ
    assert a.label != "VERİ YETERSİZ"
    assert a.label == "TUT"

    # Must contain closed market note
    notes_text = " ".join(a.notes)
    assert "Piyasa kapalı (XETR)" in notes_text
    assert "geçerli kabul edildi" in notes_text


def test_closed_market_truly_stale_quote_flagged():
    """On Sunday with quote from 2 weeks ago, it is flagged as VERİ YETERSİZ."""
    cfg = load_config()

    # Quote from 2 weeks prior (stale even for closed market)
    pos = SealedPosition(
        isin="IE00B3YLTY66",
        name="SPDR MSCI ACWI IMI",
        quantity=Decimal("10"),
        broker_value=Decimal("2000"),
        broker_mid=Decimal("200"),
        fifo_price=Decimal("180"),
        bid=Decimal("199.9"),
        ask=Decimal("200.1"),
        mid=Decimal("200.0"),
        spread_pct=Decimal("0.1"),
        quote_time="2026-10-15T16:30:00+00:00",
        quote_age_seconds=1450000.0,
        quality="OUTDATED",
    )

    run = SealedRun(
        run_id="run_test_stale",
        completed_at="2026-11-01T12:00:00+00:00",
        hashes={},
        quality="VALID",
        positions=[pos],
        cash=Decimal("100"),
        buying_power=Decimal("100"),
    )

    dummy_metrics = {
        "IE00B3YLTY66": RiskMetrics(
            points=250,
            start="2025-10-30",
            end="2026-10-30",
            periods_per_year=252.0,
            total_return=0.15,
            cagr=0.15,
            volatility=0.12,
            sharpe=1.2,
            sortino=1.5,
            max_drawdown=0.08,
            from_high=0.02,
            above_trend=True,
            trend_gap=0.05,
        )
    }

    assessments = assess(run, cfg, dummy_metrics)
    assert len(assessments) == 1
    a = assessments[0]
    assert a.label == "VERİ YETERSİZ"
    reasons_text = " ".join(a.reasons)
    assert "eski" in reasons_text
