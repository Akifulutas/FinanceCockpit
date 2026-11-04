"""Havuz taramasi: ETF/hisse adaylarini Scalable verisiyle olc, siralama yap.

Cikti "ARASTIRMAYA DEGER / IZLE / ELENDI" etiketidir; alim emri degildir. Her
aday icin sc quote + sc chart (1y) muhurlenir (snapshot run_id = scan_*).
Puan bilesenleri seffaftir: 6A ve 1Y momentum, trend, Sharpe, makas ve mevcut
portfoyle korelasyon (cesitlendirme katkisi).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

import numpy as np

from masa.analytics import RiskMetrics, aligned_frame, risk_metrics
from masa.config import Config
from masa.pipeline import Pipeline, classify_quote


DEFAULT_SCAN_WEIGHTS: Dict[str, float] = {
    "perf_6m": 0.25,
    "perf_1y": 0.25,
    "sharpe": 0.25,
    "trend_gap": 0.15,
    "corr_to_portfolio": 0.10,
}


@dataclass
class Candidate:
    isin: str
    group: str
    name: str
    held: bool
    spread_pct: Optional[float] = None
    perf_6m: Optional[float] = None
    perf_1y: Optional[float] = None
    metrics: Optional[RiskMetrics] = None
    corr_to_portfolio: Optional[float] = None
    score: Optional[float] = None
    label: str = "ELENDİ"
    reasons: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _z(values: List[Optional[float]]) -> List[float]:
    arr = np.array([v if v is not None else np.nan for v in values], dtype=float)
    mu, sd = np.nanmean(arr), np.nanstd(arr)
    return [0.0 if (np.isnan(x) or sd == 0) else float((x - mu) / sd) for x in arr]


def scan(pipe: Pipeline, cfg: Config, portfolio_series: List, held: set) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    run_id = f"scan_{started.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    pipe.audit.log_event("masa.scanner", "RUN_STARTED", "run", run_id, {"pool": {g: list(v) for g, v in cfg.pool.items()}})
    cands: List[Candidate] = []
    quote_rows, parts = [], []
    for group, items in cfg.pool.items():
        for isin, meta in items.items():
            c = Candidate(isin=isin, group=group, name=meta.get("ad", isin), held=isin in held)
            try:
                q = pipe.reader.get_quote(isin)
                raw = pipe.reader.last_raw
                rid = pipe._store_raw(raw, 1)
                parts.append((rid, raw.payload_sha256))
                status, age = classify_quote(q, datetime.now(timezone.utc), pipe.calendar)
                quote_rows.append({"raw_object_id": rid, "isin": q.isin, "alias": q.name, "currency": q.currency,
                                   "bid": q.bid, "ask": q.ask, "provider_mid": q.mid, "computed_mid": q.computed_mid,
                                   "spread": q.spread, "spread_pct": q.spread_pct, "quote_timestamp": q.timestamp_utc,
                                   "retrieved_at": raw.retrieved_at, "quote_age_seconds": round(age, 3),
                                   "source": "sc.broker.quote", "provider_outdated": q.is_outdated,
                                   "quality_status": status})
                c.name = q.name or c.name
                c.spread_pct = float(q.spread_pct)
                c.perf_6m = float(q.performances["SIX_MONTHS"]) if "SIX_MONTHS" in q.performances else None
                c.perf_1y = float(q.performances["ONE_YEAR"]) if "ONE_YEAR" in q.performances else None
                series = pipe.reader.get_chart(isin, "1y")
                sraw = pipe.reader.last_raw
                srid = pipe._store_raw(sraw, len(series.points))
                pts = [(p.timestamp_utc, p.mid_price) for p in series.points]
                pipe.store.save_snapshot("series", f"{run_id}_{isin}_1y", srid, f"sc.broker.chart:{series.source}",
                                         started, datetime.now(timezone.utc),
                                         [{"raw_object_id": srid, "series_key": f"{isin}:1y", "series_kind": "mid_price",
                                           "point_time": t, "value": v} for t, v in pts], run_id=run_id)
                c.metrics = risk_metrics(pts)
                if portfolio_series and not c.held:
                    df = aligned_frame({"p": portfolio_series, "c": pts})
                    if len(df) > 20:
                        c.corr_to_portfolio = float(df.pct_change().dropna().corr().iloc[0, 1])
            except Exception as exc:
                c.error = str(exc)[:200]
            cands.append(c)
    if quote_rows:
        rid_m, _ = pipe.store.store_manifest("sc.broker.quote", parts, datetime.now(timezone.utc), extra={"run_id": run_id})
        pipe.store.save_snapshot("quotes", f"{run_id}_quotes", rid_m, "sc.broker.quote", started,
                                 datetime.now(timezone.utc), quote_rows, run_id=run_id,
                                 quality_status="SCAN")

    ok = [c for c in cands if c.error is None and c.metrics is not None]
    if ok:
        raw_weights = cfg.policy.scan.get("agirliklar", DEFAULT_SCAN_WEIGHTS)
        weights = {k: float(v) for k, v in raw_weights.items()}
        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > 1e-4:
            raise ValueError(f"Tarama z-skoru ağırlıkları toplamı 1.0 olmalıdır (mevcut: {weight_sum:.4f})")

        w_6m = weights.get("perf_6m", 0.25)
        w_1y = weights.get("perf_1y", 0.25)
        w_sh = weights.get("sharpe", 0.25)
        w_tg = weights.get("trend_gap", 0.15)
        w_cr = weights.get("corr_to_portfolio", 0.10)

        z6 = _z([c.perf_6m for c in ok]); z12 = _z([c.perf_1y for c in ok])
        zs = _z([c.metrics.sharpe for c in ok]); zt = _z([c.metrics.trend_gap for c in ok])
        zc = _z([(-c.corr_to_portfolio) if c.corr_to_portfolio is not None else None for c in ok])
        for i, c in enumerate(ok):
            c.score = w_6m * z6[i] + w_1y * z12[i] + w_sh * zs[i] + w_tg * zt[i] + w_cr * zc[i]
    rules = cfg.policy.scan
    for c in cands:
        if c.error:
            c.reasons.append(f"Veri alınamadı: {c.error}")
            continue
        m = c.metrics
        if m is None:
            c.reasons.append("Fiyat geçmişi yetersiz.")
            continue
        fails = []
        if m.sharpe < rules["min_sharpe"]:
            fails.append(f"Sharpe {m.sharpe:.2f} < {rules['min_sharpe']}")
        if c.spread_pct is not None and c.spread_pct > rules["max_makas_yuzde"]:
            fails.append(f"makas %{c.spread_pct:.2f} > %{rules['max_makas_yuzde']}")
        if m.above_trend is False:
            fails.append("fiyat ~200 günlük ortalamanın altında")
        if c.corr_to_portfolio is not None and c.corr_to_portfolio > rules["max_korelasyon"]:
            c.reasons.append(f"Portföyle korelasyon {c.corr_to_portfolio:.2f}: çeşitlendirme katkısı sınırlı.")
        if fails:
            c.label = "İZLE"
            c.reasons.append("Ölçüt dışı: " + "; ".join(fails))
        else:
            c.label = "ARAŞTIRMAYA DEĞER"
            c.reasons.append("Trend üstünde, risk-düzeltilmiş getiri ve makas ölçütleri karşılanıyor.")
        if c.held:
            c.reasons.append("Zaten portföyde.")
    ranked = sorted(cands, key=lambda c: (c.score is None, -(c.score or 0)))
    pipe.audit.log_event("masa.scanner", "RUN_SEALED", "run", run_id,
                         {"ranked": [(c.isin, c.label, c.score) for c in ranked]})
    return {"run_id": run_id, "candidates": ranked}
