"""ISO 6166 International Securities Identification Number (ISIN) validator.

Implements strict format checking and the Luhn Modulus-10 check digit algorithm
as defined by the Association of National Numbering Agencies (ANNA) and ISO 6166.
"""

from __future__ import annotations

import re
from typing import Annotated
from pydantic import AfterValidator

# Regex strictly matching:
# - Exactly 2 uppercase ASCII letters (country/special prefix)
# - Exactly 9 uppercase ASCII alphanumeric chars (NSIN)
# - Exactly 1 numeric check digit
ISIN_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
PREFIX_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}$")


def calculate_isin_check_digit(prefix11: str) -> int:
    """Calculate the ISO 6166 Luhn Modulus-10 check digit for an 11-character ISIN prefix.

    Args:
        prefix11: The first 11 characters of an ISIN (2 country letters + 9 NSIN chars).

    Returns:
        Integer check digit in the range [0, 9].

    Raises:
        ValueError: If prefix11 is not exactly 11 valid uppercase alphanumeric characters.
    """
    if not isinstance(prefix11, str):
        raise TypeError(f"Prefix must be a string, got {type(prefix11).__name__}")

    if len(prefix11) != 11:
        raise ValueError(
            f"ISIN prefix must be exactly 11 characters, got {len(prefix11)} ({prefix11!r})"
        )
    if not PREFIX_PATTERN.match(prefix11):
        raise ValueError(
            f"ISIN prefix must match pattern [A-Z]{{2}}[A-Z0-9]{{9}}, got {prefix11!r}"
        )

    # Step 1: Expand letters to 2-digit strings (A=10, ..., Z=35)
    digits: list[int] = []
    for char in prefix11:
        if "0" <= char <= "9":
            digits.append(int(char))
        else:
            val = ord(char) - ord("A") + 10
            digits.append(val // 10)
            digits.append(val % 10)

    # Step 2 & 3: Weighting from right to left with doubling of every second digit
    # In an ISIN, the check digit (position 12) has weight 1.
    # Therefore, moving leftward from the check digit, the rightmost digit of prefix11 has weight 2,
    # the next has weight 1, then 2, then 1, and so forth.
    total_sum = 0
    for offset_from_right, digit in enumerate(reversed(digits)):
        if offset_from_right % 2 == 0:
            product = digit * 2
            total_sum += (product // 10) + (product % 10)
        else:
            total_sum += digit

    # Step 4: Modulo-10 check digit
    return (10 - (total_sum % 10)) % 10


def validate_isin(isin: str) -> str:
    """Validate a 12-character ISIN string against ISO 6166 format and Luhn check digit.

    Args:
        isin: Candidate ISIN string.

    Returns:
        The validated uppercase ISIN string.

    Raises:
        TypeError: If isin is not a string.
        ValueError: If length, characters, or check digit are invalid.
    """
    if not isinstance(isin, str):
        raise TypeError(f"ISIN must be a string, got {type(isin).__name__}")

    clean_isin = isin.strip()
    if len(clean_isin) != 12:
        raise ValueError(
            f"ISIN must be exactly 12 characters, got {len(clean_isin)} ({isin!r})"
        )

    if not ISIN_PATTERN.match(clean_isin):
        raise ValueError(
            f"ISIN {isin!r} does not match ISO 6166 pattern [A-Z]{{2}}[A-Z0-9]{{9}}[0-9]"
        )

    expected_check = calculate_isin_check_digit(clean_isin[:11])
    actual_check = int(clean_isin[11])

    if actual_check != expected_check:
        raise ValueError(
            f"ISIN check digit mismatch for {clean_isin}: got {actual_check}, expected {expected_check}"
        )

    return clean_isin


def is_valid_isin(isin: str) -> bool:
    """Non-raising predicate returning True if isin passes ISO 6166 validation."""
    try:
        validate_isin(isin)
        return True
    except (ValueError, TypeError):
        return False


# Alias for compatibility with tests expecting validate_isin_luhn
validate_isin_luhn = validate_isin

# Annotated Pydantic type for strict declarative schema validation
ISIN = Annotated[str, AfterValidator(validate_isin)]
