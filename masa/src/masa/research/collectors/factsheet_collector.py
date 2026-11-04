"""Factsheet and issuer documentation collector using Trafilatura (IP-6)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import trafilatura

from masa.research.collectors.base import (
    SecureHttpFetcher,
    compute_content_sha256,
    sanitize_extracted_text,
    validate_research_url,
    wrap_untrusted_source,
)
from masa.research.models import SourceRecord, SourceType

logger = logging.getLogger(__name__)


class FactsheetCollector:
    """Collects and extracts clean document text from issuer factsheets or web pages."""

    def __init__(self, fetcher: Optional[SecureHttpFetcher] = None) -> None:
        self.fetcher = fetcher or SecureHttpFetcher()

    def fetch_url(
        self,
        url: str,
        publisher: str,
        title: Optional[str] = None,
    ) -> Tuple[SourceRecord, str]:
        """Fetch URL with SSRF protection, extract clean textual body, and return sealed SourceRecord + wrapped text."""
        # 1. Download safely through SecureHttpFetcher (validates DNS, whitelist, redirects)
        raw_bytes = self.fetcher.fetch(url)
        raw_sha = compute_content_sha256(raw_bytes)

        # 2. Extract in-memory with trafilatura (no network call inside trafilatura)
        html_text = raw_bytes.decode("utf-8", errors="replace")
        extracted = trafilatura.extract(html_text, include_tables=True, output_format="txt") or ""
        clean_text = sanitize_extracted_text(extracted)

        doc_title = title or f"{publisher} Factsheet"
        source_rec = SourceRecord(
            source_type=SourceType.FACTSHEET,
            title=doc_title,
            url_or_path=url,
            publisher=publisher,
            content_sha256=raw_sha,
        )

        wrapped = wrap_untrusted_source(
            source_id=source_rec.source_id,
            source_type="FACTSHEET",
            publisher=publisher,
            content=clean_text,
        )

        return source_rec, wrapped

    def load_local_document(
        self,
        file_path: Path | str,
        publisher: str,
        title: str,
    ) -> Tuple[SourceRecord, str]:
        """Load and extract text from an approved local factsheet document."""
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {p}")

        content_bytes = p.read_bytes()
        raw_sha = compute_content_sha256(content_bytes)

        # Attempt trafilatura extraction if HTML/XML, otherwise decode text
        content_str = content_bytes.decode("utf-8", errors="replace")
        extracted = trafilatura.extract(content_str, include_tables=True, output_format="txt")
        clean_text = sanitize_extracted_text(extracted if extracted else content_str)

        source_rec = SourceRecord(
            source_type=SourceType.FACTSHEET,
            title=title,
            url_or_path=str(p.resolve()),
            publisher=publisher,
            content_sha256=raw_sha,
        )

        wrapped = wrap_untrusted_source(
            source_id=source_rec.source_id,
            source_type="FACTSHEET",
            publisher=publisher,
            content=clean_text,
        )

        return source_rec, wrapped
