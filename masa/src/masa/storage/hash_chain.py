"""SHA-256 canonical hashing and chain verification (schema v2).

Her alt kaydin ozeti, kayit kimligi ve record_hash disindaki TUM sutunlarin
kanonik JSON'undan hesaplanir. Dogrulama saklanan ozete guvenmez: her satirin
ozetini alanlardan yeniden hesaplar, satir sayisini item_count ile karsilastirir,
sonra baslik ozetini ve zincir baglantisini kontrol eder.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

GENESIS_HASH: str = "0" * 64
HASH_SCHEME = "masa-v2-canonical-json"

# snapshot_type -> (child table, primary key, hashed columns in fixed order)
CHILD_SPECS: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "quotes": ("quotes", "quote_id", (
        "snapshot_id", "raw_object_id", "isin", "alias", "currency", "bid", "ask",
        "provider_mid", "computed_mid", "spread", "spread_pct", "quote_timestamp",
        "retrieved_at", "quote_age_seconds", "source", "exchange", "provider_outdated",
        "quality_status",
    )),
    "portfolio": ("position_observations", "position_id", (
        "snapshot_id", "raw_object_id", "isin", "display_name", "security_type", "quantity",
        "blocked_quantity", "pending_quantity", "unit_price_displayed", "value_eur",
        "currency", "broker_cost_basis", "quote_timestamp", "provider_outdated", "observed_at",
    )),
    "cash": ("cash_observations", "cash_id", (
        "snapshot_id", "raw_object_id", "account_id_masked", "currency", "settled_cash",
        "unsettled_cash", "accrued_cash", "total_cash", "buying_power",
        "pending_buy_orders_amount", "possible_taxes", "observed_at",
    )),
    "transactions": ("transaction_observations", "tx_row_id", (
        "snapshot_id", "raw_object_id", "broker_tx_id", "tx_type", "cash_transaction_type",
        "security_transaction_type", "side", "isin", "description", "amount", "currency",
        "quantity", "limit_price", "status", "is_cancellation", "event_time",
    )),
    "series": ("series_points", "point_id", (
        "snapshot_id", "raw_object_id", "series_key", "series_kind", "point_time", "value",
    )),
}

SNAPSHOT_HEADER_FIELDS: Tuple[str, ...] = (
    "snapshot_id", "run_id", "snapshot_type", "collection_started_at",
    "collection_completed_at", "raw_object_id", "source", "item_count",
    "quality_status", "connector_version", "prev_hash",
)


def canonical_json(obj: Any) -> str:
    """Produce key-sorted, compact, UTF-8 canonical JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_value(value: Any) -> Optional[str]:
    """Storage normal form: every value is TEXT (or NULL). Decimals stay lossless."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def compute_record_hash(snapshot_type: str, values: Mapping[str, Any]) -> str:
    _table, _pk, columns = CHILD_SPECS[snapshot_type]
    payload = {"scheme": HASH_SCHEME, "type": snapshot_type,
               "fields": {c: normalize_value(values.get(c)) for c in columns}}
    return sha256_text(canonical_json(payload))


def compute_header_hash(header: Mapping[str, Any], child_hashes: Sequence[str]) -> str:
    payload = {"scheme": HASH_SCHEME,
               "header": {f: normalize_value(header.get(f)) for f in SNAPSHOT_HEADER_FIELDS},
               "children": list(child_hashes)}
    return sha256_text(canonical_json(payload))


class HashChainEngine:
    """Verifies the snapshot chain (with field-level recomputation) and the audit chain."""

    compute_record_hash = staticmethod(compute_record_hash)
    compute_header_hash = staticmethod(compute_header_hash)

    @staticmethod
    def compute_audit_event_hash(
        prev_hash: str, event_uuid: str, event_time: str, actor: str, action: str,
        entity_type: str, entity_id: str, payload_sha256: str,
    ) -> str:
        payload = (
            f"{prev_hash}|{event_uuid}|{event_time}|{actor}|{action}|"
            f"{entity_type}|{entity_id}|{payload_sha256}"
        )
        return sha256_text(payload)

    @classmethod
    def verify_audit_chain(cls, conn: sqlite3.Connection) -> Tuple[bool, Optional[str]]:
        rows = conn.execute(
            """SELECT event_id, event_uuid, event_time, actor, action, entity_type, entity_id,
                      payload_json, payload_sha256, prev_hash, curr_hash
               FROM audit_events ORDER BY event_id ASC"""
        ).fetchall()
        expected_prev = GENESIS_HASH
        for row in rows:
            if row["prev_hash"] != expected_prev:
                return False, (f"Audit chain broken at event_id {row['event_id']}: "
                               f"expected prev_hash={expected_prev}, found={row['prev_hash']}")
            if sha256_text(row["payload_json"]) != row["payload_sha256"]:
                return False, f"Audit payload mismatch at event_id {row['event_id']}"
            calculated = cls.compute_audit_event_hash(
                row["prev_hash"], row["event_uuid"], row["event_time"], row["actor"],
                row["action"], row["entity_type"], row["entity_id"], row["payload_sha256"],
            )
            if row["curr_hash"] != calculated:
                return False, (f"Audit hash mismatch at event_id {row['event_id']}: "
                               f"calculated={calculated}, stored={row['curr_hash']}")
            expected_prev = row["curr_hash"]
        return True, None

    @classmethod
    def verify_snapshot_chain(cls, conn: sqlite3.Connection) -> Tuple[bool, Optional[str]]:
        snapshots = conn.execute("SELECT * FROM snapshots ORDER BY rowid ASC").fetchall()
        expected_prev = GENESIS_HASH
        for snap in snapshots:
            sid = snap["snapshot_id"]
            if snap["prev_hash"] != expected_prev:
                return False, (f"Snapshot chain broken at {sid}: expected prev_hash="
                               f"{expected_prev}, found={snap['prev_hash']}")
            stype = snap["snapshot_type"]
            if stype not in CHILD_SPECS:
                return False, f"Unknown snapshot_type {stype!r} at {sid}"
            table, pk, columns = CHILD_SPECS[stype]
            rows = conn.execute(
                f"SELECT {pk}, record_hash, {', '.join(columns)} FROM {table} "
                f"WHERE snapshot_id = ? ORDER BY {pk} ASC", (sid,)
            ).fetchall()
            if len(rows) != snap["item_count"]:
                return False, (f"Child count mismatch at {sid}: item_count={snap['item_count']}, "
                               f"found={len(rows)}")
            child_hashes: List[str] = []
            for r in rows:
                recomputed = compute_record_hash(stype, {c: r[c] for c in columns})
                if recomputed != r["record_hash"]:
                    return False, (f"Record tampered in {table} {pk}={r[pk]} (snapshot {sid}): "
                                   f"field-level hash {recomputed[:12]}… != stored {str(r['record_hash'])[:12]}…")
                child_hashes.append(recomputed)
            calculated = compute_header_hash({f: snap[f] for f in SNAPSHOT_HEADER_FIELDS}, child_hashes)
            if snap["curr_hash"] != calculated:
                return False, (f"Snapshot curr_hash mismatch at {sid}: calculated={calculated}, "
                               f"stored={snap['curr_hash']}")
            expected_prev = snap["curr_hash"]
        return True, None

    @classmethod
    def verify_raw_objects(cls, conn: sqlite3.Connection) -> Tuple[bool, Optional[str]]:
        for r in conn.execute("SELECT raw_id, payload_sha256, payload_text FROM raw_objects"):
            if sha256_text(r["payload_text"]) != r["payload_sha256"]:
                return False, f"raw_objects raw_id={r['raw_id']} icerigi ozetiyle uyusmuyor"
        return True, None


def compute_event_hash(
    event_id: Any, event_time: str, actor: str, action: str, entity_type: str,
    entity_id: str, payload_hash: str, prev_hash: str,
) -> str:
    """Helper for audit event hash computation (event_id = event_uuid)."""
    return HashChainEngine.compute_audit_event_hash(
        prev_hash, str(event_id), event_time, actor, action, entity_type, entity_id, payload_hash)


def verify_hash_chain(conn: sqlite3.Connection) -> bool:
    valid, _ = HashChainEngine.verify_audit_chain(conn)
    return valid


def compute_transaction_version_hash(values: Mapping[str, Any]) -> str:
    row_dict = {
        "amount": str(values["amount"]),
        "broker_tx_id": str(values["broker_tx_id"]),
        "cost_impact": str(values["cost_impact"]) if values.get("cost_impact") is not None else None,
        "created_at": str(values["created_at"]),
        "currency": str(values.get("currency", "EUR")),
        "description": str(values["description"]) if values.get("description") is not None else None,
        "event_time": str(values["event_time"]),
        "flow_classification": str(values.get("flow_classification", "UNCLASSIFIED")),
        "is_cancellation": 1 if values.get("is_cancellation") in (1, True, "1", "True") else 0,
        "isin": str(values["isin"]) if values.get("isin") is not None else None,
        "limit_price": str(values["limit_price"]) if values.get("limit_price") is not None else None,
        "payload_json": str(values.get("payload_json", "{}")),
        "quantity": str(values["quantity"]) if values.get("quantity") is not None else None,
        "raw_object_id": int(values["raw_object_id"]) if values.get("raw_object_id") is not None else None,
        "settlement_date": str(values["settlement_date"]) if values.get("settlement_date") is not None else None,
        "side": str(values["side"]) if values.get("side") is not None else None,
        "snapshot_id": str(values["snapshot_id"]) if values.get("snapshot_id") is not None else None,
        "status": str(values["status"]),
        "sub_type": str(values["sub_type"]) if values.get("sub_type") is not None else None,
        "supersedes_id": str(values["supersedes_id"]) if values.get("supersedes_id") is not None else None,
        "tx_type": str(values["tx_type"]),
        "version_id": str(values["version_id"]),
        "version_number": int(values.get("version_number", 1)),
    }
    return sha256_text(canonical_json(row_dict))


def compute_corporate_action_hash(values: Mapping[str, Any]) -> str:
    row_dict = {
        "action_id": str(values["action_id"]),
        "action_type": str(values["action_type"]),
        "announcement_date": str(values["announcement_date"]) if values.get("announcement_date") is not None else None,
        "approved_at": str(values["approved_at"]),
        "approved_by": str(values["approved_by"]),
        "created_at": str(values["created_at"]),
        "description": str(values["description"]),
        "effective_date": str(values["effective_date"]),
        "evidence_json": str(values["evidence_json"]) if values.get("evidence_json") is not None else None,
        "isin": str(values["isin"]),
        "new_isin": str(values["new_isin"]) if values.get("new_isin") is not None else None,
        "new_ticker": str(values["new_ticker"]) if values.get("new_ticker") is not None else None,
        "ratio": str(values["ratio"]),
        "source": str(values.get("source", "user")),
        "supersedes_id": str(values["supersedes_id"]) if values.get("supersedes_id") is not None else None,
    }
    return sha256_text(canonical_json(row_dict))


def compute_reconciliation_hash(values: Mapping[str, Any]) -> str:
    row_dict = {
        "broker_snapshot_id": str(values["broker_snapshot_id"]) if values.get("broker_snapshot_id") is not None else None,
        "cash_gap_eur": str(values["cash_gap_eur"]) if values.get("cash_gap_eur") is not None else None,
        "cash_match": 1 if values.get("cash_match") in (1, True, "1", "True") else 0,
        "cash_observation_id": int(values["cash_observation_id"]) if values.get("cash_observation_id") is not None else None,
        "cost_basis_match": 1 if values.get("cost_basis_match") in (1, True, "1", "True") else 0,
        "created_at": str(values["created_at"]),
        "discrepancies_count": int(values.get("discrepancies_count", 0)),
        "discrepancies_json": str(values.get("discrepancies_json", "[]")),
        "notes": str(values["notes"]) if values.get("notes") is not None else None,
        "observation_lag_seconds": str(values["observation_lag_seconds"]) if values.get("observation_lag_seconds") is not None else None,
        "reconciliation_id": str(values["reconciliation_id"]),
        "reconciliation_time": str(values["reconciliation_time"]),
        "reconciliation_type": str(values["reconciliation_type"]),
        "run_id": str(values["run_id"]),
        "shares_match": 1 if values.get("shares_match") in (1, True, "1", "True") else 0,
        "status": str(values["status"]),
        "valuation_match": 1 if values.get("valuation_match") in (1, True, "1", "True") else 0,
    }
    return sha256_text(canonical_json(row_dict))


def compute_holdings_set_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a holdings_set row."""
    vals = dict(values)
    row_dict = {
        "as_of_date": str(vals["as_of_date"]),
        "created_at": str(vals["created_at"]),
        "isin": str(vals["isin"]),
        "provider": str(vals["provider"]),
        "set_id": str(vals["set_id"]),
        "source_file": str(vals["source_file"]),
        "total_records": int(vals["total_records"]),
        "total_weight_pct": str(vals["total_weight_pct"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_holding_item_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a holding_item row."""
    vals = dict(values)
    row_dict = {
        "asset_class": str(vals["asset_class"]) if vals.get("asset_class") is not None else None,
        "constituent_isin": str(vals["constituent_isin"]) if vals.get("constituent_isin") is not None else None,
        "constituent_name": str(vals["constituent_name"]),
        "constituent_ticker": str(vals["constituent_ticker"]) if vals.get("constituent_ticker") is not None else None,
        "country": str(vals["country"]) if vals.get("country") is not None else None,
        "created_at": str(vals["created_at"]),
        "currency": str(vals["currency"]) if vals.get("currency") is not None else None,
        "item_id": str(vals["item_id"]),
        "item_order": int(vals["item_order"]),
        "market_value": str(vals["market_value"]) if vals.get("market_value") is not None else None,
        "sector": str(vals["sector"]) if vals.get("sector") is not None else None,
        "set_id": str(vals["set_id"]),
        "shares_held": str(vals["shares_held"]) if vals.get("shares_held") is not None else None,
        "weight_pct": str(vals["weight_pct"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_thesis_version_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a thesis_versions row."""
    vals = dict(values)
    row_dict = {
        "author": str(vals.get("author", "user")),
        "benchmark_reference": str(vals.get("benchmark_reference", "araştırma referansı")),
        "category": str(vals["category"]),
        "counter_arguments": str(vals["counter_arguments"]) if vals.get("counter_arguments") is not None else None,
        "created_at": str(vals["created_at"]),
        "economic_rationale": str(vals["economic_rationale"]),
        "evidence_pillars_json": str(vals.get("evidence_pillars_json", "[]")),
        "falsification_triggers_json": str(vals.get("falsification_triggers_json", "[]")),
        "horizon": str(vals["horizon"]),
        "isin": str(vals["isin"]),
        "next_review_date": str(vals["next_review_date"]) if vals.get("next_review_date") is not None else None,
        "one_line_summary": str(vals["one_line_summary"]),
        "revision_rationale": str(vals["revision_rationale"]) if vals.get("revision_rationale") is not None else None,
        "sources_json": str(vals.get("sources_json", "[]")),
        "status": str(vals.get("status", "ACTIVE")),
        "supersedes_id": str(vals["supersedes_id"]) if vals.get("supersedes_id") is not None else None,
        "target_allocation_pct": str(vals["target_allocation_pct"]) if vals.get("target_allocation_pct") is not None else None,
        "thesis_id": str(vals["thesis_id"]),
        "title": str(vals["title"]),
        "version_id": str(vals["version_id"]),
        "version_number": int(vals.get("version_number", 1)),
    }
    return sha256_text(canonical_json(row_dict))


compute_thesis_hash = compute_thesis_version_hash


def compute_forecast_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a forecast_entries row."""
    vals = dict(values)
    row_dict = {
        "confidence_pct": str(vals["confidence_pct"]),
        "created_at": str(vals["created_at"]),
        "direction": str(vals["direction"]),
        "forecast_id": str(vals["forecast_id"]),
        "forecast_type": str(vals.get("forecast_type", "DAILY_CLOSE")),
        "isin": str(vals["isin"]),
        "model_id": str(vals["model_id"]),
        "reference_price": str(vals["reference_price"]),
        "target_date": str(vals["target_date"]),
        "target_price": str(vals["target_price"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_settlement_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a settlements row."""
    vals = dict(values)
    row_dict = {
        "actual_close_price": str(vals["actual_close_price"]),
        "direction_hit": 1 if vals.get("direction_hit") in (1, True, "1", "True") else 0,
        "error_eur": str(vals["error_eur"]),
        "error_pct": str(vals["error_pct"]),
        "forecast_id": str(vals["forecast_id"]),
        "isin": str(vals["isin"]),
        "settled_at": str(vals["settled_at"]),
        "settlement_date": str(vals["settlement_date"]),
        "settlement_id": str(vals["settlement_id"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_source_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a sources row."""
    vals = dict(values)
    row_dict = {
        "content_sha256": str(vals["content_sha256"]),
        "created_at": str(vals["created_at"]),
        "publication_date": str(vals["publication_date"]) if vals.get("publication_date") is not None else None,
        "publisher": str(vals["publisher"]),
        "raw_object_id": str(vals["raw_object_id"]) if vals.get("raw_object_id") is not None else None,
        "retrieved_at": str(vals["retrieved_at"]),
        "source_id": str(vals["source_id"]),
        "source_type": str(vals["source_type"]),
        "title": str(vals["title"]),
        "url_or_path": str(vals["url_or_path"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_evidence_bundle_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for an evidence_bundles row."""
    vals = dict(values)
    row_dict = {
        "as_of_date": str(vals["as_of_date"]),
        "bundle_id": str(vals["bundle_id"]),
        "claims_count": int(vals.get("claims_count", 0)),
        "created_at": str(vals["created_at"]),
        "instrument_id": str(vals["instrument_id"]),
        "metrics_count": int(vals.get("metrics_count", 0)),
        "model_id": str(vals.get("model_id", "user")),
        "run_id": str(vals["run_id"]) if vals.get("run_id") is not None else None,
    }
    return sha256_text(canonical_json(row_dict))


def compute_claim_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a claims row."""
    vals = dict(values)
    row_dict = {
        "bundle_id": str(vals["bundle_id"]),
        "claim_id": str(vals["claim_id"]),
        "claim_text": str(vals["claim_text"]),
        "claim_type": str(vals.get("claim_type", "fact")),
        "confidence_pct": str(vals.get("confidence_pct", "100.00")),
        "created_at": str(vals["created_at"]),
        "instrument_id": str(vals["instrument_id"]),
        "page_num": int(vals["page_num"]) if vals.get("page_num") is not None else None,
        "quote_verbatim": str(vals["quote_verbatim"]),
        "section_ref": str(vals["section_ref"]) if vals.get("section_ref") is not None else None,
        "source_id": str(vals["source_id"]),
        "verification_status": str(vals.get("verification_status", "VERIFIED")),
    }
    return sha256_text(canonical_json(row_dict))


def compute_metric_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a metrics row."""
    vals = dict(values)
    row_dict = {
        "bundle_id": str(vals["bundle_id"]) if vals.get("bundle_id") is not None else None,
        "created_at": str(vals["created_at"]),
        "instrument_id": str(vals["instrument_id"]),
        "metric_id": str(vals["metric_id"]),
        "metric_name": str(vals["metric_name"]),
        "period_end": str(vals["period_end"]) if vals.get("period_end") is not None else None,
        "period_start": str(vals["period_start"]) if vals.get("period_start") is not None else None,
        "source_id": str(vals["source_id"]),
        "unit": str(vals["unit"]),
        "value": str(vals["value"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_model_registry_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a model_registry row."""
    vals = dict(values)
    row_dict = {
        "access_tier": str(vals["access_tier"]),
        "created_at": str(vals["created_at"]),
        "last_verified_at": str(vals["last_verified_at"]) if vals.get("last_verified_at") is not None else None,
        "model_id": str(vals["model_id"]),
        "model_name": str(vals["model_name"]),
        "privacy_class": str(vals.get("privacy_class", "confidential_anonymized")),
        "provider": str(vals["provider"]),
        "quota_info": str(vals["quota_info"]) if vals.get("quota_info") is not None else None,
        "region_compliance": str(vals.get("region_compliance", "EU_COMPLIANT")),
        "status": str(vals.get("status", "discovered")),
    }
    return sha256_text(canonical_json(row_dict))


def compute_model_evaluation_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a model_evaluations row."""
    vals = dict(values)
    row_dict = {
        "created_at": str(vals["created_at"]),
        "critical_error_passed": int(vals.get("critical_error_passed", 0)),
        "eval_dataset_version": str(vals["eval_dataset_version"]),
        "eval_metrics_json": str(vals["eval_metrics_json"]),
        "evaluation_id": str(vals["evaluation_id"]),
        "is_champion": int(vals.get("is_champion", 0)),
        "model_id": str(vals["model_id"]),
        "score_pct": str(vals["score_pct"]),
        "task_category": str(vals["task_category"]),
    }
    return sha256_text(canonical_json(row_dict))


def compute_model_run_hash(values: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 hash for a model_runs row."""
    vals = dict(values)
    row_dict = {
        "created_at": str(vals["created_at"]),
        "deep_model_id": str(vals["deep_model_id"]),
        "parent_run_id": str(vals["parent_run_id"]) if vals.get("parent_run_id") is not None else None,
        "prompt_hash": str(vals["prompt_hash"]),
        "quick_model_id": str(vals["quick_model_id"]),
        "route_label": str(vals["route_label"]),
        "run_id": str(vals["run_id"]),
        "selection_rationale": str(vals["selection_rationale"]),
        "status": str(vals.get("status", "completed")),
        "task_name": str(vals["task_name"]),
        "tools_used": str(vals["tools_used"]),
    }
    return sha256_text(canonical_json(row_dict))





