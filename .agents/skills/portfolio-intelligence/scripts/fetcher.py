"""Optional daily market context; no account valuation, news or option estimates."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from engine import MARKET_INSTRUMENTS, WORKSPACE_DIR


def summarize_bars(bars, kind):
    """Price changes use exactly N observed sessions and previous year/month close."""
    clean = {}
    for item in bars:
        day = date.fromisoformat(item["date"])
        value = float(item["close"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Geçersiz günlük gözlem")
        clean[day] = value
    dates = sorted(clean)
    if len(dates) < 2:
        raise ValueError("En az iki tamamlanmış günlük gözlem gerekli")
    latest, previous = dates[-1], dates[-2]
    price = clean[latest]
    def change(base):
        if base is None:
            return None
        difference = price - clean[base]
        if kind == "yield":
            return difference * 100  # percentage points to basis points
        if kind == "volatility":
            return difference
        return 100 * difference / clean[base]
    month = [day for day in dates if day < latest.replace(day=1)]
    year = [day for day in dates if day < latest.replace(month=1, day=1)]
    five = dates[-6] if len(dates) >= 6 else None
    month_base = month[-1] if month else None
    year_base = year[-1] if year else None
    # A truncated history must not pretend to provide MTD/YTD.
    if month_base and (latest.replace(day=1) - month_base).days > 7:
        month_base = None
    if year_base and (latest.replace(month=1, day=1) - year_base).days > 7:
        year_base = None
    return {
        "price": price, "bar_date": latest.isoformat(),
        "change_unit": "bp" if kind == "yield" else "puan" if kind == "volatility" else "%",
        "changes": {"1d": change(previous), "5d": change(five),
                    "mtd": change(month_base), "ytd": change(year_base)},
        "period_starts": {"1d": previous.isoformat(), "5d": five.isoformat() if five else None,
                          "mtd": month_base.isoformat() if month_base else None,
                          "ytd": year_base.isoformat() if year_base else None},
    }


def download_symbol(symbol, spec, now):
    import yfinance as yf  # Keep offline reporting independent of network packages.
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="2y", interval="1d", auto_adjust=False,
                             actions=False, repair=False, timeout=8, raise_errors=True)
    metadata = ticker.get_history_metadata()
    zone_name = metadata.get("exchangeTimezoneName")
    currency = metadata.get("currency")
    if not zone_name or not currency:
        raise ValueError("Kaynak borsa saat dilimi veya para birimi vermedi")
    local_day = now.astimezone(ZoneInfo(zone_name)).date()
    bars = []
    if history.index.tz is None:
        raise ValueError("Günlük serinin saat dilimi yok")
    for stamp, row in history.iterrows():
        day = stamp.tz_convert(zone_name).date()
        value = float(row["Close"])
        # Deliberately exclude today's entire daily bar, even after the close.
        if day < local_day and math.isfinite(value) and value > 0:
            bars.append({"date": day.isoformat(), "close": value})
    result = summarize_bars(bars, spec["kind"])
    result.update(
        currency=currency, exchange_timezone=zone_name,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="Yahoo Finance / yfinance",
        source_url=f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/history/",
        price_type="Önceki seans günlük Close; dağıtımlar dahil değil",
    )
    return result


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".market-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_market_data(force=False, root=None, loader=None, now=None):
    root = Path(root or WORKSPACE_DIR)
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Saat dilimi gerekli")
    path = root / "data/market_cache.json"
    # Invalid existing JSON is an error, not permission to destroy the cache.
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cache = old if old.get("schema_version") == 2 else {"schema_version": 2, "symbols": {}}
    cache["attempts"] = {}
    if loader is None:
        import yfinance as yf
        yf.set_tz_cache_location(str(root / "data/provider-cache"))
        loader = download_symbol
    succeeded = 0
    for symbol, spec in MARKET_INSTRUMENTS.items():
        try:
            record = loader(symbol, spec, now)
            checked_at = fixed_now or datetime.now(timezone.utc)
            # Validate essential fields before replacing a previous good observation.
            if not math.isfinite(float(record["price"])) or float(record["price"]) <= 0:
                raise ValueError("Geçersiz fiyat")
            if date.fromisoformat(record["bar_date"]) >= checked_at.astimezone(ZoneInfo(record["exchange_timezone"])).date():
                raise ValueError("Günlük gözlem henüz tamamlanmamış")
            stamp = datetime.fromisoformat(record["retrieved_at"])
            if stamp.tzinfo is None or stamp > checked_at or not record.get("currency") or not record.get("source_url"):
                raise ValueError("Fiyat tarihi, birimi veya kaynağı eksik")
            cache["symbols"][symbol] = record
            cache["attempts"][symbol] = {"status": "ok", "at": checked_at.isoformat()}
            succeeded += 1
        except Exception as error:
            # No zero, last cost or synthetic value replaces a failed request.
            cache["attempts"][symbol] = {
                "status": "error", "at": (fixed_now or datetime.now(timezone.utc)).isoformat(),
                "message": f"{type(error).__name__}: {str(error)[:240]}",
            }
    cache["last_fetch"] = {"at": (fixed_now or datetime.now(timezone.utc)).isoformat(), "success": succeeded,
                            "requested": len(MARKET_INSTRUMENTS)}
    atomic_json(path, cache)
    return cache["last_fetch"]
