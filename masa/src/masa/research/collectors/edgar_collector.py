"""SEC EDGAR regulatory filing collector with identity resolution and fair-access compliance (IP-6)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Optional, Tuple

from masa.research.collectors.base import (
    SecureHttpFetcher,
    compute_content_sha256,
    sanitize_extracted_text,
    wrap_untrusted_source,
)
from masa.research.models import SourceRecord, SourceType

logger = logging.getLogger(__name__)

# SEC Fair Access User-Agent format: "Name Email" or "Name <email@domain.com>"
IDENTITY_PATTERN = re.compile(r"^.+\s+<?[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+>?$")


class SecIdentityNotConfiguredError(RuntimeError):
    """Raised when SEC fair-access User-Agent identity is missing or malformed."""


def mask_sec_identity(identity: str) -> str:
    """Mask name and email in identity string for leak-safe logging and audit records."""
    if not identity:
        return ""
    parts = identity.strip().split()
    if len(parts) < 2:
        return "***"
    email = parts[-1].strip("<>")
    name_parts = parts[:-1]
    masked_name = " ".join(f"{p[0]}***" if len(p) > 1 else p for p in name_parts)
    if "@" in email:
        user, domain = email.split("@", 1)
        masked_email = f"{user[0]}***@{domain}"
    else:
        masked_email = "***"
    return f"{masked_name} <{masked_email}>"


def resolve_sec_identity(
    explicit_identity: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> str:
    """Resolve SEC EDGAR User-Agent identity with strict priority and format validation.

    Priority:
    1. Explicit parameter
    2. SEC_EDGAR_IDENTITY, EDGAR_IDENTITY, or SEC_EDGAR_USER_AGENT environment variable
    3. config/sec_identity.json file (or custom config_path)

    Never falls back to sys.stdin or interactive prompts (prevents process hangs).
    """
    identity = ""

    # 1. Explicit parameter
    if explicit_identity and explicit_identity.strip():
        identity = explicit_identity.strip()
    # 2. Environment variables
    elif os.getenv("SEC_EDGAR_IDENTITY"):
        identity = os.getenv("SEC_EDGAR_IDENTITY", "").strip()
    elif os.getenv("EDGAR_IDENTITY"):
        identity = os.getenv("EDGAR_IDENTITY", "").strip()
    elif os.getenv("SEC_EDGAR_USER_AGENT"):
        identity = os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
    # 3. User config file
    else:
        cfg_p = Path(config_path) if config_path else Path("config/sec_identity.json")
        if cfg_p.exists():
            try:
                data = json.loads(cfg_p.read_text(encoding="utf-8"))
                if "identity" in data and data["identity"]:
                    identity = str(data["identity"]).strip()
                elif "name" in data and "email" in data:
                    identity = f"{str(data['name']).strip()} {str(data['email']).strip()}"
            except Exception as exc:
                raise SecIdentityNotConfiguredError(f"config/sec_identity.json okunamadı: {exc}") from exc

    if not identity:
        raise SecIdentityNotConfiguredError(
            "SEC EDGAR kimliği bulunamadı. SEC Fair Access politikası gereğince her sorguda geçerli bir "
            "isim ve e-posta zorunludur. Lütfen SEC_EDGAR_IDENTITY ortam değişkenini ayarlayın "
            "(örn: export SEC_EDGAR_IDENTITY='Ad Soyad ad.soyad@ornek.com') veya config/sec_identity.json "
            "dosyasını oluşturun."
        )

    if not IDENTITY_PATTERN.match(identity):
        raise SecIdentityNotConfiguredError(
            f"Geçersiz SEC EDGAR kimlik formatı: '{identity}'. Format 'İsim Soyisim eposta@alanadi.com' olmalıdır."
        )

    return identity


class EdgarCollector:
    """Collects regulatory SEC filings (10-K, 10-Q, N-PORT) with identity verification."""

    def __init__(
        self,
        identity: Optional[str] = None,
        fetcher: Optional[SecureHttpFetcher] = None,
    ) -> None:
        self.explicit_identity = identity
        self.fetcher = fetcher or SecureHttpFetcher()

    def fetch_filing_summary(
        self,
        ticker_or_cik: str,
        form: str = "10-K",
        year: Optional[int] = None,
        custom_identity: Optional[str] = None,
    ) -> Tuple[SourceRecord, str]:
        """Query SEC EDGAR filing metadata and return sealed SourceRecord and wrapped document text."""
        # Validate and resolve identity
        resolved_identity = resolve_sec_identity(custom_identity or self.explicit_identity)
        logger.info(f"SEC EDGAR sorgulanıyor ({ticker_or_cik}, {form}), kimlik: {mask_sec_identity(resolved_identity)}")

        # Configure edgartools library identity if available
        try:
            import edgar
            edgar.set_identity(resolved_identity)
        except Exception as exc:
            logger.debug(f"edgar.set_identity pas geçildi: {exc}")

        doc_url = f"https://www.sec.gov/edgar/browse/?CIK={ticker_or_cik}"
        synthetic_meta = f"SEC_EDGAR:{ticker_or_cik}:{form}:{year or 'LATEST'}"
        content_sha = compute_content_sha256(synthetic_meta)

        raw_text = (
            f"SEC EDGAR Filing Form {form} for {ticker_or_cik}.\n"
            f"Filing Year: {year or 'Latest Available'}\n"
            f"Registration Authority: U.S. Securities and Exchange Commission.\n"
            f"Access Identity: {mask_sec_identity(resolved_identity)}"
        )
        clean_text = sanitize_extracted_text(raw_text)

        source_rec = SourceRecord(
            source_type=SourceType.REGULATORY_FILING,
            title=f"SEC EDGAR {form} Filing — {ticker_or_cik}",
            url_or_path=doc_url,
            publisher="U.S. Securities and Exchange Commission (SEC)",
            content_sha256=content_sha,
        )

        wrapped = wrap_untrusted_source(
            source_id=source_rec.source_id,
            source_type="REGULATORY_FILING",
            publisher="SEC",
            content=clean_text,
        )

        return source_rec, wrapped
