"""State Street SPDR holdings parser for XLSX and CSV files (İP-4).

Supports openpyxl XLSX extraction, dynamic column detection, header and footnote
filtering, decimal handling, percentage normalization to [0.0, 1.0], and invariant validation.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Union

from masa.holdings.models import (
    AssetClass,
    HoldingsValidationError,
    ParsedHoldingItem,
    ParsedHoldingsSet,
)
from masa.holdings.ishares_parser import (
    ISIN_REGEX,
    classify_asset_class,
    clean_decimal,
    extract_as_of_date_from_text,
)

# Header alias sets for SPDR
SPDR_TICKER_ALIASES = {"ticker", "local ticker", "symbol", "tkr"}
SPDR_NAME_ALIASES = {"name", "security name", "company name", "holding name", "description"}
SPDR_ISIN_ALIASES = {"isin", "identifier", "sedol", "cusip"}
SPDR_WEIGHT_ALIASES = {"weight", "weight (%)", "weighting", "weighting (%)", "% of net assets", "market value %"}
SPDR_SHARES_ALIASES = {"shares held", "shares", "quantity", "nominal"}
SPDR_VALUE_ALIASES = {"market value", "value", "local market value", "base market value"}
SPDR_SECTOR_ALIASES = {"sector", "gics sector"}
SPDR_COUNTRY_ALIASES = {"country", "location"}
SPDR_CURRENCY_ALIASES = {"local currency", "currency", "base currency"}


class SPDRParser:
    """Parser for State Street Global Advisors (SSGA / SPDR) holdings files."""

    @classmethod
    def parse(
        cls,
        content: Union[str, bytes, Path],
        isin: str,
        as_of_date: Optional[date] = None,
        source_file_name: str = "spdr_holdings.xlsx",
    ) -> ParsedHoldingsSet:
        """Parse SPDR XLSX or CSV into ParsedHoldingsSet."""
        if isinstance(content, Path):
            source_file_name = content.name
            if source_file_name.lower().endswith(".xlsx") or source_file_name.lower().endswith(".xls"):
                raw_rows, detected_date = cls._read_xlsx(content.read_bytes())
            else:
                raw_rows, detected_date = cls._read_csv(content.read_text(encoding="utf-8-sig", errors="replace"))
        elif isinstance(content, bytes):
            if source_file_name.lower().endswith(".xlsx") or source_file_name.lower().endswith(".xls") or content[:4] == b"PK\x03\x04":
                raw_rows, detected_date = cls._read_xlsx(content)
            else:
                raw_rows, detected_date = cls._read_csv(content.decode("utf-8-sig", errors="replace"))
        else:
            raw_rows, detected_date = cls._read_csv(content)

        if not raw_rows:
            raise HoldingsValidationError("SPDR dosyası boş veya satır bulunamadı.")

        final_as_of_date = as_of_date or detected_date or date.today()

        # Find header row
        header_idx = -1
        col_map: Dict[str, int] = {}

        for idx, row in enumerate(raw_rows[:25]):
            row_str = [str(c).strip().lower() for c in row if c is not None]
            has_name = any(c in SPDR_NAME_ALIASES for c in row_str)
            has_weight = any(c in SPDR_WEIGHT_ALIASES for c in row_str)
            has_ticker = any(c in SPDR_TICKER_ALIASES for c in row_str)
            has_isin = any(c in SPDR_ISIN_ALIASES for c in row_str)

            if sum([has_name, has_weight, has_ticker or has_isin]) >= 2:
                header_idx = idx
                for col_i, cell in enumerate(row):
                    if cell is None:
                        continue
                    c_low = str(cell).strip().lower()
                    if c_low in SPDR_NAME_ALIASES and "name" not in col_map:
                        col_map["name"] = col_i
                    elif c_low in SPDR_WEIGHT_ALIASES and "weight" not in col_map:
                        col_map["weight"] = col_i
                    elif c_low in SPDR_TICKER_ALIASES and "ticker" not in col_map:
                        col_map["ticker"] = col_i
                    elif c_low in SPDR_ISIN_ALIASES and "isin" not in col_map:
                        col_map["isin"] = col_i
                    elif c_low in SPDR_SHARES_ALIASES and "shares" not in col_map:
                        col_map["shares"] = col_i
                    elif c_low in SPDR_VALUE_ALIASES and "market_value" not in col_map:
                        col_map["market_value"] = col_i
                    elif c_low in SPDR_SECTOR_ALIASES and "sector" not in col_map:
                        col_map["sector"] = col_i
                    elif c_low in SPDR_COUNTRY_ALIASES and "country" not in col_map:
                        col_map["country"] = col_i
                    elif c_low in SPDR_CURRENCY_ALIASES and "currency" not in col_map:
                        col_map["currency"] = col_i
                break

        if header_idx == -1 or "name" not in col_map or "weight" not in col_map:
            raise HoldingsValidationError("SPDR başlık satırı (Name ve Weight sütunları) tespit edilemedi.")

        raw_items: List[Dict[str, Any]] = []
        for row in raw_rows[header_idx + 1:]:
            if not row or len(row) <= max(col_map.values(), default=0):
                continue

            name_cell = row[col_map["name"]]
            if name_cell is None:
                continue
            name = str(name_cell).strip()
            if not name:
                continue

            # Footnote and trailer filtering
            n_lower = name.lower()
            if n_lower.startswith(("total", "grand total", "subtotal", "*", "disclaimer", "source:")):
                continue
            if "subject to change" in n_lower or "ssga" in n_lower or "state street" in n_lower:
                continue

            w_cell = row[col_map["weight"]]
            w_dec = clean_decimal(w_cell)
            if w_dec is None:
                continue

            # ISIN
            c_isin = None
            if "isin" in col_map and col_map["isin"] < len(row):
                isin_raw = str(row[col_map["isin"]]).strip() if row[col_map["isin"]] is not None else ""
                if len(isin_raw) == 12 and ISIN_REGEX.match(isin_raw):
                    c_isin = isin_raw

            # Ticker
            c_ticker = None
            if "ticker" in col_map and col_map["ticker"] < len(row):
                t_raw = str(row[col_map["ticker"]]).strip() if row[col_map["ticker"]] is not None else ""
                if t_raw and t_raw not in ("-", "--", "N/A"):
                    c_ticker = t_raw

            shares = clean_decimal(row[col_map["shares"]]) if "shares" in col_map and col_map["shares"] < len(row) else None
            m_val = clean_decimal(row[col_map["market_value"]]) if "market_value" in col_map and col_map["market_value"] < len(row) else None
            sector = str(row[col_map["sector"]]).strip() if "sector" in col_map and col_map["sector"] < len(row) and row[col_map["sector"]] is not None else None
            if sector in ("-", "--", "N/A", "None", ""):
                sector = None

            country = str(row[col_map["country"]]).strip() if "country" in col_map and col_map["country"] < len(row) and row[col_map["country"]] is not None else None
            if country in ("-", "--", "N/A", "None", ""):
                country = None

            currency = str(row[col_map["currency"]]).strip() if "currency" in col_map and col_map["currency"] < len(row) and row[col_map["currency"]] is not None else None
            if currency in ("-", "--", "N/A", "None", ""):
                currency = None

            asset_class = classify_asset_class(None, name, c_ticker)

            raw_items.append({
                "name": name,
                "weight": w_dec,
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
            raise HoldingsValidationError("SPDR dosyasında geçerli sepet satırı bulunamadı.")

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
            provider="SPDR",
            total_records=len(parsed_items),
            total_weight_pct=total_weight,
            total_equity_weight=total_equity,
            total_cash_weight=total_cash,
            total_derivative_weight=total_deriv,
            items=parsed_items,
        )

    @classmethod
    def _read_xlsx(cls, data: bytes) -> Tuple[List[List[Any]], Optional[date]]:
        """Read openpyxl workbook and return raw row matrix and detected date."""
        try:
            import openpyxl
        except ImportError as exc:
            raise HoldingsValidationError("openpyxl kurulu değil; XLSX dosyası açılamıyor.") from exc

        wb = openpyxl.load_workbook(filename=io.BytesIO(data), data_only=True, read_only=True)
        sheet = wb.active
        rows: List[List[Any]] = []
        detected_date: Optional[date] = None

        for row in sheet.iter_rows(values_only=True):
            r_list = list(row)
            rows.append(r_list)
            # Scan top rows for date if not yet detected
            if detected_date is None and len(rows) <= 10:
                row_text = " ".join([str(c) for c in r_list if c is not None])
                d = extract_as_of_date_from_text(row_text)
                if d is not None:
                    detected_date = d

        wb.close()
        return rows, detected_date

    @classmethod
    def _read_csv(cls, text: str) -> Tuple[List[List[Any]], Optional[date]]:
        """Read CSV text and return raw rows and detected date."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return [], None

        sample = "\n".join(lines[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ";" if ";" in sample and sample.count(";") > sample.count(",") else ","

        rows: List[List[Any]] = []
        detected_date: Optional[date] = None

        reader = csv.reader(lines, delimiter=delimiter)
        for idx, row in enumerate(reader):
            rows.append(row)
            if detected_date is None and idx <= 10:
                row_text = " ".join(row)
                d = extract_as_of_date_from_text(row_text)
                if d is not None:
                    detected_date = d

        return rows, detected_date
