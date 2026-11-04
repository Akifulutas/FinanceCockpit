"""Financial flow and cost classification engine for transaction ledger (IP-3).

Classifies 21 Scalable Capital transaction types + corporate actions into:
- EXTERNAL_INFLOW
- EXTERNAL_OUTFLOW
- INTERNAL_TRADE
- INCOME
- COST
- NEUTRAL

Decomposes gross, net, fee, and tax amounts.
Enforces fail-safe zero-hallucination protocol: unknown or unsupported transaction types
are marked NEEDS_REVIEW and logged as TRANSACTION_CLASSIFICATION_FAILED in AuditLogger.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
import logging
import sqlite3
from typing import Any, Dict, Mapping, Optional, Union

from masa.audit.events import AuditLogger
from masa.storage.db import DatabaseManager


logger = logging.getLogger(__name__)


class FlowClassification(str, Enum):
    EXTERNAL_INFLOW = "EXTERNAL_INFLOW"
    EXTERNAL_OUTFLOW = "EXTERNAL_OUTFLOW"
    INTERNAL_TRADE = "INTERNAL_TRADE"
    INCOME = "INCOME"
    COST = "COST"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class ClassificationStatus(str, Enum):
    CLASSIFIED = "CLASSIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


SUPPORTED_SCALABLE_TYPES = {
    "BUY",
    "SELL",
    "SAVINGS_PLAN",
    "DEPOSIT",
    "WITHDRAWAL",
    "DISTRIBUTION",
    "FEE",
    "INTEREST",
    "TAX",
    "TAX_RETURN",
    "SWAP_IN",
    "SWAP_OUT",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "CURRENCY_SWITCH_BUY",
    "CURRENCY_SWITCH_SELL",
    "CASH_TRANSFER_IN",
    "CASH_TRANSFER_OUT",
    "POCKET_MONEY",
    "REINVESTMENT",
    "REINVESTMENT_DISTRIBUTION",
    "REINVESTMENT_POCKET_MONEY",
}

SUPPORTED_CORPORATE_TYPES = {
    "CORPORATE_ACTION",
    "SPLIT",
    "REVERSE_SPLIT",
    "ISIN_CHANGE",
    "MERGER",
}


@dataclass(frozen=True)
class ClassificationResult:
    classification: FlowClassification
    status: ClassificationStatus
    gross_amount: Optional[Decimal]
    net_amount: Decimal
    fee_amount: Decimal
    tax_amount: Decimal
    affects_twr: bool
    affects_mwr: bool
    cost_impact_json: str
    resolved_type: str
    reason: Optional[str] = None


def resolve_effective_type(
    tx_type: str,
    cash_type: Optional[str] = None,
    sec_type: Optional[str] = None,
    side: Optional[str] = None,
) -> str:
    """Resolve the canonical specific type from broad types and subtypes."""
    t_upper = (tx_type or "").strip().upper()
    c_upper = (cash_type or "").strip().upper()
    s_upper = (sec_type or "").strip().upper()
    side_upper = (side or "").strip().upper()

    if t_upper in SUPPORTED_SCALABLE_TYPES or t_upper in SUPPORTED_CORPORATE_TYPES:
        return t_upper
    if t_upper == "SECURITY_TRANSACTION":
        if s_upper in SUPPORTED_SCALABLE_TYPES:
            return s_upper
        if side_upper in ("BUY", "SELL"):
            return side_upper
        return s_upper or side_upper or "SECURITY_TRANSACTION"
    if t_upper == "CASH_TRANSACTION":
        if c_upper in SUPPORTED_SCALABLE_TYPES:
            return c_upper
        return c_upper or "CASH_TRANSACTION"

    return t_upper or "UNKNOWN"


def classify_transaction(
    item_or_dict: Any,
    db: Optional[Union[DatabaseManager, sqlite3.Connection]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> ClassificationResult:
    """Classify a transaction item or dictionary into financial flow and cost decomposition.

    If unknown or unsupported type is encountered:
    - classification = UNKNOWN
    - status = NEEDS_REVIEW
    - audit event TRANSACTION_CLASSIFICATION_FAILED is logged if db or conn is supplied
    """
    if hasattr(item_or_dict, "type"):
        # Pydantic or dataclass TransactionItem
        raw_type = getattr(item_or_dict, "type", "")
        cash_type = getattr(item_or_dict, "cash_transaction_type", None)
        sec_type = getattr(item_or_dict, "security_transaction_type", None)
        side = getattr(item_or_dict, "side", None)
        desc = getattr(item_or_dict, "description", "") or ""
        amount_val = getattr(item_or_dict, "amount", 0)
        qty_val = getattr(item_or_dict, "quantity", None)
        limit_val = getattr(item_or_dict, "limit_price", None)
        tx_id = getattr(item_or_dict, "id", "") or getattr(item_or_dict, "broker_tx_id", "")
    elif isinstance(item_or_dict, Mapping):
        raw_type = item_or_dict.get("tx_type") or item_or_dict.get("type", "")
        cash_type = item_or_dict.get("cash_transaction_type")
        sec_type = item_or_dict.get("security_transaction_type")
        side = item_or_dict.get("side")
        desc = item_or_dict.get("description") or ""
        amount_val = item_or_dict.get("amount", 0)
        qty_val = item_or_dict.get("quantity")
        limit_val = item_or_dict.get("limit_price")
        tx_id = item_or_dict.get("broker_tx_id") or item_or_dict.get("id", "")
    else:
        raw_type = ""
        cash_type = None
        sec_type = None
        side = None
        desc = ""
        amount_val = 0
        qty_val = None
        limit_val = None
        tx_id = ""

    amount = Decimal(str(amount_val or "0"))
    quantity = Decimal(str(qty_val)) if qty_val is not None else None
    limit_price = Decimal(str(limit_val)) if limit_val is not None else None

    eff_type = resolve_effective_type(raw_type, cash_type, sec_type, side)

    # Cost decomposition defaults
    gross: Optional[Decimal] = None
    fee = Decimal("0")
    tax = Decimal("0")
    net = amount

    # Validate against supported universe
    if eff_type not in SUPPORTED_SCALABLE_TYPES and eff_type not in SUPPORTED_CORPORATE_TYPES:
        status = ClassificationStatus.NEEDS_REVIEW
        flow = FlowClassification.UNKNOWN
        reason = f"Desteklenmeyen veya tanımlanmamış işlem tipi: {eff_type} (raw={raw_type})"

        target_db = conn if conn is not None else db
        if target_db is not None:
            try:
                AuditLogger(target_db).log_event(
                    actor="masa.calc.transaction_classifier",
                    action="TRANSACTION_CLASSIFICATION_FAILED",
                    entity_type="transaction",
                    entity_id=str(tx_id),
                    payload={
                        "broker_tx_id": str(tx_id),
                        "eff_type": eff_type,
                        "raw_type": str(raw_type),
                        "cash_type": str(cash_type),
                        "sec_type": str(sec_type),
                        "amount": str(amount),
                        "reason": reason,
                    },
                )
            except Exception as exc:
                logger.warning(f"Classification failure audit event could not be logged: {exc}")

        cost_dict = {
            "gross": None,

            "net": str(net),
            "fee": str(fee),
            "tax": str(tax),
        }
        return ClassificationResult(
            classification=flow,
            status=status,
            gross_amount=gross,
            net_amount=net,
            fee_amount=fee,
            tax_amount=tax,
            affects_twr=False,
            affects_mwr=False,
            cost_impact_json=json.dumps(cost_dict, separators=(",", ":")),
            resolved_type=eff_type,
            reason=reason,
        )

    # Type-specific rules
    status = ClassificationStatus.CLASSIFIED
    reason = None
    affects_twr = False
    affects_mwr = False

    if eff_type in ("BUY", "SECURITY_TRANSACTION"):
        flow = FlowClassification.INTERNAL_TRADE
        if quantity is not None and limit_price is not None:
            gross = quantity * limit_price
            if abs(amount) > gross:
                fee = abs(amount) - gross
        else:
            gross = abs(amount)

    elif eff_type == "SELL":
        flow = FlowClassification.INTERNAL_TRADE
        if quantity is not None and limit_price is not None:
            gross = quantity * limit_price
            if gross > abs(amount):
                fee = gross - abs(amount)
        else:
            gross = abs(amount)

    elif eff_type == "SAVINGS_PLAN":
        # Check description for direct SEPA bank funding
        desc_lower = (desc or "").lower()
        if any(tok in desc_lower for tok in ("sepa", "lastschrift", "bank")):
            flow = FlowClassification.EXTERNAL_INFLOW
            affects_twr = True
            affects_mwr = True
        else:
            flow = FlowClassification.INTERNAL_TRADE
        if quantity is not None and limit_price is not None:
            gross = quantity * limit_price
            if abs(amount) > gross:
                fee = abs(amount) - gross
        else:
            gross = abs(amount)

    elif eff_type in ("DEPOSIT", "CASH_TRANSFER_IN", "TRANSFER_IN"):
        flow = FlowClassification.EXTERNAL_INFLOW
        gross = abs(amount)
        net = abs(amount)
        affects_twr = True
        affects_mwr = True

    elif eff_type in ("WITHDRAWAL", "CASH_TRANSFER_OUT", "TRANSFER_OUT"):
        flow = FlowClassification.EXTERNAL_OUTFLOW
        gross = abs(amount)
        net = -abs(amount)
        affects_twr = True
        affects_mwr = True

    elif eff_type in ("DISTRIBUTION", "INTEREST", "REINVESTMENT_DISTRIBUTION"):
        flow = FlowClassification.INCOME
        gross = abs(amount)
        net = abs(amount)

    elif eff_type == "REINVESTMENT":
        flow = FlowClassification.INCOME
        gross = abs(amount)

    elif eff_type in ("CURRENCY_SWITCH_BUY", "CURRENCY_SWITCH_SELL", "POCKET_MONEY", "REINVESTMENT_POCKET_MONEY"):
        flow = FlowClassification.INTERNAL_TRADE
        gross = abs(amount)

    elif eff_type == "FEE":
        flow = FlowClassification.COST
        fee = abs(amount)
        gross = abs(amount)

    elif eff_type == "TAX":
        flow = FlowClassification.COST
        tax = abs(amount)
        gross = abs(amount)

    elif eff_type == "TAX_RETURN":
        flow = FlowClassification.COST
        tax = -abs(amount)  # negative cost (recovery)
        gross = abs(amount)

    elif eff_type in ("SWAP_IN", "SWAP_OUT", "CORPORATE_ACTION", "SPLIT", "REVERSE_SPLIT", "ISIN_CHANGE", "MERGER"):
        flow = FlowClassification.NEUTRAL
        gross = Decimal("0")

    else:
        # Fallback guard
        flow = FlowClassification.UNKNOWN
        status = ClassificationStatus.NEEDS_REVIEW
        reason = f"Beklenmeyen işlem tipi: {eff_type}"

    cost_dict = {
        "gross": str(gross) if gross is not None else None,
        "net": str(net),
        "fee": str(fee),
        "tax": str(tax),
    }

    return ClassificationResult(
        classification=flow,
        status=status,
        gross_amount=gross,
        net_amount=net,
        fee_amount=fee,
        tax_amount=tax,
        affects_twr=affects_twr,
        affects_mwr=affects_mwr,
        cost_impact_json=json.dumps(cost_dict, separators=(",", ":")),
        resolved_type=eff_type,
        reason=reason,
    )
