"""Corporate Actions Module (IP-3).

Handles:
- Splits, reverse splits, mergers, ISIN changes
- Mandatory approved_by validation and ISO 6166 ISIN validation
- Append-only persistence in corporate_actions table
- In-memory dynamic FIFO lot transformation (never mutates DB records in-place)
- Audit event sealing
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from masa.audit.events import AuditLogger
from masa.identity.isin import validate_isin
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_corporate_action_hash

logger = logging.getLogger(__name__)


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    ISIN_CHANGE = "ISIN_CHANGE"
    MERGER = "MERGER"


class CorporateActionRecord(BaseModel):
    """Pydantic model representing a sealed corporate action entry."""
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(default_factory=lambda: f"ca_{uuid.uuid4().hex[:12]}")
    isin: str
    action_type: CorporateActionType
    ratio: Decimal = Field(gt=Decimal("0"))
    new_isin: Optional[str] = None
    new_ticker: Optional[str] = None
    effective_date: str
    announcement_date: Optional[str] = None
    description: str = Field(min_length=1)
    source: str = "user"
    evidence_json: Optional[str] = None
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    supersedes_id: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    record_hash: Optional[str] = None

    @field_validator("isin")
    @classmethod
    def check_isin(cls, v: str) -> str:
        clean = v.strip().upper()
        validate_isin(clean)
        return clean

    @field_validator("new_isin")
    @classmethod
    def check_new_isin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip().upper()
        validate_isin(clean)
        return clean

    @field_validator("approved_by")
    @classmethod
    def check_approved_by(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("approved_by cannot be empty or whitespace (mandatory authorization).")
        return clean

    @model_validator(mode="after")
    def validate_action_semantics(self) -> CorporateActionRecord:
        if self.action_type in (CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT):
            if self.new_isin is not None:
                raise ValueError(f"{self.action_type.value} must not define new_isin.")
        elif self.action_type in (CorporateActionType.ISIN_CHANGE, CorporateActionType.MERGER):
            if not self.new_isin:
                raise ValueError(f"{self.action_type.value} requires a valid new_isin.")
            if self.new_isin == self.isin:
                raise ValueError(f"{self.action_type.value} requires new_isin to differ from original isin.")
        return self


def register_corporate_action(
    db: DatabaseManager,
    action: CorporateActionRecord,
) -> str:
    """Validate, compute record_hash, insert corporate action into DB, and seal audit event."""
    # Ensure fields are formatted
    created_at = action.created_at or datetime.now(timezone.utc).isoformat()
    approved_at = action.approved_at or datetime.now(timezone.utc).isoformat()

    row_dict = {
        "action_id": action.action_id,
        "action_type": action.action_type.value,
        "announcement_date": action.announcement_date,
        "approved_at": approved_at,
        "approved_by": action.approved_by,
        "created_at": created_at,
        "description": action.description,
        "effective_date": action.effective_date,
        "evidence_json": action.evidence_json,
        "isin": action.isin,
        "new_isin": action.new_isin,
        "new_ticker": action.new_ticker,
        "ratio": str(action.ratio),
        "source": action.source,
        "supersedes_id": action.supersedes_id,
    }
    rec_hash = compute_corporate_action_hash(row_dict)

    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO corporate_actions (
                action_id, isin, action_type, ratio, new_isin, new_ticker,
                effective_date, announcement_date, description, source,
                evidence_json, approved_by, approved_at, supersedes_id,
                created_at, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.action_id,
                action.isin,
                action.action_type.value,
                str(action.ratio),
                action.new_isin,
                action.new_ticker,
                action.effective_date,
                action.announcement_date,
                action.description,
                action.source,
                action.evidence_json,
                action.approved_by,
                approved_at,
                action.supersedes_id,
                created_at,
                rec_hash,
            ),
        )

    # Log audit event
    try:
        AuditLogger(db).log_event(
            actor=action.approved_by,
            action="CORPORATE_ACTION_REGISTERED",
            entity_type="corporate_action",
            entity_id=action.action_id,
            payload={
                "action_id": action.action_id,
                "isin": action.isin,
                "action_type": action.action_type.value,
                "ratio": str(action.ratio),
                "new_isin": action.new_isin,
                "effective_date": action.effective_date,
                "approved_by": action.approved_by,
                "record_hash": rec_hash,
            },
        )
    except Exception as exc:
        logger.warning(f"Could not log audit event for corporate action: {exc}")

    return action.action_id


def list_corporate_actions(
    db: DatabaseManager,
    isin: Optional[str] = None,
) -> List[CorporateActionRecord]:
    """Retrieve active (unsuperseded) corporate actions from database."""
    conn = db.get_connection()
    try:
        sql = """
            SELECT ca.* FROM corporate_actions ca
            WHERE NOT EXISTS (
                SELECT 1 FROM corporate_actions child
                WHERE child.supersedes_id = ca.action_id
            )
        """
        params: List[Any] = []
        if isin:
            clean_isin = isin.strip().upper()
            sql += " AND (ca.isin = ? OR ca.new_isin = ?)"
            params.extend([clean_isin, clean_isin])

        sql += " ORDER BY ca.effective_date ASC, ca.action_id ASC"
        rows = conn.execute(sql, params).fetchall()

        results: List[CorporateActionRecord] = []
        for r in rows:
            results.append(
                CorporateActionRecord(
                    action_id=r["action_id"],
                    isin=r["isin"],
                    action_type=CorporateActionType(r["action_type"]),
                    ratio=Decimal(str(r["ratio"])),
                    new_isin=r["new_isin"],
                    new_ticker=r["new_ticker"],
                    effective_date=r["effective_date"],
                    announcement_date=r["announcement_date"],
                    description=r["description"],
                    source=r["source"],
                    evidence_json=r["evidence_json"],
                    approved_by=r["approved_by"],
                    approved_at=r["approved_at"],
                    supersedes_id=r["supersedes_id"],
                    created_at=r["created_at"],
                    record_hash=r["record_hash"],
                )
            )
        return results
    finally:
        conn.close()


def transform_lots_for_corporate_action(
    lots: Sequence[Any],
    action: CorporateActionRecord,
) -> Tuple[List[Dict[str, Any]], str]:
    """Transform FIFO lots dynamically in memory without altering database records.

    For SPLIT / REVERSE_SPLIT:
        shares' = shares * ratio
        cost_per_share' = cost_per_share / ratio
        total cost basis (shares * cost_per_share) is preserved!
        acquisition timestamp is preserved!

    For ISIN_CHANGE / MERGER:
        shares' = shares * ratio
        lots belong to new_isin, timestamp & unit costs are preserved.

    Returns:
        (transformed_lots, target_isin)
    """
    transformed: List[Dict[str, Any]] = []
    ratio = action.ratio
    target_isin = action.new_isin if action.action_type in (
        CorporateActionType.ISIN_CHANGE, CorporateActionType.MERGER
    ) and action.new_isin else action.isin

    for lot in lots:
        if isinstance(lot, dict):
            sh = Decimal(str(lot.get("shares", 0)))
            cps = Decimal(str(lot.get("cost_per_share", 0)))
            ts = lot.get("timestamp") or lot.get("acquired_at")
            lid = lot.get("lot_id") or lot.get("id")
        elif hasattr(lot, "shares"):
            sh = Decimal(str(getattr(lot, "shares", 0)))
            cps = Decimal(str(getattr(lot, "cost_per_share", 0)))
            ts = getattr(lot, "timestamp", None) or getattr(lot, "acquired_at", None)
            lid = getattr(lot, "lot_id", None) or getattr(lot, "id", None)
        else:
            continue

        if action.action_type in (CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT):
            new_shares = sh * ratio
            new_cps = cps / ratio if ratio != Decimal("0") else Decimal("0")
        else:
            new_shares = sh * ratio
            new_cps = cps / ratio if ratio != Decimal("0") else cps

        transformed.append({
            "lot_id": lid,
            "shares": new_shares,
            "cost_per_share": new_cps,
            "total_cost": new_shares * new_cps,
            "timestamp": ts,
            "isin": target_isin,
            "transformed_by_action": action.action_id,
        })

    return transformed, target_isin
