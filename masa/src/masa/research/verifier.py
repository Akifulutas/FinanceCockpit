"""Report and Metric Verifier (IP-6).

Audits quantitative statements and claims in generated reports against sealed evidence.
Distinguishes dates, times, and section numbering from financial numbers.
Enforces report lifecycle states: draft -> code_checked -> independent_reviewed | needs_review.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from masa.research.models import ClaimType
from masa.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class ReportStatus(str, Enum):
    """Lifecycle state of a research report."""
    DRAFT = "draft"
    CODE_CHECKED = "code_checked"
    INDEPENDENT_REVIEWED = "independent_reviewed"
    NEEDS_REVIEW = "needs_review"


class VerificationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_text: str
    is_verified: bool
    source_title: Optional[str] = None
    metric_name: Optional[str] = None
    status_tag: str  # "DOĞRULANDI" or "KAYNAKSIZ / TEYİT EDİLMEMİŞ"
    details: Optional[str] = None


class ReportVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ReportStatus
    total_statements_checked: int
    verified_count: int
    unverified_count: int
    verification_score_pct: Decimal
    items: List[VerificationItem]
    is_fully_verified: bool
    summary_message: str


class FinancialNumberExtractor:
    """Multi-stage tokenizer that extracts financial numbers while filtering out dates, times, and sections."""

    # 1. Negative patterns: strictly ignored from financial number extraction
    RE_DATE_ISO = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")          # 2026-10-30, 2026/10/30
    RE_DATE_EUR = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b")     # 30.10.2026, 30/10/2026
    RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")                       # Standalone 4-digit year (1990-2099)
    RE_MONTH_YEAR = re.compile(
        r"\b(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık|"
        r"January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        re.IGNORECASE,
    )
    RE_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:CET|UTC|EST|GMT))?\b", re.IGNORECASE)
    RE_SECTION = re.compile(r"§\s*\d+(?:\.\d+)*")                     # §4, §4.1
    RE_ITEM_REF = re.compile(r"\b(?:Bölüm|Madde|İP|IP|SPEC|Adım|Faz|Kural)\s*[-:]?\s*\d+(?:\.\d+)*", re.IGNORECASE)
    RE_VERSION = re.compile(r"\bv\d+(?:\.\d+)+(?:-[a-z0-9.]+)?\b", re.IGNORECASE)  # v1.0.0, v0.2
    RE_LIST_NUM = re.compile(r"^\s*\d+[\.\)]\s+", re.MULTILINE)       # 1. , 2)
    RE_IDENTIFIER = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")          # ISIN
    RE_TAGS = re.compile(r"\[\[(?:source|metric|quote):[^\]]+\]\]")   # Semantic citations
    RE_INTERNAL_IDS = re.compile(r"\b(?:clm|met|src|bnd|snp|raw)_[a-zA-Z0-9_-]+\b")

    # 2. Positive financial candidate patterns
    RE_LABELED_METRIC = re.compile(
        r"(?:[\(\s]|^)(TER|Gider\s*Oran[ıi]|Sharpe|Volatilite|Getiri|Fiyat|NAV)\b\s*[:\)=]?\s*([%€$]?\s*[-+]?\d+(?:[.,]\d+)?\s*(?:[%€$]|bps|baz\s+puan|EUR|USD)?)\b",
        re.IGNORECASE,
    )
    RE_CURRENCY_AFTER = re.compile(r"[-+]?\d+(?:[.,]\d+)?\s*(?:EUR|USD|TRY|GBP|€|\$)", re.IGNORECASE)
    RE_CURRENCY_BEFORE = re.compile(r"(?:€|\$)\s*[-+]?\d+(?:[.,]\d+)?")
    RE_PERCENT_AFTER = re.compile(r"[-+]?\d+(?:[.,]\d+)?\s*%")
    RE_PERCENT_BEFORE = re.compile(r"%\s*[-+]?\d+(?:[.,]\d+)?")
    RE_BPS = re.compile(r"[-+]?\d+(?:[.,]\d+)?\s*(?:bps|baz\s+puan)", re.IGNORECASE)
    RE_MULTIPLIER = re.compile(r"\b\d+(?:[.,]\d+)?\s*[xX]\b")
    RE_SHARE_COUNT = re.compile(r"\b\d+\+?\s*(?:hisse|bileşen|pay|adet)\b", re.IGNORECASE)

    @classmethod
    def extract_candidate_tokens(cls, text: str) -> List[Tuple[str, Optional[str], Optional[Decimal]]]:
        """Extract candidate financial expressions with optional label and parsed Decimal value.

        Returns list of tuples: (raw_match_text, metric_label_or_none, parsed_decimal_value_or_none)
        """
        # Step 1: Blank out non-financial occurrences (dates, times, sections, identifiers)
        # to ensure 100% false-alarm prevention.
        masked_text = text
        for neg_pat in [
            cls.RE_DATE_ISO,
            cls.RE_DATE_EUR,
            cls.RE_MONTH_YEAR,
            cls.RE_TIME,
            cls.RE_SECTION,
            cls.RE_ITEM_REF,
            cls.RE_VERSION,
            cls.RE_IDENTIFIER,
            cls.RE_TAGS,
            cls.RE_INTERNAL_IDS,
        ]:
            masked_text = neg_pat.sub(lambda m: " " * len(m.group(0)), masked_text)

        # Also mask standalone years (only if not preceded/followed by % or currency)
        def mask_standalone_year(m: re.Match) -> str:
            start = m.start()
            end = m.end()
            # Check context around year
            prefix = masked_text[max(0, start - 5):start]
            suffix = masked_text[end:min(len(masked_text), end + 5)]
            if "%" in prefix or "%" in suffix or "EUR" in suffix or "USD" in suffix:
                return m.group(0)
            return " " * len(m.group(0))

        masked_text = cls.RE_YEAR.sub(mask_standalone_year, masked_text)

        # Step 2: Extract positive candidates
        candidates: List[Tuple[str, Optional[str], Optional[Decimal]]] = []
        seen_spans: Set[Tuple[int, int]] = set()

        # Check labeled metrics first
        for m in cls.RE_LABELED_METRIC.finditer(masked_text):
            span = m.span()
            seen_spans.add(span)
            label = m.group(1).strip()
            num_part = m.group(2).strip()
            dec_val = cls._parse_decimal(num_part)
            candidates.append((m.group(0).strip(), label, dec_val))

        # Check other patterns
        for pat in [
            cls.RE_CURRENCY_AFTER,
            cls.RE_CURRENCY_BEFORE,
            cls.RE_PERCENT_AFTER,
            cls.RE_PERCENT_BEFORE,
            cls.RE_BPS,
            cls.RE_MULTIPLIER,
            cls.RE_SHARE_COUNT,
        ]:
            for m in pat.finditer(masked_text):
                span = m.span()
                # Ensure no overlap with already extracted labeled metric
                if any(s[0] <= span[0] and span[1] <= s[1] for s in seen_spans):
                    continue
                seen_spans.add(span)
                raw = m.group(0).strip()
                dec_val = cls._parse_decimal(raw)
                candidates.append((raw, None, dec_val))

        return candidates

    @classmethod
    def _parse_decimal(cls, text: str) -> Optional[Decimal]:
        """Extract the numeric portion of a token and parse into Decimal."""
        m = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
        if not m:
            return None
        cleaned = m.group(0).replace(",", ".")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None


class ReportVerifier:
    """Verifies that facts, claims, and metrics in text reports are backed by sealed evidence."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()

    def _resolve_canonical_id(self, conn, identifier: Optional[str]) -> Optional[str]:
        if not identifier:
            return None
        try:
            row = conn.execute(
                "SELECT instrument_id FROM instruments WHERE instrument_id = ? OR isin = ?",
                (identifier, identifier)
            ).fetchone()
            return row["instrument_id"] if row else identifier
        except Exception:
            return identifier

    def get_known_metrics(self, instrument_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch verified metrics from database with full numeric and unit context."""
        conn = self.db.get_connection()
        try:
            canonical_id = self._resolve_canonical_id(conn, instrument_id)
            q = "SELECT metric_id, metric_name, value, unit, period_start, period_end, source_id FROM metrics WHERE 1=1"
            params: List[Any] = []
            if canonical_id:
                q += " AND (instrument_id = ? OR instrument_id = ?)"
                params.extend([canonical_id, instrument_id])
            rows = conn.execute(q, tuple(params)).fetchall()
            result = []
            for r in rows:
                try:
                    dec_val = Decimal(str(r["value"]))
                except InvalidOperation:
                    dec_val = None
                result.append({
                    "metric_id": r["metric_id"],
                    "metric_name": r["metric_name"],
                    "norm_name": r["metric_name"].lower().strip(),
                    "value_dec": dec_val,
                    "value_str": str(r["value"]),
                    "unit": str(r["unit"]),
                    "source_id": r["source_id"],
                })
            return result
        finally:
            conn.close()

    def get_known_quotes(self, instrument_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch latest quotes for the instrument."""
        conn = self.db.get_connection()
        try:
            canonical_id = self._resolve_canonical_id(conn, instrument_id)
            isin = instrument_id
            if canonical_id and canonical_id != instrument_id:
                try:
                    row = conn.execute("SELECT isin FROM instruments WHERE instrument_id = ?", (canonical_id,)).fetchone()
                    if row and row["isin"]:
                        isin = row["isin"]
                except Exception:
                    pass

            q = "SELECT bid, ask, computed_mid, provider_mid, spread, spread_pct, currency, exchange FROM quotes WHERE 1=1"
            params: List[Any] = []
            if isin:
                q += " AND (isin = ? OR isin = ?)"
                params.extend([isin, instrument_id])
            q += " ORDER BY retrieved_at DESC LIMIT 5"
            rows = conn.execute(q, tuple(params)).fetchall()
            result = []
            for r in rows:
                for k in ("bid", "ask", "computed_mid", "provider_mid", "spread", "spread_pct"):
                    if k in r.keys() and r[k] is not None:
                        try:
                            result.append({
                                "field": k,
                                "value_dec": Decimal(str(r[k])),
                                "currency": r["currency"] if "currency" in r.keys() else None,
                            })
                        except Exception:
                            pass
            return result
        finally:
            conn.close()

    def get_known_claims(self, instrument_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch verified claims from v_evidence_verified."""
        conn = self.db.get_connection()
        try:
            canonical_id = self._resolve_canonical_id(conn, instrument_id)
            q = "SELECT * FROM v_evidence_verified WHERE verification_status = 'VERIFIED'"
            params: List[Any] = []
            if canonical_id:
                q += " AND (instrument_id = ? OR instrument_id = ?)"
                params.extend([canonical_id, instrument_id])
            rows = conn.execute(q, tuple(params)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def _metric_synonyms_match(cls, label: str, metric_name: str) -> bool:
        tr_map = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iIgGuUsSoOcC")
        nl = re.sub(r"[^a-z0-9]", "", label.translate(tr_map).lower())
        nm = re.sub(r"[^a-z0-9]", "", metric_name.translate(tr_map).lower())
        if nl == nm or nl in nm or nm in nl:
            return True
        synonyms = [
            {"ter", "terpct", "giderorani", "gideroran", "toplamgider", "toplamgiderorani", "expenseratio"},
            {"mid", "midprice", "ortafiyat", "ortapiyasafiyati", "fiyat", "computedmid", "providermid"},
            {"spread", "makas", "spreadpct"},
            {"sharpe", "sharperatio"},
            {"volatilite", "volatility", "oynaklik"},
            {"trackingdiff", "trackingdifference", "takipfarki"},
        ]
        for s in synonyms:
            if (nl in s or any(x in nl for x in s)) and (nm in s or any(y in nm for y in s)):
                return True
        return False

    def verify_report(
        self,
        report_text: str,
        instrument_id: Optional[str] = None,
        is_independent_model_review: bool = False,
    ) -> ReportVerificationResult:
        """Audit report text against known verified metrics and claims.

        Guarantees:
        - Dates and section numbers produce zero false alarms.
        - Deliberately wrong financial numbers (e.g. false TER %0.45 instead of %0.12) are detected and flagged.
        - Every factual claim without sealed evidence triggers needs_review.
        - Computes lifecycle state: draft -> code_checked -> independent_reviewed | needs_review.
        """
        metrics = self.get_known_metrics(instrument_id)
        quotes = self.get_known_quotes(instrument_id)
        claims = self.get_known_claims(instrument_id)

        candidates = FinancialNumberExtractor.extract_candidate_tokens(report_text)
        items: List[VerificationItem] = []
        verified_count = 0

        # Numerical comparison tolerance (relative and absolute)
        ABS_TOLERANCE = Decimal("0.005")

        def matches_value(val_a: Optional[Decimal], val_b: Optional[Decimal]) -> bool:
            if val_a is None or val_b is None:
                return False
            return abs(val_a - val_b) <= ABS_TOLERANCE

        # 1. Verify candidate financial numbers
        if candidates:
            for raw_text, label, dec_val in candidates:
                is_backed = False
                matched_source = None
                matched_metric = None
                details = None

                # Case A: Candidate has a metric label (e.g. "TER %0.45", "Sharpe 1.25")
                if label:
                    # Find matching metric by name or synonyms
                    matching_metrics = [m for m in metrics if self._metric_synonyms_match(label, m["metric_name"])]
                    if matching_metrics:
                        # Check value matches!
                        val_matches = any(matches_value(dec_val, m["value_dec"]) for m in matching_metrics)
                        if val_matches:
                            is_backed = True
                            matched_metric = matching_metrics[0]["metric_name"]
                            matched_source = matching_metrics[0]["source_id"]
                            details = f"Metrik '{matched_metric}' değeri ({dec_val}) mühürlü değerle tam uyuştu."
                        else:
                            # CRITICAL BUG FIX: Metric name matches, but numerical value DOES NOT MATCH!
                            is_backed = False
                            matched_metric = matching_metrics[0]["metric_name"]
                            expected_val = matching_metrics[0]["value_str"]
                            details = f"HATALI RAKAM: '{label}' için raporda '{dec_val}' geçti, mühürlü değer: '{expected_val}'!"
                    else:
                        is_backed = False
                        details = f"Metrik '{label}' veritabanında bulunamadı."

                # Case B: Candidate has no label (e.g. "0.12%", "100.22 EUR", "25 bps")
                if not label and dec_val is not None:
                    # Check metrics values
                    for m in metrics:
                        if matches_value(dec_val, m["value_dec"]):
                            is_backed = True
                            matched_metric = m["metric_name"]
                            matched_source = m["source_id"]
                            details = f"Değer ({dec_val}), mühürlü '{m['metric_name']}' metriği ile uyuştu."
                            break

                    # Check quotes
                    if not is_backed:
                        for q in quotes:
                            if matches_value(dec_val, q["value_dec"]):
                                is_backed = True
                                matched_metric = f"quote_{q['field']}"
                                details = f"Değer ({dec_val}), mühürlü kotasyon ({q['field']}) ile uyuştu."
                                break

                    # Check verbatim claims
                    if not is_backed:
                        norm_raw = raw_text.lower().replace(" ", "")
                        for c in claims:
                            c_quote = c["quote_verbatim"].lower().replace(" ", "")
                            c_text = c["claim_text"].lower().replace(" ", "")
                            if norm_raw in c_quote or norm_raw in c_text:
                                is_backed = True
                                matched_source = c.get("source_title") or c.get("source_id")
                                details = f"Alıntı mühürlü iddia ({c['claim_id']}) içinde bulundu."
                                break

                if is_backed:
                    verified_count += 1
                    items.append(
                        VerificationItem(
                            target_text=raw_text,
                            is_verified=True,
                            source_title=matched_source,
                            metric_name=matched_metric,
                            status_tag="DOĞRULANDI",
                            details=details,
                        )
                    )
                else:
                    status_tag = "UYUMSUZ / ÇELİŞKİLİ DEĞER" if (details and "HATALI RAKAM" in details) else "KAYNAKSIZ / TEYİT EDİLMEMİŞ"
                    items.append(
                        VerificationItem(
                            target_text=raw_text,
                            is_verified=False,
                            source_title=matched_source,
                            metric_name=matched_metric,
                            status_tag=status_tag,
                            details=details or "Mühürlü kanıt veya kotasyon eşleşmesi bulunamadı.",
                        )
                    )

        # 2. Check for explicit unsourced factual claims
        # Look for sentences or claim lines marked as fact without source citation
        claim_lines = [
            line.strip()
            for line in report_text.splitlines()
            if line.strip().startswith("- Olgu:") or line.strip().startswith("- [fact]") or "iddia:" in line.lower()
        ]
        for cline in claim_lines:
            has_source_link = ("[[source:" in cline) or any(s in cline for s in [c["source_id"] for c in claims])
            if not has_source_link:
                items.append(
                    VerificationItem(
                        target_text=cline[:100],
                        is_verified=False,
                        status_tag="KAYNAKSIZ / TEYİT EDİLMEMİŞ",
                        details="Olgu (fact) iddiası mühürlü bir kaynak bağı taşımıyor.",
                    )
                )

        total = len(items)
        unverified = total - verified_count
        score = (
            ((Decimal(str(verified_count)) / Decimal(str(total))) * Decimal("100")).quantize(Decimal("0.01"))
            if total > 0
            else Decimal("100.00")
        )
        is_fully_verified = (unverified == 0)

        # Lifecycle state determination
        if not is_fully_verified:
            status = ReportStatus.NEEDS_REVIEW
            summary = f"Rapor denetimi BAŞARISIZ ({unverified} kaynaksız/hatalı ifade bulundu). Durum: needs_review."
        elif is_independent_model_review:
            status = ReportStatus.INDEPENDENT_REVIEWED
            summary = "Tüm finansal sayılar ve iddialar mühürlü kanıtlarla doğrulandı + Bağımsız model denetiminden geçti."
        else:
            status = ReportStatus.CODE_CHECKED
            summary = "Tüm finansal sayılar ve iddialar mühürlü kanıtlarla doğrulandı (Kod kontrolünden geçti — Bağımsız model denetimi: YOK)."

        return ReportVerificationResult(
            status=status,
            total_statements_checked=total,
            verified_count=verified_count,
            unverified_count=unverified,
            verification_score_pct=score,
            items=items,
            is_fully_verified=is_fully_verified,
            summary_message=summary,
        )
