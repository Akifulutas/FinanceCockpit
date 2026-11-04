"""iShares CSV holdings parser (İP-4).

Supports dynamic header detection, German and international locale headers,
metadata extraction (as-of date), robust comma/period decimal parsing,
percentage normalization to [0.0, 1.0], asset class segregation, and non-inflation verification.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from masa.holdings.models import (
    AssetClass,
    HoldingsValidationError,
    ParsedHoldingItem,
    ParsedHoldingsSet,
)

ISIN_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Date pattern matchers
DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(\d{1,2})\.([A-Za-z]{3,4})\.(\d{4})"), "%d.%b.%Y"),
    (re.compile(r"(\d{2})\.(\d{2})\.(\d{4})"), "%d.%m.%Y"),
    (re.compile(r"(\d{2})/(\d{2})/(\d{4})"), "%d/%m/%Y"),
    (re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})"), "%d-%b-%Y"),
    (re.compile(r"([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})"), "%b %d, %Y"),
    (re.compile(r"(\d{1,2})\s+([A-Za-z]{3,4})\s+(\d{4})"), "%d %b %Y"),
]

# Header normalization mappings
TICKER_ALIASES = {"ticker", "issuer ticker", "emittententicker", "tkr"}
NAME_ALIASES = {"name", "holding name", "wertpapiername", "security name", "company name", "bezeichnung"}
ISIN_ALIASES = {"isin", "identifier", "kennnummer"}
WEIGHT_ALIASES = {"weight (%)", "weight", "gewichtung (%)", "gewichtung", "weighting"}
SHARES_ALIASES = {"shares", "anteile", "nominal", "shares held", "quantity", "bestand"}
MARKET_VALUE_ALIASES = {"market value", "marktwert", "value", "notional value"}
SECTOR_ALIASES = {"sector", "sektor"}
COUNTRY_ALIASES = {"country", "land", "location", "standort"}
CURRENCY_ALIASES = {"currency", "währung", "market currency", "handelswährung"}
ASSET_CLASS_ALIASES = {"asset class", "assetklasse", "anlageklasse"}


def clean_decimal(value: Any) -> Optional[Decimal]:
    """Parse string representation of decimal number handling comma/period locales."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    s = str(value).strip()
    if not s or s in ("-", "--", "N/A", "n/a", "null", "None", "."):
        return None

    # Remove currency symbols and percent signs
    s = re.sub(r"[€$£¥%\s]", "", s)

    # Handle thousands and decimal separators
    if "," in s and "." in s:
        # Determine which comes last
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            # European format: 1.234,56 -> 1234.56
            s = s.replace(".", "").replace(",", ".")
        else:
            # US/UK format: 1,234.56 -> 1234.56
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") > 1 and "." not in s:
            # Multiple commas without dot: thousands separators e.g. 1,234,567 -> 1234567
            s = s.replace(",", "")
        else:
            # Only comma: European decimal e.g. 3,84 -> 3.84
            s = s.replace(",", ".")

    try:
        dec = Decimal(s)
        if not dec.is_finite():
            return None
        return dec
    except InvalidOperation:
        return None


def extract_as_of_date_from_text(text: str) -> Optional[date]:
    """Search for date patterns in metadata rows."""
    for pattern, dt_format in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            matched_str = match.group(0)
            try:
                # Handle month name replacement for German if needed
                german_months = {
                    "Jan": "Jan", "Feb": "Feb", "Mär": "Mar", "Mrz": "Mar", "Apr": "Apr",
                    "Mai": "May", "Jun": "Jun", "Jul": "Jul", "Aug": "Aug", "Sep": "Sep",
                    "Okt": "Oct", "Nov": "Nov", "Dez": "Dec"
                }
                normalized_dt_str = matched_str
                for g_m, en_m in german_months.items():
                    normalized_dt_str = normalized_dt_str.replace(g_m, en_m)
                dt = datetime.strptime(normalized_dt_str, dt_format)
                return dt.date()
            except ValueError:
                continue
    return None


def classify_asset_class(raw_class: Optional[str], name: str, ticker: Optional[str]) -> str:
    """Classify holding into EQUITY, CASH, DERIVATIVE, OTHER."""
    n_lower = name.lower()
    c_lower = (raw_class or "").lower().strip()
    t_lower = (ticker or "").lower().strip()

    # Cash checks
    if any(k in c_lower for k in ["cash", "barmittel", "money market", "collateral"]):
        return AssetClass.CASH.value
    if any(k in n_lower for k in ["cash collateral", "usd cash", "eur cash", "barmittel", "cash offset", "blackrock ics"]):
        return AssetClass.CASH.value
    if t_lower in ["cash", "usd", "eur", "gbp"]:
        return AssetClass.CASH.value

    # Derivative checks
    if any(k in c_lower for k in ["futures", "future", "derivate", "derivative", "forward", "option", "swap"]):
        return AssetClass.DERIVATIVE.value
    if any(k in n_lower for k in [" fut", " future", " forward", " fwd", " opt ", " swap "]):
        return AssetClass.DERIVATIVE.value

    # Equity checks
    if any(k in c_lower for k in ["equity", "aktien", "stock", "shares"]):
        return AssetClass.EQUITY.value

    # If raw class is other known non-equity
    if any(k in c_lower for k in ["bond", "anleihen", "fixed income", "debt"]):
        return AssetClass.OTHER.value

    # Default heuristic: if not cash or derivative, consider equity
    return AssetClass.EQUITY.value


class ISharesParser:
    """Parser for BlackRock / iShares UCITS ETF holdings CSV files."""

    @classmethod
    def parse(
        cls,
        content: Union[str, bytes, Path],
        isin: str,
        as_of_date: Optional[date] = None,
        source_file_name: str = "ishares_holdings.csv",
    ) -> ParsedHoldingsSet:
        """Parse iShares CSV into a verified ParsedHoldingsSet."""
        if isinstance(content, Path):
            source_file_name = content.name
            raw_text = content.read_text(encoding="utf-8-sig", errors="replace")
        elif isinstance(content, bytes):
            raw_text = content.decode("utf-8-sig", errors="replace")
        else:
            raw_text = content

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            raise HoldingsValidationError("iShares CSV dosyası boş.")

        # Detect delimiter (comma or semicolon)
        sample = "\n".join(lines[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ";" if ";" in sample and sample.count(";") > sample.count(",") else ","

        # Scan for header line within first 30 lines
        header_idx = -1
        col_map: Dict[str, int] = {}
        detected_as_of: Optional[date] = None

        for idx, line in enumerate(lines[:35]):
            reader = csv.reader([line], delimiter=delimiter)
            row = next(reader, [])
            row_lower = [c.strip().lower() for c in row]

            # Check for as_of_date in metadata lines before header
            if detected_as_of is None:
                d = extract_as_of_date_from_text(line)
                if d is not None:
                    detected_as_of = d

            # Check if this row is the header candidate
            has_name = any(c in NAME_ALIASES for c in row_lower)
            has_weight = any(c in WEIGHT_ALIASES for c in row_lower)
            has_ticker = any(c in TICKER_ALIASES for c in row_lower)
            has_isin = any(c in ISIN_ALIASES for c in row_lower)

            matches = sum([has_name, has_weight, has_ticker or has_isin])
            if matches >= 2 and (has_name or has_isin):
                header_idx = idx
                for col_i, col_name in enumerate(row_lower):
                    if col_name in NAME_ALIASES and "name" not in col_map:
                        col_map["name"] = col_i
                    elif col_name in WEIGHT_ALIASES and "weight" not in col_map:
                        col_map["weight"] = col_i
                    elif col_name in TICKER_ALIASES and "ticker" not in col_map:
                        col_map["ticker"] = col_i
                    elif col_name in ISIN_ALIASES and "isin" not in col_map:
                        col_map["isin"] = col_i
                    elif col_name in SHARES_ALIASES and "shares" not in col_map:
                        col_map["shares"] = col_i
                    elif col_name in MARKET_VALUE_ALIASES and "market_value" not in col_map:
                        col_map["market_value"] = col_i
                    elif col_name in SECTOR_ALIASES and "sector" not in col_map:
                        col_map["sector"] = col_i
                    elif col_name in COUNTRY_ALIASES and "country" not in col_map:
                        col_map["country"] = col_i
                    elif col_name in CURRENCY_ALIASES and "currency" not in col_map:
                        col_map["currency"] = col_i
                    elif col_name in ASSET_CLASS_ALIASES and "asset_class" not in col_map:
                        col_map["asset_class"] = col_i
                break

        if header_idx == -1 or "name" not in col_map or "weight" not in col_map:
            raise HoldingsValidationError("iShares CSV başlık satırı (Name ve Weight sütunları) tespit edilemedi.")

        final_as_of_date = as_of_date or detected_as_of
        if final_as_of_date is None:
            # Fallback to today if not extractable
            final_as_of_date = date.today()

        raw_items: List[Dict[str, Any]] = []
        csv_reader = csv.reader(lines[header_idx + 1:], delimiter=delimiter)

        for row in csv_reader:
            if not row or len(row) <= max(col_map.values(), default=0):
                continue

            name = row[col_map["name"]].strip()
            if not name or name.lower().startswith("total") or name.lower().startswith("gesamt"):
                continue

            w_val = clean_decimal(row[col_map["weight"]])
            if w_val is None:
                continue

            c_isin = row[col_map["isin"]].strip() if "isin" in col_map and col_map["isin"] < len(row) else None
            if c_isin and (len(c_isin) != 12 or not ISIN_REGEX.match(c_isin)):
                c_isin = None

            c_ticker = row[col_map["ticker"]].strip() if "ticker" in col_map and col_map["ticker"] < len(row) else None
            if c_ticker == "-" or not c_ticker:
                c_ticker = None

            shares = clean_decimal(row[col_map["shares"]]) if "shares" in col_map and col_map["shares"] < len(row) else None
            m_val = clean_decimal(row[col_map["market_value"]]) if "market_value" in col_map and col_map["market_value"] < len(row) else None
            sector = row[col_map["sector"]].strip() if "sector" in col_map and col_map["sector"] < len(row) else None
            if sector == "-":
                sector = None

            country = row[col_map["country"]].strip() if "country" in col_map and col_map["country"] < len(row) else None
            if country == "-":
                country = None

            currency = row[col_map["currency"]].strip() if "currency" in col_map and col_map["currency"] < len(row) else None
            if currency == "-":
                currency = None

            raw_asset_class = row[col_map["asset_class"]].strip() if "asset_class" in col_map and col_map["asset_class"] < len(row) else None
            asset_class = classify_asset_class(raw_asset_class, name, c_ticker)

            raw_items.append({
                "name": name,
                "weight": w_val,
                "isin": c_isin,
                "ticker": c_ticker,
                "shares": shares,
                "market_value": m_val,
                "sector": sector,
                "country": country,
                "currency": currency,
                "asset_class": asset_class,
            })

        if not raw_items:
            raise HoldingsValidationError("iShares CSV dosyasında geçerli sepet satırı bulunamadı.")

        # Determine if weights are in percentage points [0, 100] or normalized [0.0, 1.0]
        # Sum positive weights to inspect scale
        sum_weights = sum((item["weight"] for item in raw_items), Decimal("0"))
        needs_div_100 = sum_weights > Decimal("1.5")

        parsed_items: List[ParsedHoldingItem] = []
        for idx, r in enumerate(raw_items, start=1):
            norm_weight = r["weight"] / Decimal("100") if needs_div_100 else r["weight"]
            if r["asset_class"] == AssetClass.EQUITY.value and norm_weight < Decimal("0"):
                raise HoldingsValidationError("Negatif hisse senedi ağırlığı kabul edilemez: Fiziksel hisse senetleri negatif ağırlık taşıyamaz")
            parsed_items.append(
                ParsedHoldingItem(
                    item_order=idx,
                    constituent_name=r["name"],
                    weight_pct=norm_weight,
                    constituent_isin=r["isin"],
                    constituent_ticker=r["ticker"],
                    shares_held=r["shares"],
                    market_value=r["market_value"],
                    currency=r["currency"],
                    sector=r["sector"],
                    country=r["country"],
                    asset_class=r["asset_class"],
                )
            )

        total_weight = sum((item.weight_pct for item in parsed_items), Decimal("0"))
        if total_weight > Decimal("1.0001"):
            raise HoldingsValidationError(
                f"Sepet ağırlık toplamı {total_weight} üst sınırı (1.0001) aşıyor (şişirme/hata tespiti)."
            )

        total_equity = sum((item.weight_pct for item in parsed_items if item.asset_class == AssetClass.EQUITY.value), Decimal("0"))
        total_cash = sum((item.weight_pct for item in parsed_items if item.asset_class == AssetClass.CASH.value), Decimal("0"))
        total_deriv = sum((item.weight_pct for item in parsed_items if item.asset_class == AssetClass.DERIVATIVE.value), Decimal("0"))

        return ParsedHoldingsSet(
            isin=isin,
            as_of_date=final_as_of_date,
            source_file=source_file_name,
            provider="iShares",
            total_records=len(parsed_items),
            total_weight_pct=total_weight,
            total_equity_weight=total_equity,
            total_cash_weight=total_cash,
            total_derivative_weight=total_deriv,
            items=parsed_items,
        )
