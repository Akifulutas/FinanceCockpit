"""Pydantic v2 domain models for financial instrument identity.

Strictly separates legal entity (Issuer), economic security (Instrument),
and venue execution line (Listing).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from masa.identity.isin import ISIN


class InstrumentType(str, Enum):
    """Categorization of financial instrument."""
    ETF = "ETF"
    EQUITY = "EQUITY"
    ADR = "ADR"
    BOND = "BOND"
    ETC = "ETC"
    MUTUAL_FUND = "MUTUAL_FUND"
    OTHER = "OTHER"


class Issuer(BaseModel):
    """Corporate or fund management legal entity."""
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    issuer_id: str = Field(
        ...,
        description="Deterministic unique identifier (e.g. iss_blackrock_ie)",
        min_length=3,
        max_length=64,
    )
    name: str = Field(..., description="Full legal name of the entity", min_length=1)
    country: str = Field(
        ...,
        description="ISO 3166-1 alpha-2 domicile country code",
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    lei: Optional[str] = Field(
        default=None,
        description="ISO 17442 Legal Entity Identifier (20 chars alphanumeric)",
        min_length=20,
        max_length=20,
        pattern=r"^[A-Z0-9]{20}$",
    )
    is_active: bool = Field(default=True, description="Whether issuer is currently operating")


class Instrument(BaseModel):
    """Economic security or fund share class.

    Invariant: An instrument represents an economic share class, NOT a trading venue.
    UCITS status MUST be explicitly stated and cannot be inferred from ISIN country prefix.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    instrument_id: str = Field(
        ...,
        description="Unique system identifier (e.g. inst_ie00bkm4gz66)",
        min_length=3,
        max_length=64,
    )
    isin: ISIN = Field(
        ...,
        description="ISO 6166 verified 12-character ISIN code",
    )
    name: str = Field(..., description="Standard descriptive name of the security", min_length=1)
    instrument_type: InstrumentType = Field(..., description="Economic instrument class")
    issuer_id: str = Field(..., description="Reference to parent Issuer.issuer_id")
    is_ucits: Optional[bool] = Field(
        default=None,
        description="Explicit flag for UCITS compliance; NEVER infer from ISIN country code",
    )
    domicile: Optional[str] = Field(
        default=None,
        description="ISO 3166-1 alpha-2 domicile country",
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    base_currency: str = Field(
        ...,
        description="ISO 4217 fund/security base currency (e.g. USD, EUR)",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    underlying_asset_class: Optional[str] = Field(
        default=None,
        description="Underlying economic category (e.g. Equity, Fixed Income, Commodity)",
    )
    ter_bps: Optional[int] = Field(
        default=None,
        description="Total Expense Ratio in basis points (e.g. 18 = 0.18%)",
        ge=0,
        le=10000,
    )
    is_active: bool = Field(default=True, description="Whether instrument is actively tracked")


class Listing(BaseModel):
    """Specific exchange venue quote and execution line.

    Invariant: Combines an Instrument with a specific Market Identifier Code (MIC),
    currency, and local exchange ticker.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    listing_id: str = Field(
        ...,
        description="Unique listing identifier (e.g. list_xetr_is3n_eur)",
        min_length=3,
        max_length=64,
    )
    instrument_id: str = Field(..., description="Reference to parent Instrument.instrument_id")
    mic: str = Field(
        ...,
        description="ISO 10383 Market Identifier Code (e.g. XETR, XFRA, XLON, XNAS)",
        min_length=4,
        max_length=4,
        pattern=r"^[A-Z0-9]{4}$",
    )
    ticker: str = Field(
        ...,
        description="Local venue trading symbol (e.g. IS3N, AAPL)",
        min_length=1,
        max_length=16,
    )
    currency: str = Field(
        ...,
        description="ISO 4217 trading/quote currency (e.g. EUR, USD)",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    is_primary: bool = Field(
        default=False,
        description="Whether this listing is the primary reference line for the instrument",
    )
    is_active: bool = Field(default=True, description="Whether listing is currently open/tradable")
