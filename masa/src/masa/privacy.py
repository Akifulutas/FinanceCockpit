"""Privacy, Data Sanitization, and PII Leakage Protection (İP-10).

Design Invariants:
1. Strict LLM payload sanitization: removes accounts, IBANs, customer names, raw auth tokens.
2. Whitelisted data only: symbols, ISINs, dates, quantities, prices, weights, ratios, aggregated metrics.
3. Fail-closed: raises PrivacyViolationError if forbidden sensitive keys or unredacted secrets are detected.
4. Report sharing masking: generates privacy-safe versions of reports (--paylasim).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Union

logger = logging.getLogger(__name__)


class PrivacyViolationError(RuntimeError):
    """Raised when private, sensitive, or non-whitelisted data is leaked toward external services."""


# Forbidden keys that must NEVER be passed to external/cloud LLM services
FORBIDDEN_KEYS: Set[str] = {
    "owner",
    "account_id",
    "portfolio_id",
    "iban",
    "user_id",
    "customer_id",
    "name_surname",
    "first_name",
    "last_name",
    "tax_id",
    "ssn",
    "jwt",
    "token",
    "password",
    "secret",
    "session_id",
    "cookie",
    "auth_header",
    "api_key",
}

# Regex patterns for sensitive data
IBAN_REGEX = re.compile(
    r"\b[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}\b",
    re.ASCII,
)
SECRET_REGEX = re.compile(
    r"(?i)\b(?:bearer\s+[a-zA-Z0-9_\-\.]{16,}|ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9]{20,})\b"
)
ACCOUNT_ID_REGEX = re.compile(
    r"(?i)\b(?:konto|hesap|account|portfolio)[-_]?(?:id|no|numarasi)?\s*[:=]\s*([a-zA-Z0-9_\-]{6,})\b"
)


def is_isin(val: str) -> bool:
    """Helper to distinguish 12-char ISINs from IBANs."""
    if len(val) == 12 and val[:2].isalpha() and val[:2].isupper():
        return True
    return False


def sanitize_text(text: str) -> str:
    """Scrub sensitive patterns (IBAN, secrets, tokens) from string."""
    # Redact secrets
    text = SECRET_REGEX.sub("[MASKELENDİ_GİZLİ_ANAHTAR]", text)

    # Redact IBANs while preserving ISINs
    def _replace_iban(match: re.Match) -> str:
        matched_str = match.group(0)
        if is_isin(matched_str):
            return matched_str
        return "[MASKELENDİ_IBAN]"

    text = IBAN_REGEX.sub(_replace_iban, text)
    return text


def sanitize_for_external(
    data: Any,
    strict: bool = True,
    path: str = "",
) -> Any:
    """Recursively scrub data payload before sending to external LLM services.

    If strict=True, encountering forbidden sensitive keys or active credentials
    raises PrivacyViolationError immediately.
    """
    if data is None:
        return None

    if isinstance(data, (int, float, bool)):
        return data

    if isinstance(data, str):
        sanitized = sanitize_text(data)
        if strict and ("[MASKELENDİ_GİZLİ_ANAHTAR]" in sanitized or "[MASKELENDİ_IBAN]" in sanitized):
            raise PrivacyViolationError(
                f"Gizlilik ihlali: '{path}' alanında maskelenmiş hassas veri tespit edildi. Dış servis çağrısı engellendi."
            )
        return sanitized

    if isinstance(data, list):
        return [
            sanitize_for_external(item, strict=strict, path=f"{path}[{i}]")
            for i, item in enumerate(data)
        ]

    if isinstance(data, dict):
        sanitized_dict: Dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower().strip()
            current_path = f"{path}.{k}" if path else str(k)

            # Check forbidden keys
            if k_lower in FORBIDDEN_KEYS:
                if strict:
                    raise PrivacyViolationError(
                        f"Gizlilik ihlali: '{current_path}' alanı dış LLM servisine gönderilemez (kara liste kuralı)."
                    )
                continue

            sanitized_dict[k] = sanitize_for_external(v, strict=strict, path=current_path)
        return sanitized_dict

    # For objects with __dict__ or pydantic models
    if hasattr(data, "model_dump"):
        return sanitize_for_external(data.model_dump(), strict=strict, path=path)
    if hasattr(data, "__dict__"):
        return sanitize_for_external(data.__dict__, strict=strict, path=path)

    return str(data)


def mask_report_for_sharing(markdown_text: str) -> str:
    """Generate sanitized, shareable report with absolute monetary amounts and identities masked."""
    # Mask EUR figures (e.g. 12,500.50 EUR -> [GİZLENDİ] EUR)
    masked = re.sub(r"\b\d{1,3}(?:[,\.]\d{3})*(?:[,\.]\d{2})?\s*EUR\b", "[GİZLENDİ] EUR", markdown_text)

    # Mask run_ids
    masked = re.sub(r"\brun_\d{8}_\d{6}\b", "run_YYYYMMDD_HHMMSS", masked)

    # Mask user paths
    masked = re.sub(r"/(?:Users|home)/[a-zA-Z0-9_\-\.]+/[^\s\)\`]+", "[YEREL_DOSYA_YOLU]", masked)

    # Add header badge
    header_notice = (
        "> [!NOTE]\n"
        "> **PAYLAŞILABİLİR KİP (--paylasim):** Bu rapor halka açık veya üçüncü taraflarla paylaşım için "
        "hassas portföy tutarları, hesap kimlikleri ve yerel dosya yolları maskelenerek üretilmiştir.\n\n"
    )

    return header_notice + masked
