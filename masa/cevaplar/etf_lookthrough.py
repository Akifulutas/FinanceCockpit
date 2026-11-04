"""ETF economic look-through and overlap engine.

Implements SPEC-PROMPT-LOOKTHROUGH-001 v1.0.0 (2026-10-30).
Python >=3.11; dependencies: pydantic>=2.6 and jsonschema>=4.18.

Important specification tensions (resolved without manufacturing exposures):
* Input JSON Schema says holding weights >=0, while section 6 explicitly requires
  signed derivative/hedge components. The Pydantic input validator accepts weights
  in [-1, 1] as an explicitly documented extension; their NET sum is used.
* Signed weights can yield an overlap sum outside [0,1]; the raw literal
  formula value is retained and the contract-bound score is explicitly flagged.
* The top-N / minimum-bps filters cannot delete reported issuers and also satisfy
  the acceptance criterion's exact accounting identity. Filtered issuers are
  therefore accumulated into one explicitly labelled reporting aggregate.
* Synthetic ETF catalog holdings may be SUBSTITUTE COLLATERAL, not index exposure.
  In the absence of an explicit economic-index-holdings field, 100% of each such
  ETF is UNCOVERED_ETF_HOLDINGS for economic look-through. Synthetic pair overlaps
  are marked UNDETERMINED (the mandatory numeric score is a non-inferential zero).
* Currencies, listing venues, and custodians are not fields in the supplied input
  schema. ADR/GDR wrapper risk is preserved as a typed security and explanatory
  warning; specific unprovided venue/currency/custodian facts are never guessed.

No API calls, network accesses, broker operations, or external state mutations.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from itertools import combinations
import json
import math
from pathlib import Path
import re
import sys
from typing import Annotated, Any, TypeAlias

from jsonschema import Draft7Validator
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
TEN_THOUSAND = Decimal("10000")
CENT = Decimal("0.01")
COVERAGE_TOLERANCE = Decimal("0.0001")  # 1 basis point of ETF NAV
WEIGHT_WARNING_TOLERANCE = Decimal("0.001")  # displayed weight rounding
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
UNKNOWN = "UNKNOWN"
UNCOVERED = "UNCOVERED_ETF_HOLDINGS"
CASH = "CASH"
OTHER = "OTHER_REPORTED_COMPANIES"


class LookthroughError(ValueError):
    """Invalid input data, ambiguous security identity, or unreconcilable output."""


def _decimal_number(value: Any) -> Decimal:
    """Accept only JSON numeric values; do not coerce strings or booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("expected JSON number, not string, bool or null")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal number") from exc
    if not result.is_finite():
        raise ValueError("nonfinite numeric values are forbidden")
    return result


Number: TypeAlias = Annotated[Decimal, BeforeValidator(_decimal_number)]
Nonnegative: TypeAlias = Annotated[Number, Field(ge=0)]
Proportion: TypeAlias = Annotated[Number, Field(ge=0, le=1)]
SignedWeight: TypeAlias = Annotated[Number, Field(ge=-1, le=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class InstrumentType(str, Enum):
    ETF = "ETF"
    EQUITY = "EQUITY"


class ReplicationMethod(str, Enum):
    PHYSICAL_FULL = "PHYSICAL_FULL"
    PHYSICAL_OPTIMIZED = "PHYSICAL_OPTIMIZED"
    SYNTHETIC = "SYNTHETIC"
    NOT_APPLICABLE = "N/A"


class SecurityType(str, Enum):
    ORDINARY = "ORDINARY"
    ADR = "ADR"
    GDR = "GDR"
    PREFERRED = "PREFERRED"


class DenominatorMode(str, Enum):
    TOTAL_PORTFOLIO_INCLUDING_CASH = "TOTAL_PORTFOLIO_INCLUDING_CASH"
    INVESTED_EQUITY_ONLY = "INVESTED_EQUITY_ONLY"


class Position(StrictModel):
    instrument_id: str = Field(min_length=1)
    isin: str = Field(pattern=ISIN_PATTERN.pattern)
    ticker: str
    instrument_type: InstrumentType
    name: str = Field(min_length=1)
    valuation_eur: Nonnegative
    weight_in_portfolio: Proportion


class PortfolioSnapshot(StrictModel):
    snapshot_id: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    cash_balance_eur: Nonnegative
    total_equity_value_eur: Nonnegative
    total_portfolio_value_eur: Nonnegative
    positions: list[Position]

    @model_validator(mode="after")
    def reconcile_positions(self) -> "PortfolioSnapshot":
        if self.base_currency != "EUR":
            raise ValueError("amounts are labelled EUR; base_currency must be EUR")
        position_ids = [p.instrument_id for p in self.positions]
        if len(set(position_ids)) != len(position_ids):
            raise ValueError("position instrument_id values must be unique")
        pos_sum = sum((p.valuation_eur for p in self.positions), ZERO)
        if abs(pos_sum - self.total_equity_value_eur) > CENT:
            raise ValueError("position valuations do not reconcile to total_equity_value_eur within EUR 0.01")
        if abs(self.total_equity_value_eur + self.cash_balance_eur - self.total_portfolio_value_eur) > CENT:
            raise ValueError("equity plus cash does not reconcile to total_portfolio_value_eur within EUR 0.01")
        return self


class ETFHolding(StrictModel):
    # In the source schema, holding ISIN is an arbitrary string (unlike Position).
    isin: str
    ticker: str
    company_name: str = Field(min_length=1)
    weight: SignedWeight  # section 6 negative-weight exception to the JSON schema
    country: str | None = None
    sector: str | None = None
    security_type: SecurityType | None = None


class ETFHoldings(StrictModel):
    as_of_date: date
    replication_method: ReplicationMethod
    reported_coverage_ratio: Proportion
    is_full_basket: bool
    holdings: list[ETFHolding]


class CrossReference(StrictModel):
    parent_issuer_id: str = Field(min_length=1)
    parent_company_name: str = Field(min_length=1)
    ordinary_isin: str = Field(pattern=ISIN_PATTERN.pattern)
    adr_ratio: str | None = None
    domicile: str = Field(min_length=1)


class CalculationSettings(StrictModel):
    denominator_mode: DenominatorMode
    minimum_reporting_weight_bps: int = Field(default=5, ge=0)
    top_n_companies_limit: int = Field(default=50, ge=0)


class LookthroughInputPayload(StrictModel):
    portfolio_snapshot: PortfolioSnapshot
    etf_holdings_catalog: dict[str, ETFHoldings]
    entity_cross_reference: dict[str, CrossReference] = Field(default_factory=dict)
    calculation_settings: CalculationSettings

    @model_validator(mode="after")
    def check_catalog_and_references(self) -> "LookthroughInputPayload":
        positions = {p.instrument_id: p for p in self.portfolio_snapshot.positions}
        for key in self.etf_holdings_catalog:
            if key not in positions or positions[key].instrument_type != InstrumentType.ETF:
                raise ValueError(f"catalog entry {key!r} does not identify a held ETF")
        for security_isin in self.entity_cross_reference:
            if not ISIN_PATTERN.fullmatch(security_isin):
                raise ValueError(f"invalid cross-reference ISIN: {security_isin!r}")
        return self


class SourceBreakdown(StrictModel):
    source_instrument_id: str
    source_ticker: str
    contribution_eur: float
    weight_in_source_fund: float
    security_isin: str | None = None
    security_ticker: str | None = None
    security_type: str | None = None
    adr_ratio: str | None = None
    wrapper_risk: str | None = None


class ConsolidatedCompany(StrictModel):
    rank: int = Field(ge=1)
    issuer_id: str
    company_name: str
    primary_country: str = UNKNOWN
    primary_sector: str = UNKNOWN
    direct_holding_eur: float
    etf_derived_eur: float
    total_exposure_eur: float
    portfolio_weight_pct: float
    sources_breakdown: list[SourceBreakdown]
    is_reporting_aggregate: bool = False


class FundUncovered(StrictModel):
    instrument_id: str
    ticker: str
    fund_uncovered_ratio: float
    uncovered_value_eur: float


class UncoveredExposure(StrictModel):
    total_uncovered_eur: float
    total_uncovered_pct: float
    by_fund: list[FundUncovered]


class SharedHolding(StrictModel):
    company_name: str
    weight_in_a: float
    weight_in_b: float
    min_weight: float


class PairwiseFundOverlap(StrictModel):
    fund_a_ticker: str
    fund_b_ticker: str
    overlap_score: float = Field(ge=0, le=1)
    shared_holdings_count: int = Field(ge=0)
    top_shared_holdings: list[SharedHolding]
    overlap_status: str  # EXACT, REPORTED_COMPONENTS_ONLY, SIGNED_SCORE_BOUNDED, UNDETERMINED
    raw_signed_overlap_score: float | None = None
    fund_a_instrument_id: str
    fund_b_instrument_id: str


class SectorBreakdown(StrictModel):
    sector: str
    total_value_eur: float
    weight_pct: float


class GeographicBreakdown(StrictModel):
    country: str
    total_value_eur: float
    weight_pct: float


class ConcentrationMetrics(StrictModel):
    top_5_weight_pct: float
    top_10_weight_pct: float
    herfindahl_hirschman_index: float


class ResultMetadata(StrictModel):
    snapshot_id: str
    execution_timestamp: AwareDatetime
    denominator_mode: DenominatorMode
    total_valuation_eur: float
    total_uncovered_weight_pct: float


class LookthroughResultPayload(StrictModel):
    metadata: ResultMetadata
    consolidated_companies: list[ConsolidatedCompany]
    uncovered_exposure: UncoveredExposure
    pairwise_fund_overlap: list[PairwiseFundOverlap]
    sector_breakdown: list[SectorBreakdown]
    geographic_breakdown: list[GeographicBreakdown]
    concentration_metrics: ConcentrationMetrics
    synthesis_notes: list[str]


# Embedded, UNMODIFIED Draft-07 output schema from source section 5.
OUTPUT_JSON_SCHEMA: dict[str, Any] = json.loads(r'''
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LookthroughResultPayload",
  "type": "object",
  "required": [
    "metadata",
    "consolidated_companies",
    "uncovered_exposure",
    "pairwise_fund_overlap",
    "sector_breakdown",
    "geographic_breakdown",
    "concentration_metrics",
    "synthesis_notes"
  ],
  "properties": {
    "metadata": {
      "type": "object",
      "required": ["snapshot_id", "execution_timestamp", "denominator_mode", "total_valuation_eur", "total_uncovered_weight_pct"],
      "properties": {
        "snapshot_id": {"type": "string"},
        "execution_timestamp": {"type": "string", "format": "date-time"},
        "denominator_mode": {"type": "string", "enum": ["TOTAL_PORTFOLIO_INCLUDING_CASH", "INVESTED_EQUITY_ONLY"]},
        "total_valuation_eur": {"type": "number"},
        "total_uncovered_weight_pct": {"type": "number"}
      }
    },
    "consolidated_companies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["rank", "issuer_id", "company_name", "total_exposure_eur", "portfolio_weight_pct", "sources_breakdown"],
        "properties": {
          "rank": {"type": "integer"},
          "issuer_id": {"type": "string"},
          "company_name": {"type": "string"},
          "primary_country": {"type": "string"},
          "primary_sector": {"type": "string"},
          "direct_holding_eur": {"type": "number"},
          "etf_derived_eur": {"type": "number"},
          "total_exposure_eur": {"type": "number"},
          "portfolio_weight_pct": {"type": "number"},
          "sources_breakdown": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["source_instrument_id", "source_ticker", "contribution_eur", "weight_in_source_fund"],
              "properties": {
                "source_instrument_id": {"type": "string"},
                "source_ticker": {"type": "string"},
                "contribution_eur": {"type": "number"},
                "weight_in_source_fund": {"type": "number"}
              }
            }
          }
        }
      }
    },
    "uncovered_exposure": {
      "type": "object",
      "required": ["total_uncovered_eur", "total_uncovered_pct", "by_fund"],
      "properties": {
        "total_uncovered_eur": {"type": "number"},
        "total_uncovered_pct": {"type": "number"},
        "by_fund": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["instrument_id", "ticker", "fund_uncovered_ratio", "uncovered_value_eur"],
            "properties": {
              "instrument_id": {"type": "string"},
              "ticker": {"type": "string"},
              "fund_uncovered_ratio": {"type": "number"},
              "uncovered_value_eur": {"type": "number"}
            }
          }
        }
      }
    },
    "pairwise_fund_overlap": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["fund_a_ticker", "fund_b_ticker", "overlap_score", "shared_holdings_count", "top_shared_holdings"],
        "properties": {
          "fund_a_ticker": {"type": "string"},
          "fund_b_ticker": {"type": "string"},
          "overlap_score": {"type": "number", "minimum": 0, "maximum": 1},
          "shared_holdings_count": {"type": "integer"},
          "top_shared_holdings": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "company_name": {"type": "string"},
                "weight_in_a": {"type": "number"},
                "weight_in_b": {"type": "number"},
                "min_weight": {"type": "number"}
              }
            }
          }
        }
      }
    },
    "sector_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["sector", "total_value_eur", "weight_pct"],
        "properties": {
          "sector": {"type": "string"},
          "total_value_eur": {"type": "number"},
          "weight_pct": {"type": "number"}
        }
      }
    },
    "geographic_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["country", "total_value_eur", "weight_pct"],
        "properties": {
          "country": {"type": "string"},
          "total_value_eur": {"type": "number"},
          "weight_pct": {"type": "number"}
        }
      }
    },
    "concentration_metrics": {
      "type": "object",
      "required": ["top_5_weight_pct", "top_10_weight_pct", "herfindahl_hirschman_index"],
      "properties": {
        "top_5_weight_pct": {"type": "number"},
        "top_10_weight_pct": {"type": "number"},
        "herfindahl_hirschman_index": {"type": "number"}
      }
    },
    "synthesis_notes": {
      "type": "array",
      "items": {"type": "string"}
    }
  }
}
''')
Draft7Validator.check_schema(OUTPUT_JSON_SCHEMA)
_OUTPUT_VALIDATOR = Draft7Validator(OUTPUT_JSON_SCHEMA,
                                   format_checker=Draft7Validator.FORMAT_CHECKER)


@dataclass(frozen=True)
class _IssuerIdentity:
    issuer_id: str
    company_name: str
    domicile: str | None = None


# These pairs, not an open-ended ticker/name guesser, are specified in section 4.4.
_BUILTIN_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ALPHABET_INC", "Alphabet Inc.", ("US02079K3059", "US02079K1079")),
    ("TSMC", "TSMC",
     ("US8740391003", "TW0002330008")),
)


class _IdentityResolver:
    def __init__(self, refs: dict[str, CrossReference]):
        self.known: dict[str, _IssuerIdentity] = {}
        self._id_owners: dict[str, _IssuerIdentity] = {}
        self.refs = refs
        for default_id, default_name, members in _BUILTIN_GROUPS:
            overrides = [refs[isin] for isin in members if isin in refs]
            if overrides:
                if len({(r.parent_issuer_id, r.parent_company_name, r.domicile)
                        for r in overrides}) != 1:
                    raise LookthroughError(f"conflicting reference identities for {members}")
                r = overrides[0]
                identity = _IssuerIdentity(r.parent_issuer_id,
                                           r.parent_company_name, r.domicile)
            else:
                identity = _IssuerIdentity(default_id, default_name)
            for isin in members:
                self._put(isin, identity)

        # Cross refs map ADR/GDR -> parent, AND parent ordinary ISIN -> issuer.
        for isin, ref in refs.items():
            identity = _IssuerIdentity(ref.parent_issuer_id,
                                       ref.parent_company_name, ref.domicile)
            self._put(isin, identity)
            self._put(ref.ordinary_isin, identity)

    def _put(self, isin: str, identity: _IssuerIdentity) -> None:
        previous = self.known.get(isin)
        if previous is not None and previous != identity:
            raise LookthroughError(f"conflicting issuer mapping for ISIN {isin}")
        owner = self._id_owners.get(identity.issuer_id)
        if owner is not None and owner != identity:
            raise LookthroughError(
                f"conflicting parent issuer metadata for {identity.issuer_id}")
        self._id_owners[identity.issuer_id] = identity
        self.known[isin] = identity

    def resolve(self, isin: str, name: str, source_key: str) -> _IssuerIdentity:
        if isin in self.known:
            return self.known[isin]
        if ISIN_PATTERN.fullmatch(isin):
            return _IssuerIdentity("ISIN:" + isin, name)
        # A stable internal row identifier, NOT a fabricated ticker or ISIN.
        return _IssuerIdentity("UNRESOLVED:" + source_key, name)


@dataclass(frozen=True)
class _Contribution:
    source_id: str
    source_ticker: str
    security_isin: str
    security_ticker: str
    security_type: SecurityType | None
    amount: Decimal
    source_weight: Decimal
    is_direct: bool
    country: str | None
    sector: str | None
    adr_ratio: str | None = None
    mapped_depositary_receipt: bool = False


@dataclass
class _Issuer:
    identity: _IssuerIdentity
    contributions: list[_Contribution] = field(default_factory=list)
    observed_names: set[str] = field(default_factory=set)

    @property
    def total(self) -> Decimal:
        return sum((x.amount for x in self.contributions), ZERO)

    @property
    def direct(self) -> Decimal:
        return sum((x.amount for x in self.contributions if x.is_direct), ZERO)

    @property
    def etf(self) -> Decimal:
        return self.total - self.direct

    def classification(self, attr: str, notes: list[str]) -> str:
        if attr == "country" and self.identity.domicile:
            return self.identity.domicile
        # Use supplied ETF metadata; for direct positions without sector/country,
        # inherit only labels from another supplied security of the *same issuer*.
        labels: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for source in self.contributions:
            label = getattr(source, attr)
            if label and label.strip():
                labels[label.strip()] += abs(source.amount)
        if not labels:
            return UNKNOWN
        if len(labels) > 1:
            notes.append(
                f"Issuer {self.identity.issuer_id} has conflicting {attr} labels: "
                f"{', '.join(sorted(labels))}; primary label is by absolute "
                "observed exposure. Review source classification.")
        return sorted(labels, key=lambda x: (-labels[x], x))[0]


@dataclass
class _FundData:
    position: Position
    coverage: Decimal
    issuer_weights: dict[str, Decimal]
    comparable: bool
    full: bool
    has_negative: bool


def _flt(value: Decimal | float | int) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        raise LookthroughError("computed value exceeds representable finite JSON number")
    return converted


def _pct(amount: Decimal, denominator: Decimal) -> float:
    return _flt(amount / denominator * HUNDRED) if denominator else 0.0


def _source_rows(contributions: list[_Contribution]) -> list[SourceBreakdown]:
    rows = []
    for c in sorted(contributions, key=lambda c:
                    (c.source_id, c.security_isin, c.security_ticker,
                     str(c.amount))):
        risk = None
        if (c.security_type in (SecurityType.ADR, SecurityType.GDR) or
            c.mapped_depositary_receipt):
            risk = ("Depositary receipt: underlying issuer exposure is grouped, "
                    "but depositary/custody, listing venue and FX risks remain; "
                    "venue, currency and custodian were not provided.")
        elif c.security_type == SecurityType.PREFERRED:
            risk = "Preferred securities may have different economic/voting rights."
        rows.append(SourceBreakdown(
            source_instrument_id=c.source_id,
            source_ticker=c.source_ticker,
            contribution_eur=_flt(c.amount),
            weight_in_source_fund=_flt(c.source_weight),
            security_isin=c.security_isin or None,
            security_ticker=c.security_ticker,
            security_type=c.security_type.value if c.security_type else None,
            adr_ratio=c.adr_ratio,
            wrapper_risk=risk,
        ))
    return rows


def _make_company(issuer: _Issuer, rank: int, denom: Decimal,
                  country: str, sector: str) -> ConsolidatedCompany:
    return ConsolidatedCompany(
        rank=rank, issuer_id=issuer.identity.issuer_id,
        company_name=issuer.identity.company_name,
        primary_country=country, primary_sector=sector,
        direct_holding_eur=_flt(issuer.direct),
        etf_derived_eur=_flt(issuer.etf),
        total_exposure_eur=_flt(issuer.total),
        portfolio_weight_pct=_pct(issuer.total, denom),
        sources_breakdown=_source_rows(issuer.contributions),
    )


def _check_totals(companies: list[ConsolidatedCompany],
                  result: LookthroughResultPayload, expected: Decimal,
                  cash: Decimal, mode: DenominatorMode) -> None:
    # Exact Decimal accounting is checked independently in compute_lookthrough.
    displayed = sum((Decimal(str(x.total_exposure_eur)) for x in companies), ZERO)
    displayed += Decimal(str(result.uncovered_exposure.total_uncovered_eur))
    if mode == DenominatorMode.TOTAL_PORTFOLIO_INCLUDING_CASH:
        displayed += cash
    if abs(displayed - expected) > CENT:
        raise LookthroughError(
            f"serialized output failed EUR 0.01 reconciliation: "
            f"reported={displayed}, target={expected}")


def _compute_overlap(a: _FundData, b: _FundData,
                     names: dict[str, str]) -> PairwiseFundOverlap:
    common_args = {"fund_a_ticker": a.position.ticker,
                   "fund_b_ticker": b.position.ticker,
                   "fund_a_instrument_id": a.position.instrument_id,
                   "fund_b_instrument_id": b.position.instrument_id}
    if not a.comparable or not b.comparable:
        # The source contract requires a number. Explicit UNDETERMINED status
        # prevents the numeric zero from being misinterpreted as no overlap.
        return PairwiseFundOverlap(**common_args, overlap_score=0.0,
                                   shared_holdings_count=0,
                                   top_shared_holdings=[],
                                   overlap_status="UNDETERMINED")

    # Apply the specification's literal sum(min(w_a, w_b)) at issuer level,
    # including signed components. Section 6 permits negative weights, even
    # though the output schema bounds overlap_score to [0, 1]. Preserve the
    # signed RAW formula when it falls outside the schema's numeric bounds.
    shared: list[tuple[str, Decimal, Decimal, Decimal]] = []
    for issuer_id in a.issuer_weights.keys() & b.issuer_weights.keys():
        wa = a.issuer_weights[issuer_id]
        wb = b.issuer_weights[issuer_id]
        overlap = min(wa, wb)
        if overlap != 0:
            shared.append((issuer_id, wa, wb, overlap))
    shared.sort(key=lambda x: (-x[3], x[0]))
    raw = sum((entry[3] for entry in shared), ZERO)
    bounded = min(ONE, max(ZERO, raw))
    did_bound = bounded != raw
    status = (
        "SIGNED_SCORE_BOUNDED" if did_bound else
        "EXACT" if a.full and b.full and not a.has_negative and not b.has_negative else
        "REPORTED_COMPONENTS_ONLY"
    )
    return PairwiseFundOverlap(
        **common_args, overlap_score=_flt(bounded),
        raw_signed_overlap_score=_flt(raw) if did_bound else None,
        shared_holdings_count=len(shared),
        overlap_status=status,
        top_shared_holdings=[SharedHolding(
            company_name=names[issuer_id], weight_in_a=_flt(wa),
            weight_in_b=_flt(wb), min_weight=_flt(minimum))
            for issuer_id, wa, wb, minimum in shared[:10]],
    )


def compute_lookthrough(payload: LookthroughInputPayload | dict[str, Any]) -> LookthroughResultPayload:
    """Compute read-only economic exposures from validated input.

    Returns a typed model, never places broker orders, never fetches prices.
    All currency valuations are supplied EUR amounts. All arithmetic uses Decimal.
    """
    if not isinstance(payload, LookthroughInputPayload):
        payload = LookthroughInputPayload.model_validate(payload)
    snapshot = payload.portfolio_snapshot
    settings = payload.calculation_settings
    denominator = (snapshot.total_equity_value_eur + snapshot.cash_balance_eur
                   if settings.denominator_mode == DenominatorMode.TOTAL_PORTFOLIO_INCLUDING_CASH
                   else snapshot.total_equity_value_eur)
    if denominator == 0 and snapshot.total_portfolio_value_eur != 0:
        # CASH-only portfolios are mathematically undefined for invested-only.
        raise LookthroughError("zero invested-equity denominator: percentage weights undefined")

    notes: list[str] = [
        f"Denominator: {settings.denominator_mode.value}; "
        f"value={denominator} EUR. No partial ETF holdings were renormalized.",
        "HHI is computed on individual disclosed issuer exposures in the "
        "0–10,000 percentage-squared convention; cash/uncovered are excluded.",
    ]
    if any(p.valuation_eur > 0 for p in snapshot.positions) and denominator == 0:
        raise LookthroughError("positive invested positions with zero denominator")

    resolver = _IdentityResolver(payload.entity_cross_reference)
    issuers: dict[str, _Issuer] = {}
    funds: list[_FundData] = []
    by_fund: list[FundUncovered] = []
    uncovered_total = ZERO
    net_equity_attribution = ZERO
    snapshot_time = snapshot.retrieved_at

    def add(identity: _IssuerIdentity, contribution: _Contribution,
            observed_name: str) -> None:
        item = issuers.setdefault(identity.issuer_id, _Issuer(identity))
        if (item.identity.issuer_id != identity.issuer_id or
            (item.identity.domicile and identity.domicile and
             item.identity.domicile != identity.domicile)):
            raise LookthroughError(
                f"issuer id {identity.issuer_id!r} has contradictory identity metadata")
        item.contributions.append(contribution)
        item.observed_names.add(observed_name.strip())

    for p in snapshot.positions:
        if snapshot.total_portfolio_value_eur:
            calculated_weight = p.valuation_eur / snapshot.total_portfolio_value_eur
            if abs(calculated_weight - p.weight_in_portfolio) > WEIGHT_WARNING_TOLERANCE:
                notes.append(f"Position {p.instrument_id}: weight_in_portfolio="
                             f"{p.weight_in_portfolio}, valuation-derived="
                             f"{calculated_weight}; exposure uses valuation_eur.")
        if p.instrument_type == InstrumentType.EQUITY:
            identity = resolver.resolve(p.isin, p.name, p.instrument_id)
            add(identity, _Contribution(
                source_id=p.instrument_id, source_ticker=p.ticker,
                security_isin=p.isin, security_ticker=p.ticker,
                security_type=(SecurityType.ADR if p.isin == "US8740391003"
                               else None), amount=p.valuation_eur,
                source_weight=ONE, is_direct=True, country=None, sector=None,
                adr_ratio=(payload.entity_cross_reference[p.isin].adr_ratio
                           if p.isin in payload.entity_cross_reference else None),
                mapped_depositary_receipt=(p.isin in payload.entity_cross_reference),
            ), p.name)
            net_equity_attribution += p.valuation_eur
            continue

        catalog = payload.etf_holdings_catalog.get(p.instrument_id)
        if catalog is None or not catalog.holdings:
            notes.append(f"ETF {p.instrument_id} ({p.ticker}): catalog missing/empty; "
                         f"100% classified as {UNCOVERED}.")
            funds.append(_FundData(p, ZERO, {}, False, False, False))
            by_fund.append(FundUncovered(
                instrument_id=p.instrument_id, ticker=p.ticker,
                fund_uncovered_ratio=1.0, uncovered_value_eur=_flt(p.valuation_eur)))
            uncovered_total += p.valuation_eur
            continue

        measured_coverage = sum((h.weight for h in catalog.holdings), ZERO)
        if not (ZERO <= measured_coverage <= ONE):
            raise LookthroughError(
                f"ETF {p.instrument_id}: net reported coverage {measured_coverage} "
                "is not in [0,1]; cannot produce a nonnegative uncovered share")
        if abs(catalog.reported_coverage_ratio - measured_coverage) > COVERAGE_TOLERANCE:
            raise LookthroughError(
                f"ETF {p.instrument_id}: reported_coverage_ratio="
                f"{catalog.reported_coverage_ratio}, but signed holding sum="
                f"{measured_coverage}; difference > 0.0001")
        if catalog.as_of_date > snapshot_time.date():
            notes.append(f"ETF {p.instrument_id}: holdings as_of_date "
                         f"{catalog.as_of_date} is after snapshot date "
                         f"{snapshot_time.date()}.")
        if (snapshot_time.date() - catalog.as_of_date).days > 90:
            notes.append(f"ETF {p.instrument_id}: holdings dated "
                         f"{catalog.as_of_date} are >90 days older than snapshot.")
        if catalog.is_full_basket and measured_coverage < ONE:
            notes.append(f"ETF {p.instrument_id}: is_full_basket=true but holdings "
                         f"sum to {measured_coverage}; residual remains uncovered.")
        has_negative = any(h.weight < 0 for h in catalog.holdings)
        if has_negative:
            notes.append(f"ETF {p.instrument_id}: signed negative components "
                         "netted at face value in exposure and raw overlap. "
                         "Any out-of-range signed overlap is explicitly "
                         "bounded with its raw formula value retained.")

        if catalog.replication_method == ReplicationMethod.SYNTHETIC:
            notes.append(
                f"ETF {p.instrument_id} ({p.ticker}) is SYNTHETIC: supplied "
                "holdings may be a substitute/collateral basket, NOT the swap "
                "index's economic exposure. Collateral holdings are excluded "
                f"from economic company exposure; 100% is {UNCOVERED}. "
                "Index weights must be supplied separately to resolve exposure.")
            funds.append(_FundData(p, ZERO, {}, False, False, has_negative))
            by_fund.append(FundUncovered(
                instrument_id=p.instrument_id, ticker=p.ticker,
                fund_uncovered_ratio=1.0, uncovered_value_eur=_flt(p.valuation_eur)))
            uncovered_total += p.valuation_eur
            continue

        fund_issuer_weights: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for index, h in enumerate(catalog.holdings):
            identity = resolver.resolve(h.isin, h.company_name,
                                        f"{p.instrument_id}:{index}")
            amount = p.valuation_eur * h.weight
            add(identity, _Contribution(
                source_id=p.instrument_id, source_ticker=p.ticker,
                security_isin=h.isin, security_ticker=h.ticker,
                security_type=(SecurityType.ADR if h.isin == "US8740391003"
                               else h.security_type), amount=amount,
                source_weight=h.weight, is_direct=False,
                country=h.country, sector=h.sector,
                adr_ratio=(payload.entity_cross_reference[h.isin].adr_ratio
                           if h.isin in payload.entity_cross_reference else None),
                mapped_depositary_receipt=(h.isin in payload.entity_cross_reference),
            ), h.company_name)
            fund_issuer_weights[identity.issuer_id] += h.weight
            net_equity_attribution += amount
            if not ISIN_PATTERN.fullmatch(h.isin):
                notes.append(f"ETF {p.instrument_id} holding #{index + 1}: "
                             "missing/invalid ISIN; isolated by source row "
                             "rather than guessing issuer identity.")
            if h.security_type in (SecurityType.ADR, SecurityType.GDR) or h.isin == "US8740391003":
                if h.isin not in resolver.known:
                    notes.append(f"ETF {p.instrument_id} {h.ticker}: "
                                 "ADR/GDR lacks a trusted issuer cross-reference; "
                                 "no speculative consolidation with ordinary shares.")
        missing_ratio = ONE - measured_coverage
        uncovered_value = p.valuation_eur * missing_ratio
        uncovered_total += uncovered_value
        by_fund.append(FundUncovered(
            instrument_id=p.instrument_id, ticker=p.ticker,
            fund_uncovered_ratio=_flt(missing_ratio),
            uncovered_value_eur=_flt(uncovered_value)))
        funds.append(_FundData(
            position=p, coverage=measured_coverage,
            issuer_weights=dict(fund_issuer_weights), comparable=True,
            full=(catalog.is_full_basket and missing_ratio == 0),
            has_negative=has_negative))
        if missing_ratio > 0:
            notes.append(f"ETF {p.instrument_id}: reported coverage="
                         f"{measured_coverage}; uncovered={missing_ratio} "
                         f"(EUR {uncovered_value}); holdings NOT rescaled.")

    # This accounting identity is valid even for signed fund components.
    if abs(net_equity_attribution + uncovered_total -
           snapshot.total_equity_value_eur) > CENT:
        raise LookthroughError("internal holdings + uncovered does not reconcile "
                               "to invested equity within EUR 0.01")

    names = {issuer_id: item.identity.company_name
             for issuer_id, item in issuers.items()}
    overlaps = [_compute_overlap(a, b, names) for a, b in combinations(funds, 2)]
    for pair in overlaps:
        if pair.overlap_status == "UNDETERMINED":
            notes.append(f"Overlap {pair.fund_a_instrument_id} / "
                         f"{pair.fund_b_instrument_id}: UNDETERMINED "
                         "(missing holdings or synthetic collateral). "
                         "Required numeric score 0 is not a claim of no overlap.")
        elif pair.overlap_status == "SIGNED_SCORE_BOUNDED":
            notes.append(f"Overlap {pair.fund_a_instrument_id} / "
                         f"{pair.fund_b_instrument_id}: raw signed sum(min)="
                         f"{pair.raw_signed_overlap_score} is outside [0,1]; "
                         "the schema-required overlap_score is bounded, "
                         "and the unmodified raw result is preserved.")
        elif pair.overlap_status == "REPORTED_COMPONENTS_ONLY":
            notes.append(f"Overlap {pair.fund_a_instrument_id} / "
                         f"{pair.fund_b_instrument_id}: observed shared "
                         "components only; not necessarily total fund overlap.")

    for issuer in issuers.values():
        if issuer.identity.issuer_id == "ALPHABET_INC":
            notes.append("Alphabet Class A (US02079K3059) and Class C "
                         "(US02079K1079) are grouped economically; "
                         "individual class ISINs/tickers and their differing "
                         "voting-right profiles remain distinct in sources_breakdown.")
        if len(issuer.observed_names) > 1:
            notes.append(f"Issuer {issuer.identity.issuer_id}: multiple supplied "
                         f"security names ({'; '.join(sorted(issuer.observed_names))}); "
                         "issuer identity determined by ISIN/xref, not names.")
        if any(c.security_type in (SecurityType.ADR, SecurityType.GDR) or
               c.mapped_depositary_receipt for c in issuer.contributions):
            notes.append(f"Issuer {issuer.identity.issuer_id}: "
                         "ADR/GDR economic exposure consolidated where mapped; "
                         "depository, FX and exchange risks remain and cannot "
                         "be quantified from the available source fields.")

    ordered = sorted(issuers.values(),
                     key=lambda x: (-x.total, x.identity.issuer_id))
    countries: dict[str, str] = {}
    sectors: dict[str, str] = {}
    by_country: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_sector: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for issuer in ordered:
        issuer_id = issuer.identity.issuer_id
        countries[issuer_id] = issuer.classification("country", notes)
        sectors[issuer_id] = issuer.classification("sector", notes)
        by_country[countries[issuer_id]] += issuer.total
        by_sector[sectors[issuer_id]] += issuer.total
    by_country[UNCOVERED] += uncovered_total
    by_sector[UNCOVERED] += uncovered_total
    if settings.denominator_mode == DenominatorMode.TOTAL_PORTFOLIO_INCLUDING_CASH:
        by_country[CASH] += snapshot.cash_balance_eur
        by_sector[CASH] += snapshot.cash_balance_eur

    reporting_cutoff = (denominator *
                        Decimal(settings.minimum_reporting_weight_bps) / TEN_THOUSAND)
    eligible = [x for x in ordered if abs(x.total) >= reporting_cutoff]
    kept_ids = {x.identity.issuer_id
                for x in eligible[:settings.top_n_companies_limit]}
    shown = [x for x in ordered if x.identity.issuer_id in kept_ids]
    hidden = [x for x in ordered if x.identity.issuer_id not in kept_ids]
    consolidated = [
        _make_company(issuer, rank, denominator,
                      countries[issuer.identity.issuer_id],
                      sectors[issuer.identity.issuer_id])
        for rank, issuer in enumerate(shown, 1)
    ]
    if hidden:
        hidden_direct = sum((x.direct for x in hidden), ZERO)
        hidden_etf = sum((x.etf for x in hidden), ZERO)
        hidden_total = hidden_direct + hidden_etf
        consolidated.append(ConsolidatedCompany(
            rank=len(consolidated) + 1,
            issuer_id=OTHER,
            company_name="Other reported companies (accounting aggregate)",
            primary_country="MIXED", primary_sector="MIXED",
            direct_holding_eur=_flt(hidden_direct),
            etf_derived_eur=_flt(hidden_etf),
            total_exposure_eur=_flt(hidden_total),
            portfolio_weight_pct=_pct(hidden_total, denominator),
            sources_breakdown=_source_rows(
                [contribution for x in hidden for contribution in x.contributions]),
            is_reporting_aggregate=True))
        notes.append(f"Reporting filters grouped {len(hidden)} known issuers "
                     f"under {OTHER}, rather than dropping exposures or "
                     "misclassifying them as uncovered. HHI/sector/country "
                     "remain based on all original issuer rows.")
    if not ordered:
        notes.append("No disclosed issuer-level holdings were available.")
    if denominator == 0:
        notes.append("Portfolio denominator is zero; all percentage outputs "
                     "are represented as 0 instead of undefined.")

    def sector_sort(item: tuple[str, Decimal]) -> tuple[Decimal, str]:
        return (-item[1], item[0])

    sector_result = [SectorBreakdown(
        sector=k, total_value_eur=_flt(v), weight_pct=_pct(v, denominator))
        for k, v in sorted(by_sector.items(), key=sector_sort)]
    geography_result = [GeographicBreakdown(
        country=k, total_value_eur=_flt(v), weight_pct=_pct(v, denominator))
        for k, v in sorted(by_country.items(), key=sector_sort)]

    individual_weights = [x.total / denominator for x in ordered] if denominator else []
    top5 = sum((x.total for x in ordered[:5]), ZERO)
    top10 = sum((x.total for x in ordered[:10]), ZERO)
    hhi = sum((w * w for w in individual_weights), ZERO) * TEN_THOUSAND
    if any(x.total < 0 for x in ordered):
        notes.append("Signed net-negative issuer exposures are included in "
                     "accounting and HHI; concentration statistics may not "
                     "behave like a long-only portfolio.")

    result = LookthroughResultPayload(
        metadata=ResultMetadata(
            snapshot_id=snapshot.snapshot_id,
            execution_timestamp=datetime.now(timezone.utc),
            denominator_mode=settings.denominator_mode,
            total_valuation_eur=_flt(denominator),
            total_uncovered_weight_pct=_pct(uncovered_total, denominator)),
        consolidated_companies=consolidated,
        uncovered_exposure=UncoveredExposure(
            total_uncovered_eur=_flt(uncovered_total),
            total_uncovered_pct=_pct(uncovered_total, denominator),
            by_fund=by_fund),
        pairwise_fund_overlap=overlaps,
        sector_breakdown=sector_result,
        geographic_breakdown=geography_result,
        concentration_metrics=ConcentrationMetrics(
            top_5_weight_pct=_pct(top5, denominator),
            top_10_weight_pct=_pct(top10, denominator),
            herfindahl_hirschman_index=_flt(hhi)),
        synthesis_notes=notes,
    )

    # Independent output checks: original Draft 7, cash and invested-only
    # balance sheets, and sector/geographic breakdowns all reconcile.
    expected = denominator
    internal_total = sum((x.total for x in ordered), ZERO) + uncovered_total
    if settings.denominator_mode == DenominatorMode.TOTAL_PORTFOLIO_INCLUDING_CASH:
        internal_total += snapshot.cash_balance_eur
    if abs(internal_total - expected) > CENT:
        raise LookthroughError("internal total allocation fails EUR 0.01 acceptance check")
    for dimension, breakdown in (("sector", by_sector), ("geography", by_country)):
        total = sum(breakdown.values(), ZERO)
        if abs(total - expected) > CENT:
            raise LookthroughError(f"{dimension} values do not reconcile to denominator")
    _check_totals(consolidated, result, expected, snapshot.cash_balance_eur,
                  settings.denominator_mode)
    wire_object = result.model_dump(mode="json")
    errors = sorted(_OUTPUT_VALIDATOR.iter_errors(wire_object),
                    key=lambda x: (str(x.absolute_path), x.message))
    if errors:
        raise LookthroughError("result failed Draft-07 output schema: " +
                               "; ".join(x.message for x in errors))
    # Verify JSON-compatible numbers (rejects NaN, Infinity and overflow).
    json.dumps(wire_object, allow_nan=False)
    return result


def calculate_json(input_text: str) -> str:
    """Strict JSON string in -> schema-checked strict JSON string out."""
    def bad_constant(value: str) -> Any:
        raise LookthroughError(f"non-JSON numeric constant: {value}")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise LookthroughError(f"duplicate JSON key: {key!r}")
            obj[key] = value
        return obj

    raw = json.loads(input_text, parse_float=Decimal, parse_int=int,
                     parse_constant=bad_constant, object_pairs_hook=unique_keys)
    if not isinstance(raw, dict):
        raise LookthroughError("root JSON value must be an object")
    payload = LookthroughInputPayload.model_validate(raw)
    result = compute_lookthrough(payload)
    return json.dumps(result.model_dump(mode="json"),
                      allow_nan=False, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only ETF issuer-level economic look-through engine")
    parser.add_argument("--input", "-i", default="-",
                        help="Input strict JSON file path; '-' means stdin")
    parser.add_argument("--output", "-o", default="-",
                        help="Output strict JSON file path; '-' means stdout")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.input).read_text(encoding="utf-8")
        json_out = calculate_json(text) + "\n"
        if args.output == "-":
            sys.stdout.write(json_out)
        else:
            Path(args.output).write_text(json_out, encoding="utf-8")
        return 0
    except (LookthroughError, ValidationError, ValueError, OSError) as exc:
        print(f"ETF look-through error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
