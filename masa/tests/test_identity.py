"""Tests for ISO 6166 ISIN validation, Luhn modulus-10 algorithm, and IdentityRegistry."""

import pytest
from pydantic import BaseModel, ValidationError

from masa.identity import (
    ISIN,
    IdentityRegistry,
    Instrument,
    InstrumentType,
    Issuer,
    Listing,
    calculate_isin_check_digit,
    is_valid_isin,
    validate_isin,
    validate_isin_luhn,
)


class SampleModel(BaseModel):
    isin: ISIN


class TestISINLuhn:
    """Verify Luhn modulus-10 on valid and invalid ISINs."""

    @pytest.mark.parametrize(
        "valid_isin",
        [
            "IE000J80JTL1",  # Scalable / Amundi UCITS
            "US0378331005",  # Apple Inc.
            "IE00BKM4GZ66",  # iShares Core MSCI EM IMI
            "IE00B3YLTY66",  # SPDR ACWI IMI
            "IE00BP3QZ825",  # iShares Momentum
            "IE00BP3QZB59",  # iShares Value
            "DE000A0F5UF5",  # iShares NASDAQ 100
            "FR0000120271",  # TotalEnergies
            "DE000BAY0090",  # Bayer AG (Check digit 0 edge case)
        ],
    )
    def test_valid_isins_pass_validation(self, valid_isin: str) -> None:
        assert validate_isin(valid_isin) == valid_isin
        assert validate_isin_luhn(valid_isin) == valid_isin
        assert is_valid_isin(valid_isin) is True

        # Test Pydantic model integration
        m = SampleModel(isin=valid_isin)
        assert m.isin == valid_isin

    @pytest.mark.parametrize(
        "invalid_isin",
        [
            "US0378331004",  # Wrong check digit (expected 5, got 4)
            "IE00B3YLTY60",  # Wrong check digit (expected 6, got 0)
            "IE000J80JTL2",  # Wrong check digit (expected 1, got 2)
            "US037833100",   # Too short (11 chars)
            "US03783310055", # Too long (13 chars)
            "US037833100A",  # Check digit must be numeric
            "120378331005",  # Country code must be alphabetic
            "US-378331005",  # Hyphen forbidden
            "us0378331005",  # Lowercase rejected in strict ISO mode
            "US 378331005",  # Spaces forbidden
        ],
    )
    def test_invalid_isins_rejected(self, invalid_isin: str) -> None:
        with pytest.raises(ValueError):
            validate_isin(invalid_isin)

        assert is_valid_isin(invalid_isin) is False

        with pytest.raises(ValidationError):
            SampleModel(isin=invalid_isin)

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            validate_isin(None)  # type: ignore

        with pytest.raises(TypeError):
            validate_isin(123456789012)  # type: ignore

    def test_calculate_check_digit_direct(self) -> None:
        # Prefix for Apple: US037833100 -> 5
        assert calculate_isin_check_digit("US037833100") == 5
        # Prefix for IE000J80JTL -> 1
        assert calculate_isin_check_digit("IE000J80JTL") == 1
        # Prefix for Bayer: DE000BAY009 -> 0
        assert calculate_isin_check_digit("DE000BAY009") == 0


class TestIdentityRegistry:
    """Verify in-memory identity registry operations."""

    def test_registry_lifecycle(self) -> None:
        registry = IdentityRegistry()

        issuer = Issuer(
            issuer_id="iss_blackrock",
            name="BlackRock Asset Management Ireland Ltd",
            country="IE",
        )
        registry.register_issuer(issuer)
        assert registry.get_issuer("iss_blackrock") == issuer

        instrument = Instrument(
            instrument_id="inst_em_imi",
            isin="IE00BKM4GZ66",
            name="iShares Core MSCI EM IMI UCITS ETF USD Acc",
            instrument_type=InstrumentType.ETF,
            issuer_id="iss_blackrock",
            is_ucits=True,
            base_currency="USD",
        )
        registry.register_instrument(instrument)
        assert registry.get_instrument("inst_em_imi") == instrument
        assert registry.get_instrument_by_isin("IE00BKM4GZ66") == instrument

        listing = Listing(
            listing_id="list_xetr_is3n_eur",
            instrument_id="inst_em_imi",
            mic="XETR",
            ticker="IS3N",
            currency="EUR",
            is_primary=True,
        )
        registry.register_listing(listing)
        assert registry.get_listing("list_xetr_is3n_eur") == listing
        assert registry.find_listing("XETR", "IS3N") == listing
        assert registry.get_listings_for_instrument("inst_em_imi") == [listing]

    def test_unregistered_references_raise_error(self) -> None:
        registry = IdentityRegistry()

        instrument = Instrument(
            instrument_id="inst_orphaned",
            isin="IE00BKM4GZ66",
            name="Orphaned ETF",
            instrument_type=InstrumentType.ETF,
            issuer_id="iss_nonexistent",
            base_currency="EUR",
        )
        with pytest.raises(ValueError, match="issuer iss_nonexistent not registered"):
            registry.register_instrument(instrument)

        listing = Listing(
            listing_id="list_orphaned",
            instrument_id="inst_nonexistent",
            mic="XETR",
            ticker="TEST",
            currency="EUR",
        )
        with pytest.raises(ValueError, match="instrument inst_nonexistent not registered"):
            registry.register_listing(listing)
