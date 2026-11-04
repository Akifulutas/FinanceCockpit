"""Transaction ledger and incremental ingestion engine (IP-3).

Handles:
- 7-day lookback incremental fetch calculation
- Transaction deduplication and versioning in transaction_versions
- Integration with v_transactions_current
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import uuid

from masa.calc.transaction_classifier import ClassificationStatus, FlowClassification, classify_transaction
from masa.ingestion.models import TransactionItem
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import canonical_json, compute_transaction_version_hash

logger = logging.getLogger(__name__)


def calculate_incremental_from_time(
    conn: sqlite3.Connection,
    overlap_days: int = 7,
    force_full: bool = False,
) -> Optional[str]:
    """Calculate ISO-8601 UTC from_time for incremental transaction fetch.

    If database is empty or force_full is True: returns None (full scan).
    Otherwise: returns max(event_time) - overlap_days.
    """
    if force_full:
        return None

    # Check transaction_versions first, then transaction_observations
    max_time_str = None
    try:
        row = conn.execute("SELECT MAX(event_time) AS max_t FROM transaction_versions").fetchone()
        if row and row["max_t"]:
            max_time_str = str(row["max_t"])
    except Exception:
        pass

    if not max_time_str:
        try:
            row = conn.execute("SELECT MAX(event_time) AS max_t FROM transaction_observations").fetchone()
            if row and row["max_t"]:
                max_time_str = str(row["max_t"])
        except Exception:
            pass

    if not max_time_str:
        return None

    try:
        dt = datetime.fromisoformat(max_time_str.replace("Z", "+00:00"))
        from_dt = (dt - timedelta(days=overlap_days)).astimezone(timezone.utc)
        return from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as exc:
        logger.warning(f"Could not parse max transaction event_time '{max_time_str}': {exc}")
        return None


def serialize_payload(item: Any) -> str:
    """Serialize transaction item to canonical JSON payload."""
    if hasattr(item, "model_dump"):
        raw_dict = item.model_dump(mode="json")
    elif hasattr(item, "__dict__"):
        raw_dict = {
            k: (str(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, datetime) else v))
            for k, v in item.__dict__.items()
            if not k.startswith("_")
        }
    elif isinstance(item, Mapping):
        raw_dict = dict(item)
    else:
        raw_dict = {"repr": str(item)}
    return canonical_json(raw_dict)


def ingest_transaction_versions(
    db: DatabaseManager,
    items: Sequence[Any],
    snapshot_id: Optional[str] = None,
    raw_object_id: Optional[int] = None,
) -> Dict[str, int]:
    """Ingest transactions into transaction_versions with deduplication and versioning.

    Rules:
    - New transaction (broker_tx_id not in DB): insert version = 1, supersedes_id = None.
    - Existing unchanged transaction: skip (deduplicated).
    - Existing changed transaction: insert version = max_version + 1, supersedes_id = previous.
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "total": len(items)}
    if not items:
        return stats

    with db.transaction() as conn:
        for it in items:
            if hasattr(it, "id"):
                broker_tx_id = str(it.id)
                tx_type = str(getattr(it, "type", "UNKNOWN"))
                cash_type = getattr(it, "cash_transaction_type", None)
                sec_type = getattr(it, "security_transaction_type", None)
                sub_type = cash_type or sec_type
                side = getattr(it, "side", None)
                isin = getattr(it, "isin", None)
                desc = getattr(it, "description", None)
                amount_dec = Decimal(str(getattr(it, "amount", 0)))
                currency = str(getattr(it, "currency", "EUR"))
                qty = getattr(it, "quantity", None)
                limit_px = getattr(it, "limit_price", None)
                status = str(getattr(it, "status", "UNKNOWN"))
                is_cancel = 1 if getattr(it, "is_cancellation", False) else 0
                dt_val = getattr(it, "last_event_datetime", None)
            elif isinstance(it, Mapping):
                broker_tx_id = str(it.get("broker_tx_id") or it.get("id", ""))
                tx_type = str(it.get("tx_type") or it.get("type", "UNKNOWN"))
                cash_type = it.get("cash_transaction_type")
                sec_type = it.get("security_transaction_type")
                sub_type = it.get("sub_type") or cash_type or sec_type
                side = it.get("side")
                isin = it.get("isin")
                desc = it.get("description")
                amount_dec = Decimal(str(it.get("amount", 0)))
                currency = str(it.get("currency", "EUR"))
                qty = it.get("quantity")
                limit_px = it.get("limit_price")
                status = str(it.get("status", "UNKNOWN"))
                is_cancel = 1 if it.get("is_cancellation") in (1, True, "1", "True") else 0
                dt_val = it.get("event_time") or it.get("last_event_datetime")
            else:
                continue

            if not broker_tx_id:
                continue

            qty_dec = Decimal(str(qty)) if qty is not None else None
            limit_dec = Decimal(str(limit_px)) if limit_px is not None else None

            if isinstance(dt_val, datetime):
                event_time_str = dt_val.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            elif dt_val:
                event_time_str = str(dt_val)
            else:
                event_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Classification
            cls_res = classify_transaction(it, db=db, conn=conn)
            flow_class = cls_res.classification.value

            cost_impact = cls_res.cost_impact_json
            payload_json = serialize_payload(it)
            created_at = datetime.now(timezone.utc).isoformat()

            # Check existing version
            row = conn.execute(
                """
                SELECT version_id, version_number, status, amount, quantity,
                       limit_price, is_cancellation, event_time, flow_classification
                FROM transaction_versions
                WHERE broker_tx_id = ?
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (broker_tx_id,),
            ).fetchone()

            if row is None:
                # Brand new transaction (Version 1)
                ver_id = f"txv_{uuid.uuid4().hex}"
                values = {
                    "version_id": ver_id,
                    "broker_tx_id": broker_tx_id,
                    "supersedes_id": None,
                    "version_number": 1,
                    "raw_object_id": raw_object_id,
                    "snapshot_id": snapshot_id,
                    "tx_type": tx_type,
                    "sub_type": sub_type,
                    "side": side,
                    "isin": isin,
                    "description": desc,
                    "amount": str(amount_dec),
                    "currency": currency,
                    "quantity": str(qty_dec) if qty_dec is not None else None,
                    "limit_price": str(limit_dec) if limit_dec is not None else None,
                    "status": status,
                    "is_cancellation": is_cancel,
                    "event_time": event_time_str,
                    "settlement_date": None,
                    "flow_classification": flow_class,
                    "cost_impact": cost_impact,
                    "payload_json": payload_json,
                    "created_at": created_at,
                }
                rec_hash = compute_transaction_version_hash(values)
                conn.execute(
                    """
                    INSERT INTO transaction_versions (
                        version_id, broker_tx_id, supersedes_id, version_number,
                        raw_object_id, snapshot_id, tx_type, sub_type, side, isin,
                        description, amount, currency, quantity, limit_price, status,
                        is_cancellation, event_time, settlement_date, flow_classification,
                        cost_impact, payload_json, created_at, record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ver_id, broker_tx_id, None, 1,
                        raw_object_id, snapshot_id, tx_type, sub_type, side, isin,
                        desc, str(amount_dec), currency,
                        str(qty_dec) if qty_dec is not None else None,
                        str(limit_dec) if limit_dec is not None else None,
                        status, is_cancel, event_time_str, None,
                        flow_class, cost_impact, payload_json, created_at, rec_hash,
                    ),
                )
                stats["inserted"] += 1
            else:
                # Compare fields to detect changes
                prev_status = str(row["status"])
                prev_amount = Decimal(str(row["amount"]))
                prev_cancel = int(row["is_cancellation"])
                prev_qty = Decimal(str(row["quantity"])) if row["quantity"] is not None else None
                prev_limit = Decimal(str(row["limit_price"])) if row["limit_price"] is not None else None

                unchanged = (
                    prev_status == status
                    and prev_amount == amount_dec
                    and prev_cancel == is_cancel
                    and prev_qty == qty_dec
                    and prev_limit == limit_dec
                )

                if unchanged:
                    stats["skipped"] += 1
                else:
                    # State or financial value changed -> insert next version with supersedes_id
                    prev_ver_id = str(row["version_id"])
                    next_ver_num = int(row["version_number"]) + 1
                    ver_id = f"txv_{uuid.uuid4().hex}"
                    values = {
                        "version_id": ver_id,
                        "broker_tx_id": broker_tx_id,
                        "supersedes_id": prev_ver_id,
                        "version_number": next_ver_num,
                        "raw_object_id": raw_object_id,
                        "snapshot_id": snapshot_id,
                        "tx_type": tx_type,
                        "sub_type": sub_type,
                        "side": side,
                        "isin": isin,
                        "description": desc,
                        "amount": str(amount_dec),
                        "currency": currency,
                        "quantity": str(qty_dec) if qty_dec is not None else None,
                        "limit_price": str(limit_dec) if limit_dec is not None else None,
                        "status": status,
                        "is_cancellation": is_cancel,
                        "event_time": event_time_str,
                        "settlement_date": None,
                        "flow_classification": flow_class,
                        "cost_impact": cost_impact,
                        "payload_json": payload_json,
                        "created_at": created_at,
                    }
                    rec_hash = compute_transaction_version_hash(values)
                    conn.execute(
                        """
                        INSERT INTO transaction_versions (
                            version_id, broker_tx_id, supersedes_id, version_number,
                            raw_object_id, snapshot_id, tx_type, sub_type, side, isin,
                            description, amount, currency, quantity, limit_price, status,
                            is_cancellation, event_time, settlement_date, flow_classification,
                            cost_impact, payload_json, created_at, record_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ver_id, broker_tx_id, prev_ver_id, next_ver_num,
                            raw_object_id, snapshot_id, tx_type, sub_type, side, isin,
                            desc, str(amount_dec), currency,
                            str(qty_dec) if qty_dec is not None else None,
                            str(limit_dec) if limit_dec is not None else None,
                            status, is_cancel, event_time_str, None,
                            flow_class, cost_impact, payload_json, created_at, rec_hash,
                        ),
                    )
                    stats["updated"] += 1

    return stats


def get_current_transactions(
    db: DatabaseManager,
    isin: Optional[str] = None,
    limit: Optional[int] = None,
    flow_class: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query current active transactions from v_transactions_current view."""
    conn = db.get_connection()
    try:
        sql = "SELECT * FROM v_transactions_current WHERE 1=1"
        params: List[Any] = []
        if isin:
            sql += " AND isin = ?"
            params.append(isin.strip().upper())
        if flow_class:
            sql += " AND flow_classification = ?"
            params.append(flow_class.strip().upper())
        if status:
            sql += " AND status = ?"
            params.append(status.strip().upper())

        sql += " ORDER BY event_time DESC, version_number DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def backfill_unversioned_observations(db: DatabaseManager) -> Dict[str, int]:
    """Safely migrate all unversioned observations from transaction_observations to transaction_versions.

    Fetches observations where broker_tx_id is not yet in transaction_versions,
    ordered by rowid ASC so that historical versions are constructed in chronological order.
    Uses ingest_transaction_versions to generate valid cryptographic record_hashes
    and respect all append-only triggers.
    """
    conn = db.get_connection()
    try:
        query = """
        SELECT 
            tx_row_id, snapshot_id, raw_object_id, broker_tx_id, tx_type,
            cash_transaction_type, security_transaction_type, side, isin,
            description, amount, currency, quantity, limit_price, status,
            is_cancellation, event_time, record_hash
        FROM transaction_observations
        WHERE broker_tx_id NOT IN (
            SELECT broker_tx_id FROM transaction_versions
        )
        ORDER BY rowid ASC
        """
        rows = [dict(r) for r in conn.execute(query).fetchall()]
    finally:
        conn.close()

    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0, "total": 0}

    logger.info(f"Backfilling {len(rows)} unversioned observations into transaction_versions...")
    return ingest_transaction_versions(db, rows)

