"""Pairwise ETF Overlap Engine and Consolidated Look-Through Portfolio Exposure (İP-4).

Implements:
1. Pairwise constituent overlap: sum(min(w_A, w_B)) with symmetric matrix.
2. 3-tier constituent matching hierarchy: ISIN (primary) -> ticker -> normalized name.
3. Consolidated stock exposure (Top 25) with exact accounting identity:
   Top 25 + Other Reported Companies + Uncovered ETF Holdings + Cash = 100.0%.
4. Consolidated sector and country breakdowns.
5. 45-day staleness verification.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from masa.holdings.models import AssetClass
from masa.storage.db import DatabaseManager

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
EPSILON = Decimal("0.0001")

# Pre-known dual-class / ADR cross reference mappings (Tier 1 expansion)
ENTITY_CROSS_REFERENCES: Dict[str, str] = {
    # Alphabet Inc: Class A (US02079K3059) and Class C (US02079K1079)
    "US02079K3059": "ENTITY:US_ALPHABET",
    "US02079K1079": "ENTITY:US_ALPHABET",
    # Taiwan Semiconductor: ADR (US8740391003) and Ordinary (TW0002330008)
    "US8740391003": "ENTITY:TW_TSMC",
    "TW0002330008": "ENTITY:TW_TSMC",
}

LEGAL_SUFFIXES_REGEX = re.compile(
    r"\b(inc|incorporated|corp|corporation|ltd|limited|holdings|holding|group|plc|ag|se|sa|nv|spa|co|company|shs|ordinary|ord|class a|class b|class c|adr|gdr|as|ab|oyj)\b",
    re.IGNORECASE,
)


def normalize_constituent_name(name: str) -> str:
    """Normalize company name by stripping legal suffixes, punctuation, and extra whitespace."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"\ba/s\b", " ", s)
    s = LEGAL_SUFFIXES_REGEX.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def check_staleness(
    as_of_date: date,
    ref_date: Optional[date] = None,
    threshold_days: int = 45,
) -> Tuple[bool, int]:
    """Return whether the holdings date is older than threshold_days and the age in days."""
    target_ref = ref_date or date.today()
    age_days = (target_ref - as_of_date).days
    return (age_days > threshold_days), max(0, age_days)


class ConstituentHolding(BaseModel):
    """A constituent security within a fund's basket."""
    model_config = ConfigDict(frozen=True)

    holding_isin: Optional[str] = None
    ticker: Optional[str] = None
    name: str
    weight: Decimal  # Normalized proportion in [-1.0, 1.0]
    country: Optional[str] = None
    sector: Optional[str] = None
    asset_class: str = AssetClass.EQUITY.value


class FundHoldings(BaseModel):
    """Normalized fund basket for overlap and lookthrough calculation."""
    model_config = ConfigDict(frozen=True)

    isin: str
    fund_name: str
    as_of_date: date
    total_weight: Decimal
    equity_weight: Decimal
    cash_weight: Decimal
    derivative_weight: Decimal
    holdings: List[ConstituentHolding] = Field(default_factory=list)
    is_stale: bool = False
    age_days: int = 0


class SharedConstituent(BaseModel):
    """A common constituent holding shared between two funds."""
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    isin: Optional[str] = None
    ticker: Optional[str] = None
    weight_a: Decimal
    weight_b: Decimal
    min_weight: Decimal


class OverlapPairResult(BaseModel):
    """Result of pairwise overlap between two funds."""
    model_config = ConfigDict(frozen=True)

    fund_a_isin: str
    fund_b_isin: str
    fund_a_name: str
    fund_b_name: str
    overlap_score: Decimal  # in [0.0, 1.0]
    shared_count: int
    top_shared: List[SharedConstituent] = Field(default_factory=list)
    status: str = "EXACT"  # EXACT, REPORTED_ONLY, UNDETERMINED


class OverlapMatrix(BaseModel):
    """Symmetric matrix of pairwise overlap scores for N funds."""
    model_config = ConfigDict(frozen=True)

    fund_isins: List[str]
    fund_names: List[str]
    matrix: List[List[Decimal]]  # N x N overlap scores
    pairs: Dict[str, OverlapPairResult] = Field(default_factory=dict)


class ConsolidatedStockExposure(BaseModel):
    """Consolidated exposure to a single company across all portfolio funds."""
    model_config = ConfigDict(frozen=True)

    rank: int
    key: str
    name: str
    isin: Optional[str] = None
    ticker: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    portfolio_weight: Decimal  # Normalized proportion e.g. 0.0384
    valuation_eur: Optional[Decimal] = None
    cumulative_weight: Decimal
    contributions: Dict[str, Decimal] = Field(default_factory=dict)  # isin -> weight contrib


class BreakdownItem(BaseModel):
    """A category item in a sector or country breakdown."""
    model_config = ConfigDict(frozen=True)

    name: str
    weight: Decimal  # Normalized proportion
    valuation_eur: Optional[Decimal] = None


class ConsolidatedBreakdown(BaseModel):
    """Consolidated sector and country exposure distributions."""
    model_config = ConfigDict(frozen=True)

    sectors: List[BreakdownItem] = Field(default_factory=list)
    countries: List[BreakdownItem] = Field(default_factory=list)


class PortfolioExposureSummary(BaseModel):
    """Complete Top 25 consolidated stock look-through and concentration summary."""
    model_config = ConfigDict(frozen=True)

    top_stocks: List[ConsolidatedStockExposure] = Field(default_factory=list)
    top5_weight: Decimal
    top10_weight: Decimal
    top25_weight: Decimal
    other_stocks_weight: Decimal
    uncovered_etf_weight: Decimal
    cash_weight: Decimal
    total_reconciled_weight: Decimal  # Identity check: top25 + other + uncovered + cash == 1.0
    hhi: Decimal
    portfolio_total_eur: Optional[Decimal] = None
    is_fully_reconciled: bool
    staleness_warnings: List[str] = Field(default_factory=list)


def get_constituent_match_key(item: ConstituentHolding) -> str:
    """Return a canonical grouping key for a constituent holding based on 3-tier hierarchy."""
    # Tier 1: ISIN
    if item.holding_isin and len(item.holding_isin) == 12:
        return ENTITY_CROSS_REFERENCES.get(item.holding_isin, f"ISIN:{item.holding_isin}")

    # Tier 2: Ticker
    if item.ticker:
        cleaned_tkr = re.sub(r"\.[A-Za-z0-9]+$", "", item.ticker.strip().upper())
        if cleaned_tkr and cleaned_tkr not in ("-", "--", "N/A"):
            return f"TICKER:{cleaned_tkr}"

    # Tier 3: Normalized Name
    norm_name = normalize_constituent_name(item.name)
    if len(norm_name) >= 3:
        return f"NAME:{norm_name}"

    return f"RAW:{item.name.strip().upper()}"


def match_constituents(a: ConstituentHolding, b: ConstituentHolding) -> Optional[str]:
    """Determine whether two constituent holdings represent the same security using 3-tier hierarchy."""
    # Tier 1: ISIN (Strict)
    if a.holding_isin and b.holding_isin and len(a.holding_isin) == 12 and len(b.holding_isin) == 12:
        key_a = ENTITY_CROSS_REFERENCES.get(a.holding_isin, f"ISIN:{a.holding_isin}")
        key_b = ENTITY_CROSS_REFERENCES.get(b.holding_isin, f"ISIN:{b.holding_isin}")
        if key_a == key_b:
            return key_a
        # Both have ISINs and they do not match -> definitely distinct
        return None

    # Tier 2: Ticker (if at least one lacks ISIN)
    if a.ticker and b.ticker:
        tkr_a = re.sub(r"\.[A-Za-z0-9]+$", "", a.ticker.strip().upper())
        tkr_b = re.sub(r"\.[A-Za-z0-9]+$", "", b.ticker.strip().upper())
        if tkr_a and tkr_a == tkr_b and tkr_a not in ("-", "--", "N/A"):
            return f"TICKER:{tkr_a}"

    # Tier 3: Normalized Name
    norm_a = normalize_constituent_name(a.name)
    norm_b = normalize_constituent_name(b.name)
    if len(norm_a) >= 3 and norm_a == norm_b:
        return f"NAME:{norm_a}"

    return None


def build_canonical_key_resolver(
    holdings: Iterable[ConstituentHolding],
) -> Callable[[ConstituentHolding], str]:
    """Build a resolver that maps constituent holdings to canonical keys,
    resolving cross-tier matches (e.g. aligning items with only Ticker to items with ISIN).
    """
    ticker_to_keys: Dict[str, Set[str]] = {}
    name_to_keys: Dict[str, Set[str]] = {}

    items = list(holdings)

    # Phase 1: Index Tier 1 items (ISIN / ENTITY_CROSS_REFERENCES)
    for h in items:
        if h.holding_isin and len(h.holding_isin) == 12:
            key = ENTITY_CROSS_REFERENCES.get(h.holding_isin, f"ISIN:{h.holding_isin}")
            if h.ticker:
                tkr = re.sub(r"\.[A-Za-z0-9]+$", "", h.ticker.strip().upper())
                if tkr and tkr not in ("-", "--", "N/A"):
                    ticker_to_keys.setdefault(tkr, set()).add(key)
            norm_name = normalize_constituent_name(h.name)
            if len(norm_name) >= 3:
                name_to_keys.setdefault(norm_name, set()).add(key)

    # Phase 2: Index Tier 2 items (no ISIN, but has Ticker)
    for h in items:
        if not (h.holding_isin and len(h.holding_isin) == 12) and h.ticker:
            tkr = re.sub(r"\.[A-Za-z0-9]+$", "", h.ticker.strip().upper())
            if tkr and tkr not in ("-", "--", "N/A"):
                if tkr in ticker_to_keys and len(ticker_to_keys[tkr]) == 1:
                    key = next(iter(ticker_to_keys[tkr]))
                else:
                    key = f"TICKER:{tkr}"
                norm_name = normalize_constituent_name(h.name)
                if len(norm_name) >= 3:
                    name_to_keys.setdefault(norm_name, set()).add(key)

    def resolver(h: ConstituentHolding) -> str:
        # Tier 1: ISIN
        if h.holding_isin and len(h.holding_isin) == 12:
            return ENTITY_CROSS_REFERENCES.get(h.holding_isin, f"ISIN:{h.holding_isin}")

        # Tier 2: Ticker
        if h.ticker:
            tkr = re.sub(r"\.[A-Za-z0-9]+$", "", h.ticker.strip().upper())
            if tkr and tkr not in ("-", "--", "N/A"):
                if tkr in ticker_to_keys and len(ticker_to_keys[tkr]) == 1:
                    return next(iter(ticker_to_keys[tkr]))
                return f"TICKER:{tkr}"

        # Tier 3: Normalized Name
        norm_name = normalize_constituent_name(h.name)
        if len(norm_name) >= 3:
            if norm_name in name_to_keys and len(name_to_keys[norm_name]) == 1:
                return next(iter(name_to_keys[norm_name]))
            return f"NAME:{norm_name}"

        return f"RAW:{h.name.strip().upper()}"

    return resolver


def calculate_pairwise_overlap(
    fund_a: FundHoldings,
    fund_b: FundHoldings,
) -> OverlapPairResult:
    """Calculate pairwise overlap between two funds: sum(min(w_A, w_B))."""
    # Self-overlap returns fund's own equity coverage
    if fund_a.isin == fund_b.isin:
        score = fund_a.equity_weight
        # Top holdings contributing to coverage
        sorted_h = sorted(
            [h for h in fund_a.holdings if h.asset_class == AssetClass.EQUITY.value],
            key=lambda x: x.weight,
            reverse=True,
        )
        top_s = [
            SharedConstituent(
                key=get_constituent_match_key(h),
                name=h.name,
                isin=h.holding_isin,
                ticker=h.ticker,
                weight_a=h.weight,
                weight_b=h.weight,
                min_weight=h.weight,
            )
            for h in sorted_h[:10]
        ]
        return OverlapPairResult(
            fund_a_isin=fund_a.isin,
            fund_b_isin=fund_b.isin,
            fund_a_name=fund_a.fund_name,
            fund_b_name=fund_b.fund_name,
            overlap_score=score,
            shared_count=len(sorted_h),
            top_shared=top_s,
            status="EXACT",
        )

    # Build canonical resolver across both funds for cross-tier matching
    resolver = build_canonical_key_resolver(
        list(fund_a.holdings) + list(fund_b.holdings)
    )

    # Group fund B equity holdings by key
    b_map: Dict[str, Decimal] = {}
    b_items: Dict[str, ConstituentHolding] = {}
    for h_b in fund_b.holdings:
        if h_b.asset_class != AssetClass.EQUITY.value or h_b.weight <= ZERO:
            continue
        key_b = resolver(h_b)
        b_map[key_b] = b_map.get(key_b, ZERO) + h_b.weight
        b_items[key_b] = h_b

    # Group fund A equity holdings by key
    a_map: Dict[str, Decimal] = {}
    a_items: Dict[str, ConstituentHolding] = {}
    for h_a in fund_a.holdings:
        if h_a.asset_class != AssetClass.EQUITY.value or h_a.weight <= ZERO:
            continue
        key_a = resolver(h_a)
        a_map[key_a] = a_map.get(key_a, ZERO) + h_a.weight
        a_items[key_a] = h_a

    # Intersect keys
    shared_keys = set(a_map.keys()) & set(b_map.keys())
    shared_list: List[SharedConstituent] = []
    total_overlap = ZERO

    for key in shared_keys:
        w_a = a_map[key]
        w_b = b_map[key]
        min_w = min(w_a, w_b)
        total_overlap += min_w

        repr_a = a_items.get(key)
        repr_b = b_items.get(key)
        repr_item = repr_a if (repr_a and repr_a.holding_isin) else (repr_b or repr_a)
        shared_list.append(
            SharedConstituent(
                key=key,
                name=repr_item.name,
                isin=repr_item.holding_isin or (repr_b.holding_isin if repr_b else None),
                ticker=repr_item.ticker or (repr_b.ticker if repr_b else None),
                weight_a=w_a,
                weight_b=w_b,
                min_weight=min_w,
            )
        )

    shared_list.sort(key=lambda x: x.min_weight, reverse=True)

    status = "EXACT"
    if fund_a.cash_weight > ZERO or fund_b.cash_weight > ZERO:
        status = "REPORTED_ONLY"

    return OverlapPairResult(
        fund_a_isin=fund_a.isin,
        fund_b_isin=fund_b.isin,
        fund_a_name=fund_a.fund_name,
        fund_b_name=fund_b.fund_name,
        overlap_score=total_overlap,
        shared_count=len(shared_list),
        top_shared=shared_list[:10],
        status=status,
    )


def build_overlap_matrix(funds: Sequence[FundHoldings]) -> OverlapMatrix:
    """Build N x N symmetric pairwise overlap matrix."""
    n = len(funds)
    fund_isins = [f.isin for f in funds]
    fund_names = [f.fund_name for f in funds]
    matrix: List[List[Decimal]] = [[ZERO] * n for _ in range(n)]
    pairs: Dict[str, OverlapPairResult] = {}

    for i in range(n):
        for j in range(i, n):
            pair_res = calculate_pairwise_overlap(funds[i], funds[j])
            matrix[i][j] = pair_res.overlap_score
            matrix[j][i] = pair_res.overlap_score
            pair_key = f"{funds[i].isin}_{funds[j].isin}"
            pairs[pair_key] = pair_res
            if i != j:
                rev_key = f"{funds[j].isin}_{funds[i].isin}"
                pairs[rev_key] = OverlapPairResult(
                    fund_a_isin=funds[j].isin,
                    fund_b_isin=funds[i].isin,
                    fund_a_name=funds[j].fund_name,
                    fund_b_name=funds[i].fund_name,
                    overlap_score=pair_res.overlap_score,
                    shared_count=pair_res.shared_count,
                    top_shared=pair_res.top_shared,
                    status=pair_res.status,
                )

    return OverlapMatrix(
        fund_isins=fund_isins,
        fund_names=fund_names,
        matrix=matrix,
        pairs=pairs,
    )


def calculate_consolidated_exposure(
    funds: Sequence[FundHoldings],
    fund_weights: Mapping[str, Decimal],
    direct_holdings: Sequence[ConstituentHolding] = (),
    portfolio_cash_weight: Decimal = ZERO,
    portfolio_total_eur: Optional[Decimal] = None,
) -> Tuple[PortfolioExposureSummary, ConsolidatedBreakdown]:
    """Calculate consolidated Top 25 stock exposures and distributions across portfolio."""
    # Aggregated company records: key -> dict
    agg_companies: Dict[str, Dict[str, Any]] = {}

    # Sector & country breakdown maps
    sector_weights: Dict[str, Decimal] = {}
    country_weights: Dict[str, Decimal] = {}

    # Uncovered ETF holdings weight tracker
    uncovered_etf_weight = ZERO

    # Account for unloaded ETFs (ISINs in fund_weights with no loaded holdings basket)
    loaded_isins = {f.isin for f in funds}
    for isin, w in fund_weights.items():
        if isin not in loaded_isins and w > ZERO:
            uncovered_etf_weight += w

    # Build cross-tier canonical key resolver across all holdings
    all_holdings = [h for f in funds for h in f.holdings] + list(direct_holdings)
    resolver = build_canonical_key_resolver(all_holdings)

    # 1. Process fund baskets
    for fund in funds:
        w_fund = fund_weights.get(fund.isin, ZERO)
        if w_fund <= ZERO:
            continue

        # Track fund uncovered fraction: fund weight * (1 - equity_weight - cash_weight)
        # Note: cash inside fund is tracked as cash
        covered_ratio = fund.equity_weight + fund.cash_weight
        uncovered_ratio = max(ZERO, ONE - covered_ratio)
        uncovered_etf_weight += w_fund * uncovered_ratio

        # Cash inside fund
        portfolio_cash_weight += w_fund * fund.cash_weight

        for item in fund.holdings:
            if item.asset_class != AssetClass.EQUITY.value or item.weight <= ZERO:
                continue

            item_exposure = w_fund * item.weight
            key = resolver(item)

            if key not in agg_companies:
                agg_companies[key] = {
                    "key": key,
                    "name": item.name,
                    "isin": item.holding_isin,
                    "ticker": item.ticker,
                    "sector": item.sector,
                    "country": item.country,
                    "weight": ZERO,
                    "contributions": {},
                }
            else:
                if not agg_companies[key].get("isin") and item.holding_isin:
                    agg_companies[key]["isin"] = item.holding_isin
                if not agg_companies[key].get("ticker") and item.ticker:
                    agg_companies[key]["ticker"] = item.ticker
                if not agg_companies[key].get("sector") and item.sector:
                    agg_companies[key]["sector"] = item.sector
                if not agg_companies[key].get("country") and item.country:
                    agg_companies[key]["country"] = item.country

            agg_companies[key]["weight"] += item_exposure
            agg_companies[key]["contributions"][fund.isin] = (
                agg_companies[key]["contributions"].get(fund.isin, ZERO) + item_exposure
            )

            # Sektör & Ülke
            sec = item.sector or "Bilinmeyen / Sektörsüz"
            cou = item.country or "Bilinmeyen / Ülkesiz"
            sector_weights[sec] = sector_weights.get(sec, ZERO) + item_exposure
            country_weights[cou] = country_weights.get(cou, ZERO) + item_exposure

    # 2. Process direct individual stock holdings if any
    for direct in direct_holdings:
        if direct.asset_class != AssetClass.EQUITY.value or direct.weight <= ZERO:
            continue
        key = resolver(direct)
        if key not in agg_companies:
            agg_companies[key] = {
                "key": key,
                "name": direct.name,
                "isin": direct.holding_isin,
                "ticker": direct.ticker,
                "sector": direct.sector,
                "country": direct.country,
                "weight": ZERO,
                "contributions": {},
            }
        else:
            if not agg_companies[key].get("isin") and direct.holding_isin:
                agg_companies[key]["isin"] = direct.holding_isin
            if not agg_companies[key].get("ticker") and direct.ticker:
                agg_companies[key]["ticker"] = direct.ticker
            if not agg_companies[key].get("sector") and direct.sector:
                agg_companies[key]["sector"] = direct.sector
            if not agg_companies[key].get("country") and direct.country:
                agg_companies[key]["country"] = direct.country
        agg_companies[key]["weight"] += direct.weight
        agg_companies[key]["contributions"]["DIRECT"] = (
            agg_companies[key]["contributions"].get("DIRECT", ZERO) + direct.weight
        )

        sec = direct.sector or "Bilinmeyen / Sektörsüz"
        cou = direct.country or "Bilinmeyen / Ülkesiz"
        sector_weights[sec] = sector_weights.get(sec, ZERO) + direct.weight
        country_weights[cou] = country_weights.get(cou, ZERO) + direct.weight

    # Sort all companies descending by weight
    sorted_companies = sorted(agg_companies.values(), key=lambda x: x["weight"], reverse=True)

    top_stocks: List[ConsolidatedStockExposure] = []
    cum_weight = ZERO

    top5_weight = ZERO
    top10_weight = ZERO
    top25_weight = ZERO

    for idx, c in enumerate(sorted_companies[:25], start=1):
        cum_weight += c["weight"]
        top25_weight += c["weight"]
        if idx <= 5:
            top5_weight += c["weight"]
        if idx <= 10:
            top10_weight += c["weight"]

        val_eur = None
        if portfolio_total_eur is not None:
            val_eur = (c["weight"] * portfolio_total_eur).quantize(Decimal("0.01"))

        top_stocks.append(
            ConsolidatedStockExposure(
                rank=idx,
                key=c["key"],
                name=c["name"],
                isin=c["isin"],
                ticker=c["ticker"],
                sector=c["sector"],
                country=c["country"],
                portfolio_weight=c["weight"],
                valuation_eur=val_eur,
                cumulative_weight=cum_weight,
                contributions=c["contributions"],
            )
        )

    # Remaining companies > 25
    other_stocks_weight = sum((c["weight"] for c in sorted_companies[25:]), ZERO)

    # Reconciled identity
    total_reconciled = top25_weight + other_stocks_weight + uncovered_etf_weight + portfolio_cash_weight
    is_fully_reconciled = abs(total_reconciled - ONE) <= EPSILON

    # Concentration: Herfindahl-Hirschman Index (HHI)
    # HHI = sum((weight * 100)^2) across all individual companies
    hhi = sum(((c["weight"] * HUNDRED) ** 2 for c in sorted_companies), ZERO).quantize(Decimal("0.1"))

    # Staleness warnings
    staleness_warnings: List[str] = []
    for f in funds:
        if f.is_stale:
            staleness_warnings.append(
                f"⚠️ UYARI: {f.isin} ({f.fund_name}) sepeti {f.age_days} günlük (45 günden eski, as_of_date: {f.as_of_date})."
            )

    summary = PortfolioExposureSummary(
        top_stocks=top_stocks,
        top5_weight=top5_weight,
        top10_weight=top10_weight,
        top25_weight=top25_weight,
        other_stocks_weight=other_stocks_weight,
        uncovered_etf_weight=uncovered_etf_weight,
        cash_weight=portfolio_cash_weight,
        total_reconciled_weight=total_reconciled,
        hhi=hhi,
        portfolio_total_eur=portfolio_total_eur,
        is_fully_reconciled=is_fully_reconciled,
        staleness_warnings=staleness_warnings,
    )

    # Breakdown building
    def _build_breakdown_items(d: Dict[str, Decimal]) -> List[BreakdownItem]:
        sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=True)
        items: List[BreakdownItem] = []
        for name, w in sorted_items:
            v_eur = None
            if portfolio_total_eur is not None:
                v_eur = (w * portfolio_total_eur).quantize(Decimal("0.01"))
            items.append(BreakdownItem(name=name, weight=w, valuation_eur=v_eur))
        return items

    breakdown = ConsolidatedBreakdown(
        sectors=_build_breakdown_items(sector_weights),
        countries=_build_breakdown_items(country_weights),
    )

    return summary, breakdown


# =============================================================================
# Database Retrieval & Pipeline Helpers
# =============================================================================

def load_fund_holdings_from_db(
    db: DatabaseManager,
    isin: str,
) -> Optional[FundHoldings]:
    """Load latest fund holdings basket from holdings_sets and holding_items."""
    conn = db.get_connection()
    try:
        s_row = conn.execute(
            """
            SELECT * FROM holdings_sets
            WHERE isin = ?
            ORDER BY as_of_date DESC, created_at DESC
            LIMIT 1
            """,
            (isin,),
        ).fetchone()

        if not s_row:
            return None

        as_of = datetime.strptime(s_row["as_of_date"], "%Y-%m-%d").date()
        is_stale, age_days = check_staleness(as_of)

        # Lookup fund display name from instruments or listings
        inst_row = conn.execute("SELECT name FROM instruments WHERE isin = ?", (isin,)).fetchone()
        fund_name = inst_row["name"] if inst_row else isin

        items_cur = conn.execute(
            """
            SELECT * FROM holding_items
            WHERE set_id = ?
            ORDER BY item_order ASC
            """,
            (s_row["set_id"],),
        )

        holdings: List[ConstituentHolding] = []
        total_w = ZERO
        eq_w = ZERO
        cash_w = ZERO
        deriv_w = ZERO

        for r in items_cur:
            w = Decimal(str(r["weight_pct"]))
            total_w += w
            a_class = r["asset_class"] or AssetClass.EQUITY.value
            if a_class == AssetClass.EQUITY.value:
                eq_w += w
            elif a_class == AssetClass.CASH.value:
                cash_w += w
            elif a_class == AssetClass.DERIVATIVE.value:
                deriv_w += w

            holdings.append(
                ConstituentHolding(
                    holding_isin=r["constituent_isin"],
                    ticker=r["constituent_ticker"],
                    name=r["constituent_name"],
                    weight=w,
                    country=r["country"],
                    sector=r["sector"],
                    asset_class=a_class,
                )
            )

        return FundHoldings(
            isin=isin,
            fund_name=fund_name,
            as_of_date=as_of,
            total_weight=total_w,
            equity_weight=eq_w,
            cash_weight=cash_w,
            derivative_weight=deriv_w,
            holdings=holdings,
            is_stale=is_stale,
            age_days=age_days,
        )
    finally:
        conn.close()


def load_all_active_holdings(
    db: DatabaseManager,
    isins: Optional[Sequence[str]] = None,
) -> Dict[str, FundHoldings]:
    """Load latest fund holdings for all requested ISINs or all registered in holdings_sets."""
    conn = db.get_connection()
    try:
        if isins is None:
            cur = conn.execute("SELECT DISTINCT isin FROM holdings_sets")
            target_isins = [r["isin"] for r in cur]
        else:
            target_isins = list(isins)
    finally:
        conn.close()

    result: Dict[str, FundHoldings] = {}
    for isin in target_isins:
        h = load_fund_holdings_from_db(db, isin)
        if h is not None:
            result[isin] = h
    return result


def get_portfolio_weights(
    db: DatabaseManager,
    use_targets: bool = False,
) -> Tuple[Dict[str, Decimal], Decimal, Optional[Decimal]]:
    """Return portfolio ETF weights dict, cash weight, and total portfolio valuation EUR.

    Order of precedence:
    1. If not use_targets: try reading latest_run(db).
    2. If no latest run or use_targets: read config/portfoy.json target weights.
    3. If targets empty: equal weights among config ETFs.
    """
    total_val_eur: Optional[Decimal] = None
    cash_weight = ZERO

    if not use_targets:
        try:
            from masa.pipeline import latest_run
            run = latest_run(db)
            if run and run.positions and run.total() > ZERO:
                total_val_eur = run.total()
                cash_weight = run.cash / total_val_eur
                weights: Dict[str, Decimal] = {}
                for isin, pos in run.positions.items():
                    weights[isin] = pos.broker_value / total_val_eur
                return weights, cash_weight, total_val_eur
        except Exception as exc:
            logger.debug(f"Canlı mühürden ağırlık okunamadı: {exc}")

    # Fallback to config/portfoy.json
    config_path = Path("config/portfoy.json")
    if not config_path.exists():
        config_path = Path(db.db_path.parent.parent.parent) / "config/portfoy.json"

    targets: Dict[str, Decimal] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            raw_targets = data.get("hedef_agirliklar") or {}
            if raw_targets:
                targets = {isin: Decimal(str(w)) for isin, w in raw_targets.items()}
            elif data.get("araclar"):
                # Equal weights among configured ETFs
                araclar = list(data["araclar"].keys())
                if araclar:
                    eq = (ONE / Decimal(len(araclar))).quantize(Decimal("0.0001"))
                    targets = {isin: eq for isin in araclar}
        except Exception as exc:
            logger.warning(f"portfoy.json okuma hatası: {exc}")

    if not targets:
        # Default portfolio core ETFs if nothing else configured
        default_isins = ["IE00B3YLTY66", "IE00BKM4GZ66", "IE00BP3QZ825", "IE00BP3QZB59"]
        targets = {isin: Decimal("0.25") for isin in default_isins}

    return targets, cash_weight, total_val_eur


def run_portfolio_overlap_analysis(
    db: DatabaseManager,
    use_targets: bool = False,
    top_n: int = 25,
) -> Tuple[OverlapMatrix, PortfolioExposureSummary, ConsolidatedBreakdown]:
    """Execute end-to-end overlap matrix and portfolio look-through exposure analysis."""
    fund_weights, cash_weight, total_eur = get_portfolio_weights(db, use_targets=use_targets)
    holdings_dict = load_all_active_holdings(db, isins=list(fund_weights.keys()))

    if not holdings_dict:
        holdings_dict = load_all_active_holdings(db)

    funds = list(holdings_dict.values())
    if not funds:
        raise ValueError("Analiz edilecek kayıtlı sepet bulunamadı. Lütfen önce `masa sepet yukle` ile sepet yükleyin.")

    if not fund_weights or all(w <= ZERO for w in fund_weights.values()):
        active_weights = {
            f.isin: ((ONE - cash_weight) / Decimal(len(funds))).quantize(Decimal("0.0001"))
            for f in funds
        }
    else:
        active_weights = dict(fund_weights)

    matrix = build_overlap_matrix(funds)
    summary, breakdown = calculate_consolidated_exposure(
        funds=funds,
        fund_weights=active_weights,
        portfolio_cash_weight=cash_weight,
        portfolio_total_eur=total_eur,
    )

    return matrix, summary, breakdown

