"""ETF Holdings Loader and Ingestion Pipeline (İP-4).

Coordinates scanning, provider identification, SHA-256 raw object persistence,
deduplication, non-inflation verification, database insertion into holdings_sets
and holding_items, audit event logging, and secure file archival.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from masa.audit.events import AuditLogger
from masa.identity.isin import validate_isin
from masa.holdings.ishares_parser import ISIN_REGEX, ISharesParser
from masa.holdings.models import HoldingsValidationError, ParsedHoldingsSet
from masa.holdings.spdr_parser import SPDRParser
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_holding_item_hash, compute_holdings_set_hash, sha256_text

logger = logging.getLogger(__name__)

HOLDINGS_INBOX_DIR = Path("var/private/holdings/inbox")
HOLDINGS_PROCESSED_DIR = Path("var/private/holdings/processed")
HOLDINGS_REJECTED_DIR = Path("var/private/holdings/rejected")


class IngestionResult:
    """Outcome of a holdings basket ingestion attempt."""

    def __init__(
        self,
        success: bool,
        status: str,
        set_id: Optional[str] = None,
        isin: Optional[str] = None,
        provider: Optional[str] = None,
        as_of_date: Optional[date] = None,
        record_count: int = 0,
        total_weight: Optional[Decimal] = None,
        file_path: Optional[Path] = None,
        archived_path: Optional[Path] = None,
        is_stale: bool = False,
        age_days: int = 0,
        staleness_warning: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self.success = success
        self.status = status
        self.set_id = set_id
        self.isin = isin
        self.provider = provider
        self.as_of_date = as_of_date
        self.record_count = record_count
        self.total_weight = total_weight
        self.file_path = file_path
        self.archived_path = archived_path
        self.is_stale = is_stale
        self.age_days = age_days
        self.staleness_warning = staleness_warning
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "set_id": self.set_id,
            "isin": self.isin,
            "provider": self.provider,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "record_count": self.record_count,
            "total_weight": str(self.total_weight) if self.total_weight is not None else None,
            "file_path": str(self.file_path) if self.file_path else None,
            "archived_path": str(self.archived_path) if self.archived_path else None,
            "is_stale": self.is_stale,
            "age_days": self.age_days,
            "staleness_warning": self.staleness_warning,
            "error_message": self.error_message,
        }


class HoldingsLoader:
    """Manages ingestion of ETF basket files into database."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        self.db = db or DatabaseManager()
        self.base_dir = base_dir or Path(self.db.db_path.parent.parent.parent)
        self.inbox_dir = self.base_dir / HOLDINGS_INBOX_DIR
        self.processed_dir = self.base_dir / HOLDINGS_PROCESSED_DIR
        self.rejected_dir = self.base_dir / HOLDINGS_REJECTED_DIR

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create holdings parent, inbox, processed, and rejected directories with 0700 permissions."""
        try:
            self.inbox_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.inbox_dir.parent, 0o700)
        except OSError:
            pass

        for d in [self.inbox_dir, self.processed_dir, self.rejected_dir]:
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass

    def scan_inbox(self) -> List[Path]:
        """Scan inbox directory for holdings files (*.csv, *.xlsx, *.xls)."""
        if not self.inbox_dir.exists():
            return []
        found: List[Path] = []
        for ext in ["*.csv", "*.xlsx", "*.xls"]:
            found.extend(sorted(self.inbox_dir.glob(ext)))
        return found

    def ingest_file(
        self,
        file_path: Union[str, Path],
        isin: Optional[str] = None,
        provider: Optional[str] = None,
        as_of_date: Optional[date] = None,
        archive: bool = True,
    ) -> IngestionResult:
        """Process and ingest a single holdings file."""
        path = Path(file_path).resolve()
        if not path.exists():
            return IngestionResult(
                success=False,
                status="FILE_NOT_FOUND",
                file_path=path,
                error_message=f"Sepet dosyası bulunamadı: {path}",
            )

        try:
            raw_bytes = path.read_bytes()
            file_sha256 = hashlib.sha256(raw_bytes).hexdigest()

            # Identify ISIN
            target_isin = isin or self._detect_isin(path, raw_bytes)
            if not target_isin:
                raise HoldingsValidationError(
                    f"Sepet dosyası için ISIN tespit edilemedi ({path.name}). "
                    "Lütfen dosya adında ISIN belirtin veya --isin parametresini kullanın."
                )
            try:
                target_isin = validate_isin(target_isin)
            except Exception as e:
                raise HoldingsValidationError(f"Geçersiz fon ISIN kimliği: '{target_isin}' ({e})")

            # Identify provider
            detected_provider = provider or self._detect_provider(path, raw_bytes)

            # Check deduplication by ISIN and file hash or existing holdings_sets
            conn = self.db.get_connection()
            try:
                existing = conn.execute(
                    """
                    SELECT s.set_id, s.as_of_date, s.total_records, s.total_weight_pct
                    FROM holdings_sets s
                    WHERE s.isin = ? AND EXISTS (
                        SELECT 1 FROM raw_objects r
                        WHERE r.payload_sha256 = ?
                    )
                    ORDER BY s.created_at DESC
                    LIMIT 1
                    """,
                    (target_isin, file_sha256),
                ).fetchone()
                if existing:
                    return IngestionResult(
                        success=True,
                        status="DUPLICATE_SKIPPED",
                        set_id=existing["set_id"],
                        isin=target_isin,
                        provider=detected_provider,
                        as_of_date=datetime.strptime(existing["as_of_date"], "%Y-%m-%d").date(),
                        record_count=existing["total_records"],
                        total_weight=Decimal(str(existing["total_weight_pct"])),
                        file_path=path,
                    )
            finally:
                conn.close()

            # Parse with appropriate parser
            if detected_provider.upper() == "SPDR" or path.suffix.lower() in (".xlsx", ".xls"):
                parsed = SPDRParser.parse(
                    content=raw_bytes,
                    isin=target_isin,
                    as_of_date=as_of_date,
                    source_file_name=path.name,
                )
            else:
                try:
                    parsed = ISharesParser.parse(
                        content=raw_bytes,
                        isin=target_isin,
                        as_of_date=as_of_date,
                        source_file_name=path.name,
                    )
                except Exception as e_ishares:
                    # Fallback to SPDR parser in case it was a CSV formatted like SPDR
                    try:
                        parsed = SPDRParser.parse(
                            content=raw_bytes,
                            isin=target_isin,
                            as_of_date=as_of_date,
                            source_file_name=path.name,
                        )
                    except Exception:
                        raise e_ishares

            # Non-inflation check (already in parser, but double-checked here)
            if parsed.total_weight_pct > Decimal("1.0001"):
                raise HoldingsValidationError(
                    f"Sepet toplam ağırlığı {parsed.total_weight_pct} > 1.0001 sınırını aşıyor."
                )

            # Check staleness
            today = date.today()
            age_days = (today - parsed.as_of_date).days
            is_stale = age_days > 45
            staleness_warning = None
            if is_stale:
                staleness_warning = (
                    f"⚠️ UYARI: {target_isin} ({parsed.provider}) sepeti {age_days} günlük "
                    f"(45 günden eski, as_of_date: {parsed.as_of_date}). Güncel sepet yüklenmesi önerilir."
                )
                logger.warning(staleness_warning)

            # Persist raw object into raw_objects
            raw_text = raw_bytes.decode("utf-8", errors="replace") if path.suffix.lower() == ".csv" else raw_bytes.hex()
            now_iso = datetime.now(timezone.utc).isoformat()
            raw_id = self._store_raw_object(
                source=f"holdings_{parsed.provider.lower()}",
                command=path.name,
                payload_sha256=file_sha256,
                payload_text=raw_text,
                retrieved_at=now_iso,
                record_count=parsed.total_records,
            )

            # Generate set ID and hashes
            set_id = f"hs_{uuid.uuid4().hex[:16]}"
            set_row = {
                "set_id": set_id,
                "isin": parsed.isin,
                "as_of_date": parsed.as_of_date.isoformat(),
                "source_file": path.name,
                "provider": parsed.provider,
                "total_records": parsed.total_records,
                "total_weight_pct": str(parsed.total_weight_pct),
                "created_at": now_iso,
            }
            set_record_hash = compute_holdings_set_hash(set_row)
            set_row["record_hash"] = set_record_hash

            # Prepare items
            item_rows: List[Dict[str, Any]] = []
            for item in parsed.items:
                item_id = f"hi_{set_id}_{item.item_order}"
                i_dict = {
                    "item_id": item_id,
                    "set_id": set_id,
                    "constituent_isin": item.constituent_isin,
                    "constituent_ticker": item.constituent_ticker,
                    "constituent_name": item.constituent_name,
                    "weight_pct": str(item.weight_pct),
                    "shares_held": str(item.shares_held) if item.shares_held is not None else None,
                    "market_value": str(item.market_value) if item.market_value is not None else None,
                    "currency": item.currency,
                    "sector": item.sector,
                    "country": item.country,
                    "asset_class": item.asset_class,
                    "item_order": item.item_order,
                    "created_at": now_iso,
                }
                i_hash = compute_holding_item_hash(i_dict)
                i_dict["record_hash"] = i_hash
                item_rows.append(i_dict)

            # Insert into database in a single transaction
            with self.db.transaction() as db_conn:
                db_conn.execute(
                    """
                    INSERT INTO holdings_sets (
                        set_id, isin, as_of_date, source_file, provider,
                        total_records, total_weight_pct, record_hash, created_at
                    ) VALUES (
                        :set_id, :isin, :as_of_date, :source_file, :provider,
                        :total_records, :total_weight_pct, :record_hash, :created_at
                    )
                    """,
                    set_row,
                )

                db_conn.executemany(
                    """
                    INSERT INTO holding_items (
                        item_id, set_id, constituent_isin, constituent_ticker,
                        constituent_name, weight_pct, shares_held, market_value,
                        currency, sector, country, asset_class, item_order,
                        record_hash, created_at
                    ) VALUES (
                        :item_id, :set_id, :constituent_isin, :constituent_ticker,
                        :constituent_name, :weight_pct, :shares_held, :market_value,
                        :currency, :sector, :country, :asset_class, :item_order,
                        :record_hash, :created_at
                    )
                    """,
                    item_rows,
                )

            # Audit event logging
            try:
                AuditLogger(self.db).log_event(
                    actor="masa.holdings.loader",
                    action="HOLDINGS_SET_INGESTED",
                    entity_type="holdings_set",
                    entity_id=set_id,
                    payload={
                        "isin": parsed.isin,
                        "provider": parsed.provider,
                        "as_of_date": parsed.as_of_date.isoformat(),
                        "total_records": parsed.total_records,
                        "total_weight_pct": str(parsed.total_weight_pct),
                        "file_sha256": file_sha256,
                        "source_file": path.name,
                    },
                )
            except Exception as e_audit:
                logger.warning(f"Audit log yazılamadı: {e_audit}")

            # Archival
            archived_path: Optional[Path] = None
            if archive:
                archived_path = self._archive_file(path)

            return IngestionResult(
                success=True,
                status="INGESTED",
                set_id=set_id,
                isin=target_isin,
                provider=parsed.provider,
                as_of_date=parsed.as_of_date,
                record_count=parsed.total_records,
                total_weight=parsed.total_weight_pct,
                file_path=path,
                archived_path=archived_path,
                is_stale=is_stale,
                age_days=age_days,
                staleness_warning=staleness_warning,
            )

        except Exception as exc:
            logger.error(f"Sepet yükleme hatası ({path.name}): {exc}")
            self._log_rejected(path, str(exc))
            return IngestionResult(
                success=False,
                status="FAILED",
                file_path=path,
                error_message=str(exc),
            )

    def _store_raw_object(
        self,
        source: str,
        command: str,
        payload_sha256: str,
        payload_text: str,
        retrieved_at: str,
        record_count: int,
    ) -> int:
        """Store payload in raw_objects idempotently."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT raw_id FROM raw_objects WHERE payload_sha256 = ?",
                (payload_sha256,),
            ).fetchone()
            if row:
                return int(row["raw_id"])
        finally:
            conn.close()

        with self.db.transaction() as tx_conn:
            cur = tx_conn.execute(
                """
                INSERT INTO raw_objects (
                    source, command, payload_sha256, payload_text,
                    retrieved_at, record_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    command,
                    payload_sha256,
                    payload_text,
                    retrieved_at,
                    record_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cur.lastrowid)

    def _archive_file(self, file_path: Path) -> Path:
        """Move ingested file to processed directory with 0600 permissions."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_name = f"{timestamp}_{file_path.name}"
        target_path = self.processed_dir / target_name

        # If file is inside inbox, move it; otherwise copy it
        if self.inbox_dir in file_path.resolve().parents or file_path.parent.resolve() == self.inbox_dir.resolve():
            shutil.move(str(file_path), str(target_path))
        else:
            shutil.copy2(str(file_path), str(target_path))

        try:
            os.chmod(target_path, 0o600)
        except OSError:
            pass
        return target_path

    def _log_rejected(self, file_path: Path, error_text: str) -> None:
        """Record error details in rejected folder."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            err_file = self.rejected_dir / f"{timestamp}_{file_path.name}.err"
            err_file.write_text(f"Dosya: {file_path}\nHata: {error_text}\nZaman: {datetime.now(timezone.utc).isoformat()}\n")
            os.chmod(err_file, 0o600)
        except Exception as e:
            logger.warning(f"Reddedilen dosya logu yazılamadı: {e}")

    def _detect_isin(self, path: Path, raw_bytes: bytes) -> Optional[str]:
        """Attempt to extract ISIN from filename or text."""
        # 1. Search filename for ISIN pattern (not bounded by \w so _ is allowed)
        m = re.search(r"(?<![A-Z0-9])([A-Z]{2}[A-Z0-9]{9}[0-9])(?![A-Z0-9])", path.name.upper())
        if m:
            return m.group(1)

        # 2. Search text content if CSV (looking for fund ISIN header, not constituent lines)
        if path.suffix.lower() == ".csv":
            try:
                text_sample = raw_bytes[:2048].decode("utf-8", errors="replace")
                m = re.search(r"(?:ISIN|FONDS|FUND)[\s:=_-]+([A-Z]{2}[A-Z0-9]{9}[0-9])", text_sample, re.IGNORECASE)
                if m:
                    return m.group(1).upper()
            except Exception:
                pass
        return None

    def _detect_provider(self, path: Path, raw_bytes: bytes) -> str:
        """Determine provider (iShares or SPDR)."""
        name_lower = path.name.lower()
        if "spdr" in name_lower or "ssga" in name_lower:
            return "SPDR"
        if "ishares" in name_lower or "blackrock" in name_lower:
            return "iShares"

        # Check content sample
        sample = raw_bytes[:4096].decode("utf-8", errors="replace").lower()
        if "state street" in sample or "spdr" in sample:
            return "SPDR"
        if "blackrock" in sample or "ishares" in sample:
            return "iShares"

        # If XLSX, default to SPDR
        if path.suffix.lower() in (".xlsx", ".xls"):
            return "SPDR"

        return "iShares"
