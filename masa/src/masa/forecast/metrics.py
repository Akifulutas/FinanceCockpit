"""Forecast scorecard and performance metrics calculation (IP-5).

Calculates:
- Hit Rate (%) = (Sum of direction_hit / N) * 100
- MAPE (%) = (1 / N) * Sum(|error_pct|)
- MAE (EUR) = (1 / N) * Sum(|error_eur|)
- MPE (%) = (1 / N) * Sum(error_pct)  [Systemic bias]
- Breakdown for ETFs vs Stocks
- Small sample warning barrier (N < 30)
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any, List, Optional

from masa.forecast.models import ForecastPerformanceMetrics
from masa.forecast.pool import load_forecast_pool
from masa.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


def calculate_performance_metrics(
    db: DatabaseManager,
    isin: Optional[str] = None,
    model_id: Optional[str] = None,
) -> ForecastPerformanceMetrics:
    """Calculate scorecard metrics from v_forecast_performance and v_forecasts_unsettled."""
    pool = load_forecast_pool()
    etf_isins = set(pool.etf.keys())
    stock_isins = set(pool.hisse.keys())

    conn = db.get_connection()
    try:
        # 1. Fetch settled records
        query_settled = "SELECT * FROM v_forecast_performance WHERE 1=1"
        params_settled: List[Any] = []
        if isin:
            query_settled += " AND isin = ?"
            params_settled.append(isin.upper())
        if model_id:
            query_settled += " AND model_id = ?"
            params_settled.append(model_id)

        settled_rows = conn.execute(query_settled, tuple(params_settled)).fetchall()

        # 2. Fetch unsettled count
        query_unsettled = "SELECT COUNT(*) FROM v_forecasts_unsettled WHERE 1=1"
        params_unsettled: List[Any] = []
        if isin:
            query_unsettled += " AND isin = ?"
            params_unsettled.append(isin.upper())
        if model_id:
            query_unsettled += " AND model_id = ?"
            params_unsettled.append(model_id)

        pending_count = conn.execute(query_unsettled, tuple(params_unsettled)).fetchone()[0]
    finally:
        conn.close()

    settled_count = len(settled_rows)
    total_forecasts = settled_count + pending_count

    if settled_count == 0:
        return ForecastPerformanceMetrics(
            total_forecasts=total_forecasts,
            settled_count=0,
            pending_count=pending_count,
            hit_rate_pct=Decimal("0.00"),
            etf_hit_rate_pct=None,
            stock_hit_rate_pct=None,
            mape_pct=Decimal("0.00"),
            mae_eur=Decimal("0.0000"),
            mpe_pct=Decimal("0.00"),
            is_small_sample=True,
            warning_message="Henüz uzlaşmış tahmin bulunmuyor.",
        )

    n_dec = Decimal(str(settled_count))

    # Overall Hit Rate
    hits = sum(r["direction_hit"] for r in settled_rows)
    hit_rate_pct = ((Decimal(str(hits)) / n_dec) * Decimal("100")).quantize(Decimal("0.01"))

    # Errors
    total_abs_pct = sum(abs(Decimal(str(r["error_pct"]))) for r in settled_rows)
    mape_pct = (total_abs_pct / n_dec).quantize(Decimal("0.01"))

    total_abs_eur = sum(abs(Decimal(str(r["error_eur"]))) for r in settled_rows)
    mae_eur = (total_abs_eur / n_dec).quantize(Decimal("0.0001"))

    total_mpe = sum(Decimal(str(r["error_pct"])) for r in settled_rows)
    mpe_pct = (total_mpe / n_dec).quantize(Decimal("0.01"))

    # Breakdown: ETF vs Stock
    etf_rows = [r for r in settled_rows if r["isin"] in etf_isins]
    stock_rows = [r for r in settled_rows if r["isin"] in stock_isins]

    etf_hit_rate_pct = None
    if etf_rows:
        etf_hits = sum(r["direction_hit"] for r in etf_rows)
        etf_hit_rate_pct = ((Decimal(str(etf_hits)) / Decimal(str(len(etf_rows)))) * Decimal("100")).quantize(Decimal("0.01"))

    stock_hit_rate_pct = None
    if stock_rows:
        stock_hits = sum(r["direction_hit"] for r in stock_rows)
        stock_hit_rate_pct = ((Decimal(str(stock_hits)) / Decimal(str(len(stock_rows)))) * Decimal("100")).quantize(Decimal("0.01"))

    # -------------------------------------------------------------------------
    # Baseline Model Benchmarking (IP-5 Audit Requirement)
    # 1. Baseline: "Price Unchanged" (Martingale / Always FLAT)
    # 2. Baseline: "Yesterday's Direction Continues" (Momentum Persist)
    # -------------------------------------------------------------------------
    deadband = Decimal("0.0010")
    flat_hits = 0
    actual_directions: List[tuple[str, str, str]] = []  # (isin, target_date, actual_dir)

    for r in settled_rows:
        ref_p = Decimal(str(r["reference_price"]))
        act_p = Decimal(str(r["actual_close_price"]))
        if ref_p > 0:
            delta = (act_p - ref_p) / ref_p
        else:
            delta = Decimal("0")
        if abs(delta) < deadband:
            act_dir = "FLAT"
        elif delta > 0:
            act_dir = "UP"
        else:
            act_dir = "DOWN"
        if act_dir == "FLAT":
            flat_hits += 1
        actual_directions.append((r["isin"], r["target_date"], act_dir))

    baseline_flat_hit_rate_pct = ((Decimal(str(flat_hits)) / n_dec) * Decimal("100")).quantize(Decimal("0.01"))

    # Yesterday's direction benchmark
    # Sort actual directions chronologically per ISIN
    actual_directions.sort(key=lambda x: (x[0], x[1]))
    yesterday_hits = 0
    yesterday_pairs = 0
    for idx in range(1, len(actual_directions)):
        prev_isin, prev_date, prev_dir = actual_directions[idx - 1]
        curr_isin, curr_date, curr_dir = actual_directions[idx]
        if curr_isin == prev_isin and curr_date > prev_date:
            yesterday_pairs += 1
            if prev_dir == curr_dir:
                yesterday_hits += 1

    baseline_yesterday_hit_rate_pct = None
    if yesterday_pairs > 0:
        baseline_yesterday_hit_rate_pct = (
            (Decimal(str(yesterday_hits)) / Decimal(str(yesterday_pairs))) * Decimal("100")
        ).quantize(Decimal("0.01"))

    # Benchmark evaluation
    beats_baselines = True
    underperformed_reasons: List[str] = []
    if hit_rate_pct <= baseline_flat_hit_rate_pct:
        beats_baselines = False
        underperformed_reasons.append(f"'Değişmez' (%{hit_rate_pct} <= %{baseline_flat_hit_rate_pct})")
    if baseline_yesterday_hit_rate_pct is not None and hit_rate_pct <= baseline_yesterday_hit_rate_pct:
        beats_baselines = False
        underperformed_reasons.append(f"'Dünkü Yön' (%{hit_rate_pct} <= %{baseline_yesterday_hit_rate_pct})")

    if not beats_baselines:
        baseline_warning = (
            f"⚠️ DİKKAT: Model baz modellerden ({', '.join(underperformed_reasons)}) "
            "daha düşük veya eşit performans gösteriyor; ek tahmin gücü sağlamıyor."
        )
    else:
        baseline_warning = "✓ Model baz modelleri (değişmez ve dünkü yön) geride bıraktı."

    is_small_sample = (settled_count < 30)
    warning_msg = (
        f"DİKKAT: İstatistiksel anlamlılık için en az 30 gözlem gereklidir (mevcut: N={settled_count})."
        if is_small_sample else None
    )

    return ForecastPerformanceMetrics(
        total_forecasts=total_forecasts,
        settled_count=settled_count,
        pending_count=pending_count,
        hit_rate_pct=hit_rate_pct,
        etf_hit_rate_pct=etf_hit_rate_pct,
        stock_hit_rate_pct=stock_hit_rate_pct,
        mape_pct=mape_pct,
        mae_eur=mae_eur,
        mpe_pct=mpe_pct,
        is_small_sample=is_small_sample,
        warning_message=warning_msg,
        baseline_flat_hit_rate_pct=baseline_flat_hit_rate_pct,
        baseline_yesterday_hit_rate_pct=baseline_yesterday_hit_rate_pct,
        beats_baselines=beats_baselines,
        baseline_warning=baseline_warning,
    )
