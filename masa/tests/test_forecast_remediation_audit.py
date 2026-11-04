"""Comprehensive adversarial audit verification for Step 3: Forecast engine overhaul."""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import pytest

from masa.forecast.generator import generate_daily_forecasts, _compute_model_delta
from masa.forecast.models import ForecastDirection
from masa.forecast.pool import load_forecast_pool, seed_pool_instruments
from masa.forecast.settlement import settle_daily_forecasts, get_actual_close_price
from masa.forecast.metrics import calculate_performance_metrics
from masa.storage.db import DatabaseManager


def test_confidence_suppressed_when_under_30_observations(tmp_path: Path):
    """Confidence must be suppressed (<30) when fewer than 30 settled observations exist."""
    db = DatabaseManager(tmp_path / "fc_test.db")
    db.initialize_schema()
    seed_pool_instruments(db)

    # Mock quotes
    pool = load_forecast_pool()
    mock_quotes = {inst.isin: Decimal("50.00") for inst in pool.all_instruments()}

    # 2026-11-02 is a Monday (trading day)
    forecasts = generate_daily_forecasts(db, target_date="2026-11-02", dry_run=False, quotes_override=mock_quotes)
    assert len(forecasts) == 10
    for f in forecasts:
        # Confidence must be suppressed (displayed as "—", not "%0.00")
        assert f.confidence_pct == Decimal("0.00")
        assert f.display_confidence == "—"


def test_confidence_computed_from_empirical_hit_rate_when_ge_30(tmp_path: Path):
    """When N >= 30, confidence must equal historical empirical hit rate."""
    db = DatabaseManager(tmp_path / "fc_test.db")
    db.initialize_schema()
    seed_pool_instruments(db)

    # Insert 30 historical settlements into DB for model_momentum_v1 (21 hits = 70% hit rate)
    with db.transaction() as tx:
        for i in range(30):
            fc_id = f"fc_hist_{i}"
            hit = 1 if i < 21 else 0
            tx.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, 'IE00B3YLTY66', '2026-10-01', 'DAILY_CLOSE', 'UP',
                    '10.00', '10.50', '0.00', 'model_momentum_v1',
                    '2026-10-01T09:30:00Z', ?
                )
                """,
                (fc_id, f"hash_fc_{i}"),
            )
            tx.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    ?, ?, 'IE00B3YLTY66', '2026-10-01',
                    '10.40', '0.10', '1.00', ?,
                    '2026-10-01T17:40:00Z', ?
                )
                """,
                (f"set_hist_{i}", fc_id, hit, f"hash_set_{i}"),
            )

    pool = load_forecast_pool()
    mock_quotes = {inst.isin: Decimal("50.00") for inst in pool.all_instruments()}

    forecasts = generate_daily_forecasts(db, target_date="2026-11-02", dry_run=False, quotes_override=mock_quotes)
    assert len(forecasts) == 10
    for f in forecasts:
        # Confidence must now be 70.00%
        assert f.confidence_pct == Decimal("70.00")
        assert "%70.0" in f.display_confidence


def test_scorecard_benchmarks_against_baselines_and_warns(tmp_path: Path):
    """Karne must calculate Martingale (flat) and Momentum Persist (yesterday's direction) and warn if model <= baselines."""
    db = DatabaseManager(tmp_path / "fc_test.db")
    db.initialize_schema()
    seed_pool_instruments(db)

    # Insert historical data where market was FLAT most of the time (Martingale hit rate = 80%),
    # but model only got 50% hit rate
    with db.transaction() as tx:
        for i in range(10):
            fc_id = f"fc_bench_{i}"
            # Model guessed UP, but market was FLAT
            hit = 1 if i < 4 else 0
            act_close = "10.00" if i < 8 else "10.50"
            tx.execute(
                """
                INSERT INTO forecast_entries (
                    forecast_id, isin, target_date, forecast_type, direction,
                    reference_price, target_price, confidence_pct, model_id,
                    created_at, record_hash
                ) VALUES (
                    ?, 'IE00B3YLTY66', ?, 'DAILY_CLOSE', 'UP',
                    '10.00', '10.50', '0.00', 'model_momentum_v1',
                    '2026-10-01T09:30:00Z', ?
                )
                """,
                (fc_id, f"2026-10-{i+1:02d}", f"hash_fc_{i}"),
            )
            tx.execute(
                """
                INSERT INTO settlements (
                    settlement_id, forecast_id, isin, settlement_date,
                    actual_close_price, error_eur, error_pct, direction_hit,
                    settled_at, record_hash
                ) VALUES (
                    ?, ?, 'IE00B3YLTY66', ?,
                    ?, '0.10', '1.00', ?,
                    '2026-10-01T17:40:00Z', ?
                )
                """,
                (f"set_bench_{i}", fc_id, f"2026-10-{i+1:02d}", act_close, hit, f"hash_set_{i}"),
            )

    metrics = calculate_performance_metrics(db=db, model_id="model_momentum_v1")
    assert metrics.settled_count == 10
    assert metrics.hit_rate_pct == Decimal("40.00")
    assert metrics.baseline_flat_hit_rate_pct == Decimal("80.00")
    assert metrics.beats_baselines is False
    assert "⚠️ DİKKAT: Model baz modellerden" in metrics.baseline_warning
    assert "Değişmez" in metrics.baseline_warning


def test_quote_timestamp_gate_rejects_pre_close_quote(tmp_path: Path):
    """Settlement must reject quotes timestamped before 17:30 CET."""
    db = DatabaseManager(tmp_path / "fc_test.db")
    db.initialize_schema()

    # Insert a quote with timestamp at 14:00 CET (13:00 UTC)
    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO snapshots (
                snapshot_id, run_id, snapshot_type, collection_started_at,
                collection_completed_at, source, item_count, quality_status,
                connector_version, prev_hash, curr_hash, created_at
            ) VALUES (
                'snap_early', 'run_early', 'quotes', '2026-11-02T13:00:00Z',
                '2026-11-02T13:01:00Z', 'test', 1, 'VALID',
                '1.0', '0'*64, 'hash_early', '2026-11-02T13:01:00Z'
            )
            """
        )
        tx.execute(
            """
            INSERT INTO quotes (
                snapshot_id, isin, currency, bid, ask, computed_mid,
                spread, spread_pct, quote_timestamp, retrieved_at,
                source, quality_status, record_hash
            ) VALUES (
                'snap_early', 'IE00B3YLTY66', 'EUR', '10.00', '10.02', '10.01',
                '0.02', '0.002', '2026-11-02T13:00:00Z', '2026-11-02T13:00:00Z',
                'test', 'VALID', 'hash_q_early'
            )
            """
        )

    # Attempt to retrieve closing price for 2026-11-02: MUST RETURN None (rejected pre-close)
    price = get_actual_close_price(db, "IE00B3YLTY66", settlement_date_str="2026-11-02")
    assert price is None


def test_holiday_skips_forecast_generation(tmp_path: Path):
    """Weekend or XETR holiday must return empty list (skips generation)."""
    db = DatabaseManager(tmp_path / "fc_test.db")
    db.initialize_schema()

    # 2026-12-25 is Christmas (exchange closed)
    forecasts = generate_daily_forecasts(db, target_date="2026-12-25", dry_run=False)
    assert forecasts == []


def test_model_delta_uses_single_timeframe_without_mixing(tmp_path: Path):
    """Model delta must isolate series_key to a single timeframe and never mix 1y/max/1m."""
    from masa.forecast.generator import _compute_model_delta
    from masa.forecast.models import PoolInstrument

    db = DatabaseManager(tmp_path / "fc_tf_test.db")
    db.initialize_schema()

    inst = PoolInstrument(
        isin="IE00B3YLTY66",
        ad="SPDR ACWI",
        sembol="SPYI",
        yahoo="SPYI.DE",
        rol="core",
        mic="XETR",
        para_birimi="EUR",
        asset_type="ETF",
    )

    from masa.storage.snapshot_store import SnapshotStore
    store = SnapshotStore(db)
    rid, _ = store.store_raw_object("sc.broker.chart", "{}", datetime(2026, 11, 2, 9, 29, tzinfo=timezone.utc))

    with db.transaction() as tx:
        # Seed snapshots
        tx.execute(
            """
            INSERT INTO snapshots (snapshot_id, run_id, snapshot_type, collection_started_at, collection_completed_at, source, item_count, quality_status, connector_version, prev_hash, curr_hash, created_at)
            VALUES ('snap_s1', 'run_1', 'series', '2026-11-02T09:29:00Z', '2026-11-02T09:30:00Z', 'test', 2, 'VALID', '1.0', '0'*64, 'hash_s1', '2026-11-02T09:30:00Z')
            """
        )
        # Seed 1m points (increasing slope: 10.00 -> 10.10 -> +1.00% delta / 2 = +0.0050)
        tx.execute(
            """
            INSERT INTO series_points (snapshot_id, raw_object_id, series_key, series_kind, point_time, value, record_hash)
            VALUES ('snap_s1', ?, 'IE00B3YLTY66:1m', 'mid_price', '2026-11-02T09:29:00Z', 10.00, 'h_1m_0'),
                   ('snap_s1', ?, 'IE00B3YLTY66:1m', 'mid_price', '2026-11-02T09:30:00Z', 10.10, 'h_1m_1')
            """,
            (rid, rid),
        )
        # Seed 1y points with conflicting reverse direction (90.00 -> 20.00)
        tx.execute(
            """
            INSERT INTO series_points (snapshot_id, raw_object_id, series_key, series_kind, point_time, value, record_hash)
            VALUES ('snap_s1', ?, 'IE00B3YLTY66:1y', 'mid_price', '2026-01-01T00:00:00Z', 90.00, 'h_1y_0'),
                   ('snap_s1', ?, 'IE00B3YLTY66:1y', 'mid_price', '2026-10-30T00:00:00Z', 20.00, 'h_1y_1')
            """,
            (rid, rid),
        )

    # Compute delta: must use 1m only (+0.0050), never contaminated by 1y
    delta = _compute_model_delta(db, inst, target_date_str="2026-11-02")
    assert delta == Decimal("0.0050")


def test_collect_snapshot_extra_isins_and_collect_history_isolation(tmp_path: Path):
    """Pipeline.collect_snapshot extra_isins quotes pool, and collect_history includes only requested timeframes."""
    from masa.pipeline import Pipeline
    from masa.ingestion.sc_reader import ScalableReader
    from masa.ingestion.models import QuoteData, RawBrokerPayload, PositionsResult, CashBreakdownResult, ChartSeries, ChartPoint
    from unittest.mock import MagicMock

    db = DatabaseManager(tmp_path / "pipe_test.db")
    db.initialize_schema()

    mock_reader = MagicMock(spec=ScalableReader)
    mock_reader.get_whoami.return_value = RawBrokerPayload(command="whoami", args=[], user="user", stdout_raw="{}", stderr_raw="", exit_code=0, payload_sha256="hash_who", retrieved_at=datetime.now(timezone.utc), parsed_json={})
    mock_reader.get_positions.return_value = PositionsResult(account_id="acc123", portfolio_id="port123", items=[], total_value=Decimal("0"), count=0, retrieved_at=datetime.now(timezone.utc))
    mock_reader.get_cash.return_value = CashBreakdownResult(
        account_id="acc123",
        portfolio_id="port123",
        cash_balance=Decimal("1000"),
        buying_power=Decimal("1000"),
        buying_power_without_credit=Decimal("1000"),
        available_credit_line=Decimal("0"),
        derivatives_buying_power=Decimal("0"),
        pending_buy_orders_amount=Decimal("0"),
        possible_taxes=Decimal("0"),
        retrieved_at=datetime.now(timezone.utc),
    )
    mock_reader.last_raw = RawBrokerPayload(command="cmd", args=[], user="user", stdout_raw="{}", stderr_raw="", exit_code=0, payload_sha256="hash_raw", retrieved_at=datetime.now(timezone.utc), parsed_json={})

    def mock_get_quote(isin):
        return QuoteData(
            isin=isin,
            name=f"Name {isin}",
            security_type="ETF",
            currency="EUR",
            bid=Decimal("10.00"),
            ask=Decimal("10.02"),
            mid=Decimal("10.01"),
            computed_mid=Decimal("10.01"),
            spread=Decimal("0.02"),
            spread_pct=Decimal("0.002"),
            timestamp_utc=datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc),
            is_outdated=False,
        )
    mock_reader.get_quote.side_effect = mock_get_quote

    def mock_get_chart(isin, tf):
        return ChartSeries(
            isin=isin,
            currency="EUR",
            timeframe=tf,
            source="test",
            points=[
                ChartPoint(timestamp_utc=datetime(2026, 11, 2, 9, 28, tzinfo=timezone.utc), mid_price=Decimal("10.00")),
                ChartPoint(timestamp_utc=datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc), mid_price=Decimal("10.05")),
            ],
            retrieved_at=datetime.now(timezone.utc),
        )
    mock_reader.get_chart.side_effect = mock_get_chart

    pipe = Pipeline(db=db, reader=mock_reader)

    # 1. Snapshot with extra_isins
    res = pipe.collect_snapshot(extra_isins=["IE00B3YLTY66", "US0378331005"])
    assert res.ok is True

    # Verify quotes stored in DB
    conn = db.get_connection()
    q_count = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    conn.close()
    assert q_count == 2

    # 2. History with timeframes 1m/3m and include_transactions=False
    hist_res = pipe.collect_history(isins=["IE00B3YLTY66"], timeframes=("1m", "3m"), include_transactions=False)
    assert "IE00B3YLTY66:1m" in hist_res["series"]
    assert "IE00B3YLTY66:3m" in hist_res["series"]
    assert "transactions" not in hist_res  # Transactions skipped
    mock_reader.get_all_transactions.assert_not_called()


def test_cli_holiday_weekend_message_skips_generation(monkeypatch, capsys, tmp_path: Path):
    """XETR holiday or weekend must print exact message and return exit code 0."""
    from masa.cli import main

    monkeypatch.setenv("MASA_DB_PATH", str(tmp_path / "fc_holiday.db"))

    # Holiday (Christmas 2026-12-25)
    with pytest.raises(SystemExit) as exc:
        main(["tahmin", "uret", "--tarih", "2026-12-25"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Bugün Xetra seansı yok, tahmin üretilmedi" in out

    # Weekend (Saturday 2026-10-31)
    with pytest.raises(SystemExit) as exc:
        main(["tahmin", "uret", "--tarih", "2026-10-31"])
    assert exc.value.code == 0
    out2 = capsys.readouterr().out
    assert "Bugün Xetra seansı yok, tahmin üretilmedi" in out2


def test_cli_data_collection_auth_error_sets_waiting_auth_and_aborts(monkeypatch, capsys, tmp_path: Path):
    """Broker session expiration must transition job to waiting_auth, send alert, and halt with exit 1."""
    from unittest.mock import MagicMock
    from masa.cli import main
    from masa.pipeline import Pipeline
    from masa.audit.queue import JobQueue, JobState
    from masa.calendar.adapter import CalendarAdapter
    import masa.notify

    db_path = tmp_path / "fc_auth_err.db"
    monkeypatch.setenv("MASA_DB_PATH", str(db_path))

    db = DatabaseManager(db_path)
    db.initialize_schema()

    # Emulate active market session
    monkeypatch.setattr(CalendarAdapter, "is_market_session", lambda self, d: True)

    # Mock Pipeline.collect_snapshot raising session expiration error
    def failing_snapshot(self, *args, **kwargs):
        raise RuntimeError("Scalable oturum süresi dolmuş, lütfen yeniden giriş yapın: Session expired 401.")

    monkeypatch.setattr(Pipeline, "collect_snapshot", failing_snapshot)

    alert_mock = MagicMock(return_value=True)
    monkeypatch.setattr(masa.notify, "notify_system_alert", alert_mock)

    with pytest.raises(SystemExit) as exc:
        main(["tahmin", "uret"])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    assert "Scalable Capital oturumu sonlanmış" in out
    assert "waiting_auth" in out
    assert "masa giris" in out
    assert alert_mock.called

    # Check job queue recorded waiting_auth
    jq = JobQueue(db)
    pending = jq.get_pending_or_waiting_jobs()
    assert any(j.status == JobState.WAITING_AUTH for j in pending)

    # Zero forecasts produced
    conn = db.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM forecast_entries").fetchone()[0]
    conn.close()
    assert count == 0


def test_cli_data_collection_error_halts_without_silent_generation(monkeypatch, capsys, tmp_path: Path):
    """Generic data collection failure must halt execution (exit != 0) and not produce forecasts."""
    from masa.cli import main
    from masa.pipeline import Pipeline
    from masa.calendar.adapter import CalendarAdapter

    db_path = tmp_path / "fc_generic_err.db"
    monkeypatch.setenv("MASA_DB_PATH", str(db_path))

    db = DatabaseManager(db_path)
    db.initialize_schema()

    monkeypatch.setattr(CalendarAdapter, "is_market_session", lambda self, d: True)

    def failing_snapshot(self, *args, **kwargs):
        raise RuntimeError("Connection reset by peer: Broker unreachable")

    monkeypatch.setattr(Pipeline, "collect_snapshot", failing_snapshot)

    with pytest.raises(SystemExit) as exc:
        main(["tahmin", "uret"])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    assert "Veri toplama hatası" in out
    assert "İşlem durduruldu" in out

    # Zero forecasts produced
    conn = db.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM forecast_entries").fetchone()[0]
    conn.close()
    assert count == 0


def test_cli_e2e_real_unmocked_collect_result_persists_1m_3m_series(monkeypatch, capsys, tmp_path: Path):
    """CLI tahmin uret end-to-end with unmocked CollectResult verifies :1m and :3m series are persisted."""
    import hashlib
    from decimal import Decimal
    from masa.cli import main
    from masa.calendar.adapter import CalendarAdapter
    from masa.forecast.pool import load_forecast_pool
    from masa.ingestion.sc_reader import ScalableReader
    from masa.ingestion.models import QuoteData, RawBrokerPayload, PositionsResult, CashBreakdownResult, ChartSeries, ChartPoint

    db_path = tmp_path / "fc_e2e_series.db"
    monkeypatch.setenv("MASA_DB_PATH", str(db_path))

    db = DatabaseManager(db_path)
    db.initialize_schema()

    # Market is open
    monkeypatch.setattr(CalendarAdapter, "is_market_session", lambda self, d: True)

    # Provide mock ScalableReader that feeds realistic broker data into real Pipeline
    pool = load_forecast_pool()
    pool_isins = {inst.isin: inst for inst in pool.all_instruments()}

    now_utc = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
    raw_dummy = RawBrokerPayload(command="cmd", args=[], user="user", stdout_raw='{"ok": true}', stderr_raw="", exit_code=0, payload_sha256="h_raw", retrieved_at=now_utc, parsed_json={"ok": True})

    def fake_get_whoami(self):
        self.last_raw = raw_dummy
        return raw_dummy

    def fake_get_positions(self):
        self.last_raw = raw_dummy
        return PositionsResult(account_id="acc123", portfolio_id="port123", items=[], total_value=Decimal("0"), count=0, retrieved_at=now_utc)

    def fake_get_cash(self):
        self.last_raw = raw_dummy
        return CashBreakdownResult(
            account_id="acc123",
            portfolio_id="port123",
            cash_balance=Decimal("5000"),
            buying_power=Decimal("5000"),
            buying_power_without_credit=Decimal("5000"),
            available_credit_line=Decimal("0"),
            derivatives_buying_power=Decimal("0"),
            pending_buy_orders_amount=Decimal("0"),
            possible_taxes=Decimal("0"),
            retrieved_at=now_utc,
        )

    def fake_get_quote(self, isin):
        q_raw_str = f'{{"ok": true, "isin": "{isin}", "mid": 50.00}}'
        q_sha = hashlib.sha256(q_raw_str.encode()).hexdigest()
        self.last_raw = RawBrokerPayload(command="quote", args=["--isin", isin], user="user", stdout_raw=q_raw_str, stderr_raw="", exit_code=0, payload_sha256=q_sha, retrieved_at=now_utc, parsed_json={"ok": True})
        inst = pool_isins.get(isin)
        name = inst.ad if inst else f"Instrument {isin}"
        return QuoteData(
            isin=isin,
            name=name,
            security_type="ETF",
            currency="EUR",
            bid=Decimal("49.98"),
            ask=Decimal("50.02"),
            mid=Decimal("50.00"),
            computed_mid=Decimal("50.00"),
            spread=Decimal("0.04"),
            spread_pct=Decimal("0.0008"),
            timestamp_utc=now_utc,
            is_outdated=False,
        )

    def fake_get_chart(self, isin, timeframe="1y"):
        c_raw_str = f'{{"ok": true, "isin": "{isin}", "timeframe": "{timeframe}", "points": [49.50, 50.00]}}'
        c_sha = hashlib.sha256(c_raw_str.encode()).hexdigest()
        self.last_raw = RawBrokerPayload(command="chart", args=["--isin", isin, "--timeframe", timeframe], user="user", stdout_raw=c_raw_str, stderr_raw="", exit_code=0, payload_sha256=c_sha, retrieved_at=now_utc, parsed_json={"ok": True})
        pts = [
            ChartPoint(timestamp_utc=datetime(2026, 11, 2, 9, 20, tzinfo=timezone.utc), mid_price=Decimal("49.50")),
            ChartPoint(timestamp_utc=datetime(2026, 11, 2, 9, 29, tzinfo=timezone.utc), mid_price=Decimal("50.00")),
        ]
        return ChartSeries(isin=isin, currency="EUR", timeframe=timeframe, source="test", points=pts, retrieved_at=now_utc)

    monkeypatch.setattr(ScalableReader, "get_whoami", fake_get_whoami)
    monkeypatch.setattr(ScalableReader, "get_positions", fake_get_positions)
    monkeypatch.setattr(ScalableReader, "get_cash", fake_get_cash)
    monkeypatch.setattr(ScalableReader, "get_quote", fake_get_quote)
    monkeypatch.setattr(ScalableReader, "get_chart", fake_get_chart)

    # Execute CLI command end-to-end
    with pytest.raises(SystemExit) as exc:
        main(["tahmin", "uret"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "Mühürlü kotasyonlar toplandı (10 kotasyon" in out
    assert "1m/3m serileri mühürlendi" in out
    assert "10 tahmin başarıyla oluşturuldu ve mühürlendi" in out

    # Database assertions: verify genuine CollectResult output in series_points and forecast_entries
    conn = db.get_connection()
    try:
        # Check :1m and :3m keys
        c_1m = conn.execute("SELECT COUNT(*) FROM series_points WHERE series_key LIKE '%:1m'").fetchone()[0]
        c_3m = conn.execute("SELECT COUNT(*) FROM series_points WHERE series_key LIKE '%:3m'").fetchone()[0]
        assert c_1m >= 10, f"Expected at least 10 1m series points, found {c_1m}"
        assert c_3m >= 10, f"Expected at least 10 3m series points, found {c_3m}"

        # Check distinct ISINs in series_points
        distinct_1m_isins = conn.execute("SELECT DISTINCT series_key FROM series_points WHERE series_key LIKE '%:1m'").fetchall()
        assert len(distinct_1m_isins) == 10

        # Check forecasts
        fc_rows = conn.execute("SELECT isin, reference_price, target_price, direction, confidence_pct FROM forecast_entries").fetchall()
        assert len(fc_rows) == 10
        for r in fc_rows:
            assert Decimal(str(r["reference_price"])) == Decimal("50.00")
            assert r["direction"] in ("UP", "DOWN", "FLAT")
            # Confidence suppressed since N < 30
            assert Decimal(str(r["confidence_pct"])) == Decimal("0.00")
    finally:
        conn.close()
