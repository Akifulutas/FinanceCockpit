"""Muhurlu veriden analiz: risk (quantstats), korelasyon, getiri yeniden kurulumu.

Fiyat kaynagi tektir: `sc broker chart` serileri (masa.db). Disaridan fiyat
indirilmez. Seriler ornekleme araliklidir (1y ~ 2 gunde bir nokta); yillik
olcekleme gozlenen nokta sikligindan (periods_per_year) yapilir ve raporda yazilir.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from masa.calc import performance as perf_engine

Series = List[Tuple[datetime, Decimal]]


def _qs():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import quantstats as qs  # noqa: WPS433 (heavy import, lazy)
    return qs


def to_pandas(series: Series) -> pd.Series:
    s = pd.Series([float(v) for _, v in series],
                  index=pd.DatetimeIndex([t for t, _ in series]).tz_convert("UTC"))
    return s[~s.index.duplicated(keep="last")].sort_index()


def periods_per_year(prices: pd.Series) -> float:
    span_days = (prices.index[-1] - prices.index[0]).total_seconds() / 86400.0
    return (len(prices) - 1) / (span_days / 365.0) if span_days > 0 else float("nan")


@dataclass
class RiskMetrics:
    points: int
    start: str
    end: str
    periods_per_year: float
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    from_high: float
    above_trend: Optional[bool]
    trend_gap: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def risk_metrics(series: Series, rf: float = 0.0) -> Optional[RiskMetrics]:
    if len(series) < 20:
        return None
    prices = to_pandas(series)
    rets = prices.pct_change().dropna()
    ppy = periods_per_year(prices)
    qs = _qs()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = max(1, int(round(ppy)))
        vol = float(qs.stats.volatility(rets, periods=n))
        sharpe = float(qs.stats.sharpe(rets, rf=rf, periods=n))
        sortino = float(qs.stats.sortino(rets, rf=rf, periods=n))
        mdd = float(qs.stats.max_drawdown(prices))
    years = (prices.index[-1] - prices.index[0]).total_seconds() / (365.0 * 86400)
    total = float(prices.iloc[-1] / prices.iloc[0] - 1)
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else float("nan")
    window = max(10, int(round(n * 200 / 252)))  # ~200 trading days in observed sampling
    trend = prices.iloc[-window:].mean() if len(prices) >= window else None
    gap = float(prices.iloc[-1] / trend - 1) if trend else None
    return RiskMetrics(points=len(prices), start=prices.index[0].date().isoformat(),
                       end=prices.index[-1].date().isoformat(), periods_per_year=ppy,
                       total_return=total, cagr=cagr, volatility=vol, sharpe=sharpe, sortino=sortino,
                       max_drawdown=mdd, from_high=float(prices.iloc[-1] / prices.max() - 1),
                       above_trend=(gap > 0) if gap is not None else None, trend_gap=gap)


def aligned_frame(series_by_isin: Dict[str, Series]) -> pd.DataFrame:
    """Daily (calendar-day) last-observation alignment of several sampled series."""
    frames = {}
    for isin, s in series_by_isin.items():
        if s:
            p = to_pandas(s)
            frames[isin] = p.groupby(p.index.normalize()).last()
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames).sort_index()
    return df.ffill().dropna()


def correlation_matrix(series_by_isin: Dict[str, Series]) -> Optional[pd.DataFrame]:
    df = aligned_frame(series_by_isin)
    if df.shape[1] < 2 or len(df) < 20:
        return None
    # resample to common observation days where all series have a fresh point
    rets = df.pct_change().dropna()
    return rets.corr()


def static_portfolio_series(series_by_isin: Dict[str, Series], quantities: Dict[str, Decimal]) -> Series:
    """Value of TODAY's holdings over the past window (what-if, not realized performance)."""
    df = aligned_frame({k: v for k, v in series_by_isin.items() if k in quantities})
    if df.empty or set(df.columns) != set(quantities):
        return []
    values = sum(df[c] * float(quantities[c]) for c in df.columns)
    return [(ts.to_pydatetime(), Decimal(str(round(v, 6)))) for ts, v in values.items()]


# ============================================================ realized returns
FLOW_MAP = {
    "DEPOSIT": "EXTERNAL_DEPOSIT", "CASH_TRANSFER_IN": "EXTERNAL_DEPOSIT", "POCKET_MONEY": "EXTERNAL_DEPOSIT",
    "WITHDRAWAL": "EXTERNAL_WITHDRAWAL", "CASH_TRANSFER_OUT": "EXTERNAL_WITHDRAWAL",
    "DISTRIBUTION": "INTERNAL_DIVIDEND", "INTEREST": "INTERNAL_DIVIDEND", "TAX_RETURN": "INTERNAL_DIVIDEND",
    "FEE": "BROKER_FEE", "TAX": "BROKER_FEE",
}
SETTLED = {"SETTLED", "FILLED", "CONFIRMED"}


@dataclass
class RealizedReturn:
    available: bool
    reason: str = ""
    start: Optional[str] = None
    end: Optional[str] = None
    deposits: Decimal = Decimal("0")
    withdrawals: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    gain: Optional[Decimal] = None
    twr_pct: Optional[Decimal] = None
    mdietz_pct: Optional[Decimal] = None
    xirr_pct: Optional[Decimal] = None
    xirr_status: str = ""
    cash_gap: Optional[Decimal] = None
    fifo_check: Dict[str, Tuple[Optional[Decimal], Optional[Decimal]]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)


def _price_at(series: Series, t: datetime) -> Optional[Decimal]:
    times = [p[0] for p in series]
    i = bisect_right(times, t) - 1
    return series[i][1] if i >= 0 else None


def realized_returns(transactions: Sequence[Dict[str, Any]], holdings: Dict[str, Decimal],
                     holding_values: Dict[str, Decimal], broker_fifo: Dict[str, Optional[Decimal]],
                     cash_now: Decimal, as_of: datetime, series_by_isin: Dict[str, Series]) -> RealizedReturn:
    """Rebuild the account from its first transaction and run the performance engine.

    Assumes the transaction history starts at account opening (zero equity). That
    assumption is TESTED: reconstructed share counts must equal broker holdings and
    the cash ledger must reconcile; otherwise the result is marked unavailable.
    """
    rows = [t for t in transactions if t["status"] in SETTLED and t["is_cancellation"] in ("0", "False", 0, False)]
    out = RealizedReturn(available=False)
    if not rows:
        out.reason = "İşlem geçmişi yok (önce `masa gecmis`)."
        return out

    # IP-3: Fail-safe transaction classification validation
    from masa.calc.transaction_classifier import ClassificationStatus, FlowClassification, classify_transaction
    unsupported = []
    for r in rows:
        c_status = r.get("classification_status") or r.get("flow_classification")
        if c_status in ("NEEDS_REVIEW", "UNKNOWN"):
            unsupported.append(f"{r.get('broker_tx_id') or 'unknown'}: inceleme bekliyor")
            continue
        c_res = classify_transaction(r)
        if c_res.status == ClassificationStatus.NEEDS_REVIEW or c_res.classification == FlowClassification.UNKNOWN:
            unsupported.append(f"{r.get('broker_tx_id') or 'unknown'}: {c_res.reason or 'desteklenmeyen tip'}")
    if unsupported:
        out.available = False
        out.reason = (
            "Getiri hesabı durduruldu: İnceleme bekleyen desteklenmeyen işlem tipi mevcut "
            f"({len(unsupported)} kayıt: {', '.join(unsupported[:3])}). "
            "Tasarım gereği eksik veriyle uydurma getiri hesaplanmaz."
        )
        out.warnings.append("İşlem sınıflandırma denetimi başarısız oldu (needs_review).")
        return out

    events = sorted(rows, key=lambda r: (r["event_time"], r.get("tx_row_id", 0)))
    flows, txs = [], []
    shares: Dict[str, Decimal] = {}
    for i, r in enumerate(events):
        ts = r["event_time"]
        amount = Decimal(r["amount"])
        if r["tx_type"] == "SECURITY_TRANSACTION" and r["side"] in ("BUY", "SELL") and r["quantity"]:
            q = abs(Decimal(r["quantity"]))
            if q == 0 or amount == 0:
                out.ignored.append(f"{r['broker_tx_id']}: sıfır adet/tutar")
                continue
            price = abs(amount) / q
            txs.append({"tx_id": r["broker_tx_id"] or f"t{i}", "timestamp": ts, "isin": r["isin"],
                        "side": r["side"], "shares": float(q), "execution_price": float(price),
                        "fees": 0, "taxes": 0, "total_cash_impact": float(amount)})
            shares[r["isin"]] = shares.get(r["isin"], Decimal("0")) + (q if r["side"] == "BUY" else -q)
        elif r["tx_type"] == "CASH_TRANSACTION" and r["cash_transaction_type"] in FLOW_MAP:
            typ = FLOW_MAP[r["cash_transaction_type"]]
            if typ == "BROKER_FEE" and amount > 0:
                typ = "INTERNAL_DIVIDEND"  # fee refund / tax refund
            if typ == "EXTERNAL_DEPOSIT" and amount < 0:
                typ = "EXTERNAL_WITHDRAWAL"
            if typ == "EXTERNAL_WITHDRAWAL" and amount > 0:
                typ = "EXTERNAL_DEPOSIT"
            flows.append({"flow_id": r["broker_tx_id"] or f"f{i}", "timestamp": ts, "amount": float(amount),
                          "currency": r["currency"], "raw_description": r["description"] or "",
                          "classified_type": typ})
            if typ == "EXTERNAL_DEPOSIT":
                out.deposits += amount
            elif typ == "EXTERNAL_WITHDRAWAL":
                out.withdrawals += amount
            elif typ == "BROKER_FEE":
                out.fees += amount
        else:
            out.ignored.append(f"{r['broker_tx_id']}: {r['tx_type']}/{r['cash_transaction_type'] or r['security_transaction_type']}")

    mismatch = {i: (shares.get(i, Decimal('0')), holdings.get(i, Decimal('0')))
                for i in set(shares) | set(holdings) if shares.get(i, Decimal('0')) != holdings.get(i, Decimal('0'))}
    if mismatch:
        out.reason = ("İşlem geçmişi hesabın başından başlamıyor veya eksik: yeniden kurulan adetler broker "
                      "pozisyonlarıyla uyuşmuyor: " + ", ".join(f"{k} {a}≠{b}" for k, a, b in
                                                              ((k, *v) for k, v in mismatch.items())))
        return out

    first = datetime.fromisoformat(events[0]["event_time"])
    start = (first - timedelta(seconds=1)).astimezone(timezone.utc)
    end = as_of.astimezone(timezone.utc)
    pos_value = sum(holding_values.values(), Decimal("0"))
    subs, missing_px = [], False
    flow_times = sorted({f["timestamp"] for f in flows if f["classified_type"].startswith("EXTERNAL")})
    for ts in flow_times:
        t = datetime.fromisoformat(ts)
        cash = Decimal("0")
        held: Dict[str, Decimal] = {}
        for r in events:
            if r["event_time"] >= ts:
                break
            if r["tx_type"] == "SECURITY_TRANSACTION" and r["side"] in ("BUY", "SELL") and r["quantity"]:
                q = abs(Decimal(r["quantity"]))
                held[r["isin"]] = held.get(r["isin"], Decimal("0")) + (q if r["side"] == "BUY" else -q)
            cash += Decimal(r["amount"]) if (r["tx_type"] == "SECURITY_TRANSACTION" or
                                             r["cash_transaction_type"] in FLOW_MAP) else Decimal("0")
        value = cash
        for isin, q in held.items():
            if q == 0:
                continue
            px = _price_at(series_by_isin.get(isin, []), t)
            if px is None:
                missing_px = True
                break
            value += q * px
        if missing_px:
            break
        subs.append({"timestamp": ts, "equity_before_flow": float(max(value, Decimal("0")))})
    if missing_px:
        subs = []
        out.warnings.append("Bazı akış tarihlerinde fiyat serisi yok: gerçek TWR hesaplanmadı (MD/XIRR kullanılabilir).")

    payload = {
        "evaluation_period": {"start_date": start.isoformat(), "end_date": end.isoformat(),
                              "calendar_days": (end.date() - start.date()).days or 1},
        "initial_valuation": {"total_equity": 0, "cash_balance": 0, "positions_value": 0},
        "terminal_valuation": {"total_equity": float(pos_value + cash_now), "cash_balance": float(cash_now),
                               "positions_value": float(pos_value)},
        "subperiod_valuations": subs, "cash_flows": flows, "transactions": txs,
        "accounting_options": {},
    }
    if payload["evaluation_period"]["calendar_days"] != (end.date() - start.date()).days:
        end = end + timedelta(days=1)
        payload["evaluation_period"]["end_date"] = end.isoformat()
    context = {"terminal_position_values": {k: float(v) for k, v in holding_values.items() if holdings.get(k)}}
    try:
        res = perf_engine.calculate_performance(payload, context=context)
    except Exception as exc:
        out.reason = f"Performans motoru hesaplayamadı: {exc}"
        return out
    s = res.returns_summary
    out.available = True
    out.start, out.end = start.date().isoformat(), end.date().isoformat()
    out.gain = s.absolute_gain_loss
    out.twr_pct = s.true_twr_cumulative_pct
    out.mdietz_pct = s.modified_dietz_pct
    out.xirr_pct, out.xirr_status = s.xirr_annualized_pct, s.xirr_convergence_status
    out.cash_gap = res.reconciliation_diagnostics.unexplained_cash_gap
    out.warnings.extend(res.reconciliation_diagnostics.warnings)
    for p in res.position_cost_basis:
        out.fifo_check[p.isin] = (p.fifo_cost_per_share, broker_fifo.get(p.isin))
    if subs:
        out.warnings.append("TWR alt dönem değerlemeleri gün sonu `sc broker chart` fiyatlarıyla yaklaşık hesaplandı.")
    return out
