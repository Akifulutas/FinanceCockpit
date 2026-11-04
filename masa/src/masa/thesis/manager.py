"""Investment Thesis Manager (IP-5).

Manages immutable, sealed investment theses with linear versioning (supersedes_id chain).
Enforces Born-Sealed immutability: records are validated and hashed prior to insertion.
Zero in-place updates; status changes and edits produce superseding version records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from masa.audit.events import AuditLogger
from masa.identity.isin import validate_isin
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_thesis_version_hash
from masa.thesis.models import (
    ThesisCategory,
    ThesisHorizon,
    ThesisRecord,
    ThesisStatus,
)

logger = logging.getLogger(__name__)


class ThesisManager:
    """Manages investment theses lifecycle, immutability, and queries."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()

    def create_thesis(self, record: ThesisRecord) -> ThesisRecord:
        """Create a new investment thesis (version 1) and seal into DB."""
        # 0. Sürüm 1 ve kök düğüm denetimi
        if record.version_number != 1 or record.supersedes_id is not None:
            raise ValueError(
                "create_thesis yalnızca ilk sürüm (version_number=1, supersedes_id=None) için kullanılabilir. "
                "Revizyonlar için 'revise_thesis' metodunu kullanın."
            )

        # 1. ISIN doğrulaması
        validate_isin(record.isin)

        # 2. Instruments tablosunda kayıtlı ve aktif mi kontrolü
        conn = self.db.get_connection()
        try:
            inst = conn.execute(
                "SELECT instrument_id, name, is_active FROM instruments WHERE isin = ?",
                (record.isin,),
            ).fetchone()
            if not inst or not inst["is_active"]:
                raise ValueError(
                    f"ISIN '{record.isin}' instruments tablosunda bulunamadı veya pasif durumda. "
                    "Önce enstrüman sisteme tanıtılmalıdır."
                )

            # 3. Bu ISIN için zaten aktif bir tez var mı?
            existing = conn.execute(
                "SELECT thesis_id, version_id, title FROM v_theses_current WHERE isin = ? AND status = 'ACTIVE'",
                (record.isin,),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"ISIN '{record.isin}' için zaten aktif bir tez mevcut (ID: {existing['thesis_id']}). "
                    "Değişiklik için 'masa tez revize' komutunu kullanın."
                )
        finally:
            conn.close()

        # 4. Hash hesaplama ve Born-Sealed kayıt
        row_dict_for_hash = record.to_db_row(computed_hash="")
        row_dict_for_hash.pop("record_hash", None)
        record_hash = compute_thesis_version_hash(row_dict_for_hash)

        row_data = record.to_db_row(computed_hash=record_hash)

        # 5. Atomik INSERT
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO thesis_versions (
                    version_id, thesis_id, supersedes_id, version_number,
                    isin, category, horizon, status, title, one_line_summary,
                    economic_rationale, evidence_pillars_json, counter_arguments,
                    falsification_triggers_json, benchmark_reference, sources_json,
                    target_allocation_pct, next_review_date, revision_rationale,
                    author, created_at, record_hash
                ) VALUES (
                    :version_id, :thesis_id, :supersedes_id, :version_number,
                    :isin, :category, :horizon, :status, :title, :one_line_summary,
                    :economic_rationale, :evidence_pillars_json, :counter_arguments,
                    :falsification_triggers_json, :benchmark_reference, :sources_json,
                    :target_allocation_pct, :next_review_date, :revision_rationale,
                    :author, :created_at, :record_hash
                )
                """,
                row_data,
            )

        # 6. Audit Event loglama
        try:
            AuditLogger(self.db).log_event(
                actor=record.author,
                action="THESIS_CREATED",
                entity_type="thesis",
                entity_id=record.thesis_id,
                payload={
                    "version_id": record.version_id,
                    "isin": record.isin,
                    "title": record.title,
                    "category": record.category.value,
                    "horizon": record.horizon.value,
                    "record_hash": record_hash,
                },
            )
        except Exception as exc:
            logger.warning(f"Audit log yazılamadı: {exc}")

        return ThesisRecord.from_db_row(row_data)

    def revise_thesis(
        self,
        thesis_id: str,
        rationale: str,
        updates: Optional[Dict[str, Any]] = None,
        author: str = "user",
    ) -> ThesisRecord:
        """Revise an existing thesis by producing a superseding version (version n+1)."""
        if not rationale or len(rationale.strip()) < 10:
            raise ValueError("Tez revizyonlarında en az 10 karakterlik açıklayıcı gerekçe (rationale) zorunludur.")

        current = self.get_thesis(thesis_id)
        if not current:
            raise ValueError(f"Tez bulunamadı: {thesis_id}")
        if current.thesis_id != thesis_id:
            raise ValueError(f"Tez ID uyuşmazlığı: beklenen {thesis_id}, bulunan {current.thesis_id}")

        if current.status == ThesisStatus.INVALIDATED:
            raise ValueError(f"Geçersiz kılınmış bir tez revize edilemez: {thesis_id}")

        updates = updates or {}
        new_version_id = f"thv_{uuid.uuid4().hex[:12]}"
        new_version_number = current.version_number + 1

        category = ThesisCategory(updates.get("category", current.category.value))
        horizon = ThesisHorizon(updates.get("horizon", current.horizon.value))
        target_allocation = updates.get("target_allocation_pct", current.target_allocation_pct)
        if target_allocation is not None and not isinstance(target_allocation, Decimal):
            target_allocation = Decimal(str(target_allocation))

        new_record = ThesisRecord(
            version_id=new_version_id,
            thesis_id=current.thesis_id,
            supersedes_id=current.version_id,
            version_number=new_version_number,
            isin=current.isin,
            category=category,
            horizon=horizon,
            status=ThesisStatus.ACTIVE,
            title=updates.get("title", current.title),
            one_line_summary=updates.get("one_line_summary", current.one_line_summary),
            economic_rationale=updates.get("economic_rationale", current.economic_rationale),
            evidence_pillars=updates.get("evidence_pillars", current.evidence_pillars),
            counter_arguments=updates.get("counter_arguments", current.counter_arguments),
            falsification_triggers=updates.get("falsification_triggers", current.falsification_triggers),
            benchmark_reference=updates.get("benchmark_reference", current.benchmark_reference),
            sources=updates.get("sources", current.sources),
            target_allocation_pct=target_allocation,
            next_review_date=updates.get("next_review_date", current.next_review_date),
            revision_rationale=rationale.strip(),
            author=author,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        row_dict_for_hash = new_record.to_db_row(computed_hash="")
        row_dict_for_hash.pop("record_hash", None)
        record_hash = compute_thesis_version_hash(row_dict_for_hash)
        row_data = new_record.to_db_row(computed_hash=record_hash)

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO thesis_versions (
                    version_id, thesis_id, supersedes_id, version_number,
                    isin, category, horizon, status, title, one_line_summary,
                    economic_rationale, evidence_pillars_json, counter_arguments,
                    falsification_triggers_json, benchmark_reference, sources_json,
                    target_allocation_pct, next_review_date, revision_rationale,
                    author, created_at, record_hash
                ) VALUES (
                    :version_id, :thesis_id, :supersedes_id, :version_number,
                    :isin, :category, :horizon, :status, :title, :one_line_summary,
                    :economic_rationale, :evidence_pillars_json, :counter_arguments,
                    :falsification_triggers_json, :benchmark_reference, :sources_json,
                    :target_allocation_pct, :next_review_date, :revision_rationale,
                    :author, :created_at, :record_hash
                )
                """,
                row_data,
            )

        try:
            AuditLogger(self.db).log_event(
                actor=author,
                action="THESIS_REVISED",
                entity_type="thesis",
                entity_id=thesis_id,
                payload={
                    "version_id": new_version_id,
                    "supersedes_id": current.version_id,
                    "version_number": new_version_number,
                    "rationale": rationale.strip(),
                    "record_hash": record_hash,
                },
            )
        except Exception as exc:
            logger.warning(f"Audit log yazılamadı: {exc}")

        return ThesisRecord.from_db_row(row_data)

    def invalidate_thesis(
        self,
        thesis_id: str,
        rationale: str,
        author: str = "user",
    ) -> ThesisRecord:
        """Invalidate (falsify/close) an existing active thesis."""
        if not rationale or len(rationale.strip()) < 10:
            raise ValueError("Tezi geçersiz kılarken en az 10 karakterlik açıklayıcı gerekçe (rationale) zorunludur.")

        current = self.get_thesis(thesis_id)
        if not current:
            raise ValueError(f"Tez bulunamadı: {thesis_id}")

        if current.status == ThesisStatus.INVALIDATED:
            raise ValueError(f"Tez zaten geçersiz kılınmış: {thesis_id}")

        new_version_id = f"thv_{uuid.uuid4().hex[:12]}"
        new_version_number = current.version_number + 1

        new_record = ThesisRecord(
            version_id=new_version_id,
            thesis_id=current.thesis_id,
            supersedes_id=current.version_id,
            version_number=new_version_number,
            isin=current.isin,
            category=current.category,
            horizon=current.horizon,
            status=ThesisStatus.INVALIDATED,
            title=current.title,
            one_line_summary=current.one_line_summary,
            economic_rationale=current.economic_rationale,
            evidence_pillars=current.evidence_pillars,
            counter_arguments=current.counter_arguments,
            falsification_triggers=current.falsification_triggers,
            benchmark_reference=current.benchmark_reference,
            sources=current.sources,
            target_allocation_pct=current.target_allocation_pct,
            next_review_date=None,
            revision_rationale=rationale.strip(),
            author=author,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        row_dict_for_hash = new_record.to_db_row(computed_hash="")
        row_dict_for_hash.pop("record_hash", None)
        record_hash = compute_thesis_version_hash(row_dict_for_hash)
        row_data = new_record.to_db_row(computed_hash=record_hash)

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO thesis_versions (
                    version_id, thesis_id, supersedes_id, version_number,
                    isin, category, horizon, status, title, one_line_summary,
                    economic_rationale, evidence_pillars_json, counter_arguments,
                    falsification_triggers_json, benchmark_reference, sources_json,
                    target_allocation_pct, next_review_date, revision_rationale,
                    author, created_at, record_hash
                ) VALUES (
                    :version_id, :thesis_id, :supersedes_id, :version_number,
                    :isin, :category, :horizon, :status, :title, :one_line_summary,
                    :economic_rationale, :evidence_pillars_json, :counter_arguments,
                    :falsification_triggers_json, :benchmark_reference, :sources_json,
                    :target_allocation_pct, :next_review_date, :revision_rationale,
                    :author, :created_at, :record_hash
                )
                """,
                row_data,
            )

        try:
            AuditLogger(self.db).log_event(
                actor=author,
                action="THESIS_INVALIDATED",
                entity_type="thesis",
                entity_id=thesis_id,
                payload={
                    "version_id": new_version_id,
                    "supersedes_id": current.version_id,
                    "version_number": new_version_number,
                    "rationale": rationale.strip(),
                    "record_hash": record_hash,
                },
            )
        except Exception as exc:
            logger.warning(f"Audit log yazılamadı: {exc}")

        return ThesisRecord.from_db_row(row_data)

    def get_thesis(self, thesis_id: str) -> Optional[ThesisRecord]:
        """Fetch the current head version of a thesis by thesis_id."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM v_theses_current WHERE thesis_id = ?",
                (thesis_id,),
            ).fetchone()
            if not row:
                return None
            return ThesisRecord.from_db_row(row)
        finally:
            conn.close()

    def get_thesis_by_isin(self, isin: str) -> Optional[ThesisRecord]:
        """Fetch the current head thesis for a given ISIN."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM v_theses_current WHERE isin = ? ORDER BY created_at DESC LIMIT 1",
                (isin.upper(),),
            ).fetchone()
            if not row:
                return None
            return ThesisRecord.from_db_row(row)
        finally:
            conn.close()

    def get_thesis_history(self, thesis_id: str) -> List[ThesisRecord]:
        """Fetch full chronological history of all versions for a thesis."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM thesis_versions WHERE thesis_id = ? ORDER BY version_number ASC",
                (thesis_id,),
            ).fetchall()
            return [ThesisRecord.from_db_row(r) for r in rows]
        finally:
            conn.close()

    def list_theses(
        self,
        isin: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        horizon: Optional[str] = None,
        include_superseded: bool = False,
    ) -> List[ThesisRecord]:
        """List theses matching optional filters."""
        table = "thesis_versions" if include_superseded else "v_theses_current"
        query = f"SELECT * FROM {table} WHERE 1=1"
        params: List[Any] = []

        if isin:
            query += " AND isin = ?"
            params.append(isin.upper())
        if status:
            query += " AND status = ?"
            params.append(status.upper())
        if category:
            query += " AND category = ?"
            params.append(category.upper())
        if horizon:
            query += " AND horizon = ?"
            params.append(horizon.upper())

        query += " ORDER BY created_at DESC"

        conn = self.db.get_connection()
        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [ThesisRecord.from_db_row(r) for r in rows]
        finally:
            conn.close()

    def audit_theses_health(self) -> Dict[str, Any]:
        """Perform monthly thesis health check and review-date auditing."""
        theses = self.list_theses(status="ACTIVE")
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        active_count = len(theses)
        due_for_review = []
        missing_review_date = []
        up_to_date = []

        for t in theses:
            if not t.next_review_date:
                missing_review_date.append({
                    "thesis_id": t.thesis_id,
                    "isin": t.isin,
                    "title": t.title,
                })
            elif t.next_review_date <= today_str:
                due_for_review.append({
                    "thesis_id": t.thesis_id,
                    "isin": t.isin,
                    "title": t.title,
                    "next_review_date": t.next_review_date,
                })
            else:
                up_to_date.append({
                    "thesis_id": t.thesis_id,
                    "isin": t.isin,
                    "title": t.title,
                    "next_review_date": t.next_review_date,
                })

        return {
            "total_active_theses": active_count,
            "due_for_review_count": len(due_for_review),
            "due_for_review": due_for_review,
            "missing_review_date_count": len(missing_review_date),
            "missing_review_date": missing_review_date,
            "up_to_date_count": len(up_to_date),
            "is_all_healthy": len(due_for_review) == 0 and len(missing_review_date) == 0,
        }
