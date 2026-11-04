"""ETF snapshot reporting. Unknown inputs never become returns or valuations."""
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

WORKSPACE_DIR = Path(__file__).resolve().parents[4]
MARKET_INSTRUMENTS = {
    "^GSPC": {"name": "S&P 500", "unit": "puan", "kind": "index"},
    "^NDX": {"name": "Nasdaq 100", "unit": "puan", "kind": "index"},
    "^VIX": {"name": "VIX", "unit": "puan", "kind": "volatility"},
    "EURUSD=X": {"name": "EUR / USD", "unit": "USD / EUR", "kind": "fx"},
    "^TNX": {"name": "ABD 10 yıl nominal faiz", "unit": "%", "kind": "yield"},
    "^FVX": {"name": "ABD 5 yıl nominal faiz", "unit": "%", "kind": "yield"},
}
MISSING = [
    ("Güncel portföy değeri", "Adetler ve işlem borsaları doğrulanmadı."),
    ("Günlük / aylık / yıllık portföy getirisi", "Tarihli değer serisi ve nakit hareketleri yok."),
    ("Kâr / zarar", "Alış maliyetleri ve işlem geçmişi yok."),
    ("Nakit bakiyesi", "Bakiye paylaşılmadı."),
]


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def number(value):
    if value is None or value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Geçersiz sayısal veri")
    return result


def parse_stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Saat dilimi eksik")
    return result


def valid_source(source):
    if not isinstance(source, dict):
        raise ValueError("Kaynak bir nesne olmalı")
    url = source.get("url", source.get("source_url"))
    if not isinstance(url, str):
        raise ValueError("Kaynak URL'si eksik")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Kaynak URL'si geçersiz")
    for key in ("title", "date", "published_at", "retrieved_at"):
        if source.get(key) is not None and not isinstance(source[key], str):
            raise ValueError("Kaynak alanı metin olmalı: " + key)


def load_verified_funds(records_dir: Path, warnings=None) -> dict:
    warnings = warnings if warnings is not None else []
    file_path = records_dir / "dogrulanmis-fon-bilgileri.json"
    if not file_path.exists():
        warnings.append("Fon bilgi kaydı bulunamadı; eksik alanlar bilinmiyor olarak gösterilir.")
        return {}
    try:
        data = read_json(file_path)
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("funds"), list):
            raise ValueError("Fon bilgi dosyasının yapısı geçersiz")
        result = {}
        for fund in data["funds"]:
            if not isinstance(fund, dict) or not isinstance(fund.get("isin"), str) or not fund["isin"]:
                raise ValueError("Fon kimliği eksik")
            if fund["isin"] in result:
                raise ValueError("Mükerrer fon kimliği")
            valid_source(fund)
            if not isinstance(fund.get("legal_name"), str) or not fund["legal_name"]:
                raise ValueError("Fon adı eksik")
            for key in ("hedged", "ucits"):
                if fund.get(key) is not None and not isinstance(fund[key], bool):
                    raise ValueError("Boolean alanı geçersiz: " + key)
            if fund.get("ter_percent") is not None:
                value = fund["ter_percent"]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError("Gider oranı geçersiz")
            for key in ("issuer", "benchmark_index", "base_currency", "distribution_policy", "hedge_status_tr", "replication_method", "ter_note", "verification_note", "retrieved_at", "document_date"):
                if fund.get(key) is not None and not isinstance(fund[key], str):
                    raise ValueError("Fon alanı metin olmalı: " + key)
            listings = fund.get("reference_exchange_listings", [])
            if not isinstance(listings, list) or any(not isinstance(item, dict) or
                    any(not isinstance(item.get(key), str) or not item[key] for key in ("exchange", "ticker", "currency")) for item in listings):
                raise ValueError("Referans kotasyon kaydı geçersiz")
            result[fund["isin"]] = fund
        return result
    except (OSError, ValueError, TypeError, KeyError) as error:
        warnings.append(f"Fon bilgi kaydı doğrulanamadı; eksik değer üretilmedi: {error}")
        return {}


def load_latest_research(root: Path, now: datetime, zone: ZoneInfo, warnings: list) -> dict:
    reports_dir = root / "Yatirim-Masasi/raporlar"
    if not reports_dir.exists():
        return {"state": "Araştırma kaydı güncellenemedi", "data": None, "date": None}
    candidates = sorted(reports_dir.glob("*etf-arastirmasi.json"))
    if not candidates:
        return {"state": "Araştırma kaydı güncellenemedi", "data": None, "date": None}
    accepted, failure_state = [], "Araştırma kaydı okunamadı"
    local_today = now.astimezone(zone).date()
    for path in candidates:
        try:
            content = read_json(path)
            if not isinstance(content, dict) or content.get("schema_version") != 1:
                raise ValueError("Araştırma dosyasının yapısı geçersiz")
            day = date.fromisoformat(content["date"])
            if day > local_today:
                failure_state = "Geçersiz araştırma tarihi"
                raise ValueError("Araştırma tarihi gelecekte")
            generated = parse_stamp(content["generated_at"]) if content.get("generated_at") else None
            if generated and generated > now:
                failure_state = "Geçersiz araştırma tarihi"
                raise ValueError("Araştırma üretim zamanı gelecekte")
            macro = content.get("macro_summary", {})
            funds = content.get("funds", [])
            if not isinstance(macro, dict) or not isinstance(funds, list):
                raise ValueError("Araştırma bölümü yanlış türde")
            if not isinstance(macro.get("facts", []), list) or any(not isinstance(fact, str) for fact in macro.get("facts", [])):
                raise ValueError("Makro olgular metin listesi olmalı")
            for key in ("headline", "observation_dates", "economic_inference"):
                if macro.get(key) is not None and not isinstance(macro[key], str):
                    raise ValueError("Makro alanı metin olmalı")
            groups = [macro, *funds]
            for group in groups:
                if not isinstance(group, dict):
                    raise ValueError("Fon araştırması nesne olmalı")
                if group is not macro:
                    for key in ("isin", "fund_name", "what_changed", "economic_transmission", "counter_evidence", "next_check"):
                        if group.get(key) is not None and not isinstance(group[key], str):
                            raise ValueError("Fon araştırması alanı metin olmalı")
                sources = group.get("sources", [])
                if not isinstance(sources, list):
                    raise ValueError("Araştırma kaynakları liste olmalı")
                for source in sources:
                    valid_source(source)
            for key in ("verification_note", "disclaimer"):
                if content.get(key) is not None and not isinstance(content[key], str):
                    raise ValueError("Araştırma açıklaması metin olmalı")
            evidence = content.get("verification_status", "unreviewed")
            if evidence not in {"reviewed", "partial", "unreviewed"}:
                raise ValueError("Araştırma doğrulama durumu geçersiz")
            if not generated:
                evidence = "unreviewed"
            accepted.append((day, generated or datetime.min.replace(tzinfo=timezone.utc), path.name, content, evidence))
        except (OSError, ValueError, TypeError, KeyError) as error:
            warnings.append(f"Araştırma dosyası kullanılamadı ({path.name}): {error}")
    if not accepted:
        return {"state": failure_state, "data": None, "date": None}
    day, generated, name, content, evidence = max(accepted, key=lambda item: item[:3])
    state = "Güncel araştırma kaydı" if day == local_today else f"Önceki tarihli araştırma kaydı ({day.isoformat()})"
    if day < local_today:
        warnings.append(f"ETF araştırması bugüne ait değil; son kayıt tarihi: {day.isoformat()}.")
    labels = {"reviewed": "Kaynak kontrolü kaydedilmiş", "partial": "Doğrulama kısıtlı", "unreviewed": "İçerik doğrulaması kayıtlı değil"}
    if evidence != "reviewed":
        warnings.append("ETF araştırması: " + labels[evidence] + ". Kayıt tarihi içeriğin doğrulandığı anlamına gelmez.")
    return {"state": state, "data": content, "date": day.isoformat(), "file": name,
            "verification_status": evidence, "verification_label": labels[evidence]}


def run_all_engines(root=None, now=None):
    root = Path(root or WORKSPACE_DIR)
    records = root / "Yatirim-Masasi/veri"
    settings = read_json(records / "ayarlar.json")
    zone = ZoneInfo(settings["working_assumptions"].get("timezone", "Europe/Berlin"))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Rapor zamanı saat dilimi içermeli")
    currency = settings["working_assumptions"].get("report_currency", "EUR")
    context = settings.get("portfolio_context", {})
    with (records / "izleme-listesi.csv").open(encoding="utf-8", newline="") as stream:
        watchlist = {row["isin"]: row for row in csv.DictReader(stream)}
    with (records / "portfoy.csv").open(encoding="utf-8", newline="") as stream:
        positions = list(csv.DictReader(stream))
    warnings, seen = [], set()
    verified_funds = load_verified_funds(records, warnings)
    for position in positions:
        isin = position["isin"]
        if not isin or isin in seen:
            raise ValueError("Eksik veya mükerrer ISIN")
        seen.add(isin)
        value = number(position.get("market_value_base"))
        if value is not None and value < 0:
            raise ValueError("Negatif ekran değeri")
        if position.get("base_currency") != currency:
            raise ValueError("Ekran değerleri farklı para biriminde; kur doğrulaması gerekli")
        position["snapshot_value"] = value
        position["theme"] = watchlist.get(isin, {}).get("theme", "Maruziyet bilgisi eksik")
        source_url = watchlist.get(isin, {}).get("source_url", "")
        verified = verified_funds.get(isin, {})
        position["verified"] = verified
        position["legal_name"] = verified.get("legal_name", position["fund_name"])
        position["issuer"] = verified.get("issuer", "")
        position["ter_percent"] = verified.get("ter_percent")
        position["ter_note"] = verified.get("ter_note", "")
        position["benchmark_index"] = verified.get("benchmark_index", "")
        position["replication_method"] = verified.get("replication_method", "")
        position["distribution_policy"] = verified.get("distribution_policy")
        position["base_currency_verified"] = verified.get("base_currency")
        position["hedged_verified"] = verified.get("hedged")
        position["hedge_status_tr"] = verified.get("hedge_status_tr")
        position["reference_exchange_listings"] = verified.get("reference_exchange_listings", [])
        position["user_broker_status"] = verified.get("user_broker_status", "")
        position["source_url"] = source_url or verified.get("source_url", "")
    complete = bool(positions) and all(p["snapshot_value"] is not None for p in positions)
    visible_sum = sum(p["snapshot_value"] for p in positions) if complete else None
    for position in positions:
        position["snapshot_weight"] = (
            100 * position["snapshot_value"] / visible_sum if visible_sum else None
        )
    # This is the submitted screen header, never a newly priced account total.
    snapshot_total = number(context.get("displayed_total_eur")) if currency == "EUR" else None
    cache_path = root / "data/market_cache.json"
    cache = read_json(cache_path) if cache_path.exists() else {}
    if cache and cache.get("schema_version") != 2:
        warnings.append("Eski piyasa kaydında fiyat zamanı ve birimi doğrulanamıyor; sayılar kullanılmadı.")
        cache = {}
    market = []
    for symbol, instrument in MARKET_INSTRUMENTS.items():
        quote = cache.get("symbols", {}).get(symbol)
        attempt = cache.get("attempts", {}).get(symbol, {})
        item = {"symbol": symbol, **instrument, "quote": None, "state": "Veri yok"}
        if quote:
            try:
                stamp = parse_stamp(quote["retrieved_at"])
                bar_date = date.fromisoformat(quote["bar_date"])
                exchange_zone = ZoneInfo(quote["exchange_timezone"])
                local_day = now.astimezone(exchange_zone).date()
                if stamp > now or bar_date >= local_day or number(quote["price"]) <= 0:
                    raise ValueError("Gelecek veya tamamlanmamış gözlem")
                if not quote.get("currency") or not quote.get("source_url"):
                    raise ValueError("Kaynak veya para birimi eksik")
                age_days = (local_day - bar_date).days
                cache_old = (now - stamp).total_seconds() > 36 * 3600
                stale = age_days > 4 or cache_old or attempt.get("status") == "error"
                item.update(quote=quote, state="Eski kayıt" if stale else "Tarihli günlük veri")
            except (ValueError, KeyError, TypeError):
                warnings.append(f"{symbol}: fiyat kaydı doğrulanamadı; gösterilmedi.")
        if attempt.get("status") == "error":
            item["error"] = attempt.get("message", "Kaynak erişimi başarısız")
        market.append(item)
    research = load_latest_research(root, now, zone, warnings)
    return {
        "generated_at": now.astimezone(zone).isoformat(timespec="seconds"),
        "timezone": str(zone),
        "date": now.astimezone(zone).date().isoformat(),
        "portfolio": {
            "currency": currency, "positions": positions,
            "snapshot_total": snapshot_total, "visible_sum": visible_sum,
            "rounding_difference": round(visible_sum - snapshot_total, 2)
            if visible_sum is not None and snapshot_total is not None else None,
            "registered_on": context.get("registered_on"),
            "observed_at": context.get("observed_at"),
            "current_total": None, "daily_return": None, "monthly_return": None,
            "ytd_return": None, "cash": None, "cost_basis": None,
        },
        "market": market,
        "research": research,
        "verified_funds": list(verified_funds.values()),
        "warnings": warnings,
        "missing": MISSING,
        "fetch": cache.get("last_fetch"),
    }
