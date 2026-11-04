"""4-Dimension Portfolio Reconciliation Engine (IP-3).

Audits 4 independent dimensions:
1. Position quantities (0.0001 shares tolerance)
2. Cash balance (0.01 EUR tolerance)
3. Total valuation
4. FIFO cost basis (0.01 EUR/share tolerance)

Calculates time_delta_seconds (latency between event_time and closest broker observation).
Persists immutable records into `reconciliations` table with RECONCILED or DISCREPANCY status.
Zero hallucination: Unexplained cash gap is never fabricated as fake fee/tax.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from masa.calc.corporate import list_corporate_actions, transform_lots_for_corporate_action
from masa.calc.transaction_classifier import FlowClassification, classify_transaction
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import canonical_json, compute_reconciliation_hash

logger = logging.getLogger(__name__)

SHARES_TOLERANCE = Decimal("0.0001")
CASH_TOLERANCE = Decimal("0.01")
COST_TOLERANCE = Decimal("0.01")
VALUATION_TOLERANCE = Decimal("1.00")


@dataclass
class DiscrepancyItem:
    dimension: str  # POSITION, CASH, VALUATION, COST_BASIS
    entity: str     # ISIN or "CASH" or "PORTFOLIO"
    ledger_val: str
    broker_val: str
    diff_val: str
    tolerance: str
    reason: str


@dataclass
class ReconciliationSummary:
    reconciliation_id: str
    run_id: str
    reconciliation_time: str
    status: str  # RECONCILED, DISCREPANCY
    shares_match: bool
    cash_match: bool
    valuation_match: bool
    cost_basis_match: bool
    discrepancies: List[DiscrepancyItem] = field(default_factory=list)
    cash_gap_eur: Optional[Decimal] = None
    observation_lag_seconds: Optional[int] = None
    broker_snapshot_id: Optional[str] = None
    cash_observation_id: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


def _reconstruct_ledger(
    transactions: List[Dict[str, Any]],
    corporate_actions: List[Any],
) -> Tuple[Dict[str, Decimal], Dict[str, Decimal], Decimal, Optional[datetime]]:
    """Reconstruct share counts, FIFO unit cost basis, and net cash balance from ledger.

    Returns:
        (shares_by_isin, fifo_cost_by_isin, net_cash, latest_event_dt)
    """
    shares: Dict[str, Decimal] = {}
    lots_by_isin: Dict[str, deque] = {}  # ISIN -> deque of {"shares", "cost_per_share", "timestamp"}
    cash = Decimal("0")
    latest_dt: Optional[datetime] = None

    # Merge settled transactions and corporate actions chronologically
    events: List[Tuple[datetime, str, Any]] = []

    for tx in transactions:
        status = str(tx.get("status", "")).upper()
        is_cancel = tx.get("is_cancellation") in (1, True, "1", "True")
        if is_cancel or status not in ("SETTLED", "FILLED", "CONFIRMED"):
            continue

        raw_t = tx.get("event_time")
        if isinstance(raw_t, datetime):
            dt = raw_t.astimezone(timezone.utc)
        elif raw_t:
            dt = datetime.fromisoformat(str(raw_t).replace("Z", "+00:00"))
        else:
            dt = datetime.now(timezone.utc)

        if latest_dt is None or dt > latest_dt:
            latest_dt = dt

        events.append((dt, "TX", tx))

    for ca in corporate_actions:
        raw_t = getattr(ca, "effective_date", None)
        if isinstance(raw_t, datetime):
            dt = raw_t.astimezone(timezone.utc)
        elif raw_t:
            dt = datetime.fromisoformat(str(raw_t).replace("Z", "+00:00"))
        else:
            dt = datetime.now(timezone.utc)

        events.append((dt, "CA", ca))

    # Sort events: CorporateAction prioritized if same timestamp
    events.sort(key=lambda x: (x[0], 0 if x[1] == "CA" else 1))

    for dt, kind, payload in events:
        if kind == "CA":
            isin = payload.isin
            cur_lots = list(lots_by_isin.get(isin, []))
            transformed, target_isin = transform_lots_for_corporate_action(cur_lots, payload)
            if target_isin != isin:
                lots_by_isin.pop(isin, None)
                shares.pop(isin, None)
            lots_by_isin[target_isin] = deque(transformed)
            shares[target_isin] = sum((lot["shares"] for lot in transformed), Decimal("0"))
            continue

        # Kind == "TX"
        tx = payload
        amt = Decimal(str(tx.get("amount", 0)))
        cash += amt

        isin = tx.get("isin")
        side = tx.get("side")
        qty_raw = tx.get("quantity")
        qty = Decimal(str(qty_raw)) if qty_raw is not None else Decimal("0")
        sub_type = tx.get("sub_type") or tx.get("security_transaction_type") or ""

        is_buy = (side == "BUY" or sub_type == "SAVINGS_PLAN" or tx.get("tx_type") == "BUY") and isin and qty > 0
        is_sell = side == "SELL" and isin and qty > 0

        if is_buy:
            shares[isin] = shares.get(isin, Decimal("0")) + qty
            if isin not in lots_by_isin:
                lots_by_isin[isin] = deque()
            # Acquisition cost is |amount|
            cps = abs(amt) / qty if qty > 0 else Decimal("0")
            lots_by_isin[isin].append({
                "shares": qty,
                "cost_per_share": cps,
                "timestamp": dt,
            })

        elif is_sell:
            shares[isin] = shares.get(isin, Decimal("0")) - qty
            # FIFO consumption
            rem_to_sell = qty
            q_lots = lots_by_isin.get(isin, deque())
            while rem_to_sell > Decimal("0") and q_lots:
                oldest = q_lots[0]
                if oldest["shares"] <= rem_to_sell:
                    rem_to_sell -= oldest["shares"]
                    q_lots.popleft()
                else:
                    oldest["shares"] -= rem_to_sell
                    rem_to_sell = Decimal("0")

    # Compute weighted average unit cost from remaining open lots for each ISIN
    fifo_costs: Dict[str, Decimal] = {}
    for isin, q_lots in lots_by_isin.items():
        total_sh = sum((l["shares"] for l in q_lots), Decimal("0"))
        if total_sh > Decimal("0"):
            total_basis = sum((l["shares"] * l["cost_per_share"] for l in q_lots), Decimal("0"))
            fifo_costs[isin] = total_basis / total_sh
        else:
            fifo_costs[isin] = Decimal("0")

    return shares, fifo_costs, cash, latest_dt


def reconcile_ledger_with_broker(
    db: DatabaseManager,
    run_id: Optional[str] = None,
    as_of: Optional[datetime] = None,
) -> ReconciliationSummary:
    """Execute 4-dimension reconciliation between reconstructed ledger and latest broker observations.

    Persists an immutable record in `reconciliations` table.
    """
    rec_time = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rec_time_iso = rec_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    active_run_id = run_id or f"rec_{rec_time.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"

    conn = db.get_connection()
    try:
        # 1. Fetch latest broker snapshot for positions
        pos_snap_row = conn.execute(
            """
            SELECT snapshot_id, collection_completed_at
            FROM snapshots
            WHERE snapshot_type = 'portfolio'
            ORDER BY rowid DESC LIMIT 1
            """
        ).fetchone()
        pos_snapshot_id = pos_snap_row["snapshot_id"] if pos_snap_row else None
        pos_snap_time = pos_snap_row["collection_completed_at"] if pos_snap_row else None

        broker_positions: Dict[str, Dict[str, Any]] = {}
        if pos_snapshot_id:
            for r in conn.execute(
                """
                SELECT isin, quantity, value_eur, broker_cost_basis, observed_at
                FROM position_observations
                WHERE snapshot_id = ?
                """,
                (pos_snapshot_id,),
            ).fetchall():
                broker_positions[r["isin"]] = {
                    "quantity": Decimal(str(r["quantity"] or 0)),
                    "value_eur": Decimal(str(r["value_eur"] or 0)),
                    "cost_basis": Decimal(str(r["broker_cost_basis"])) if r["broker_cost_basis"] is not None else None,
                    "observed_at": r["observed_at"],
                }

        # 2. Fetch latest broker cash observation
        cash_row = conn.execute(
            """
            SELECT cash_id, snapshot_id, settled_cash, total_cash, observed_at
            FROM cash_observations
            ORDER BY cash_id DESC LIMIT 1
            """
        ).fetchone()
        cash_observation_id = cash_row["cash_id"] if cash_row else None
        broker_cash = Decimal(str(cash_row["settled_cash"])) if cash_row else Decimal("0")
        cash_snap_time = cash_row["observed_at"] if cash_row else None

        # 3. Fetch active transactions from v_transactions_current
        tx_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM v_transactions_current ORDER BY event_time ASC, version_number ASC"
            ).fetchall()
        ]

    finally:
        conn.close()

    # 4. Fetch corporate actions
    ca_records = list_corporate_actions(db)

    # 5. Reconstruct ledger
    ledger_shares, ledger_fifo, ledger_cash, latest_tx_dt = _reconstruct_ledger(
        tx_rows, ca_records
    )

    # 6. Latency calculation (time_delta_seconds)
    observation_lag_seconds: Optional[int] = None
    if latest_tx_dt and pos_snap_time:
        try:
            obs_dt = datetime.fromisoformat(pos_snap_time.replace("Z", "+00:00"))
            observation_lag_seconds = abs(int((obs_dt - latest_tx_dt).total_seconds()))
        except Exception:
            pass

    discrepancies: List[DiscrepancyItem] = []

    # Dimension 1: Position Quantities (0.0001 tolerance)
    shares_match = True
    all_isins = set(ledger_shares.keys()) | set(broker_positions.keys())
    for isin in sorted(all_isins):
        l_q = ledger_shares.get(isin, Decimal("0"))
        b_q = broker_positions.get(isin, {}).get("quantity", Decimal("0"))
        diff = abs(l_q - b_q)
        if diff > SHARES_TOLERANCE:
            shares_match = False
            discrepancies.append(
                DiscrepancyItem(
                    dimension="POSITION",
                    entity=isin,
                    ledger_val=str(l_q),
                    broker_val=str(b_q),
                    diff_val=str(diff),
                    tolerance=str(SHARES_TOLERANCE),
                    reason=f"Adet mutabakat uyuşmazlığı: Defter={l_q}, Broker={b_q}, Fark={diff}",
                )
            )

    # Dimension 2: Cash Balance (0.01 tolerance)
    cash_diff = abs(ledger_cash - broker_cash)
    cash_match = cash_diff <= CASH_TOLERANCE
    cash_gap_eur = ledger_cash - broker_cash if not cash_match else Decimal("0")
    if not cash_match:
        discrepancies.append(
            DiscrepancyItem(
                dimension="CASH",
                entity="EUR",
                ledger_val=str(ledger_cash),
                broker_val=str(broker_cash),
                diff_val=str(cash_diff),
                tolerance=str(CASH_TOLERANCE),
                reason=f"Nakit mutabakat uyuşmazlığı: Defter={ledger_cash}, Broker={broker_cash}, Açık={cash_gap_eur}",
            )
        )

    # Dimension 3: Valuation Match
    broker_val_total = sum((v["value_eur"] for v in broker_positions.values()), Decimal("0")) + broker_cash
    # Ledger valuation estimation: sum of (broker value of positions) + ledger cash
    # (or comparison between broker equity valuation and ledger cash flow equity)
    ledger_val_total = sum((v["value_eur"] for v in broker_positions.values()), Decimal("0")) + ledger_cash
    val_diff = abs(ledger_val_total - broker_val_total)
    valuation_match = val_diff <= VALUATION_TOLERANCE
    if not valuation_match:
        discrepancies.append(
            DiscrepancyItem(
                dimension="VALUATION",
                entity="PORTFOLIO",
                ledger_val=str(ledger_val_total),
                broker_val=str(broker_val_total),
                diff_val=str(val_diff),
                tolerance=str(VALUATION_TOLERANCE),
                reason=f"Portföy değerleme farkı: {val_diff} EUR",
            )
        )

    # Dimension 4: FIFO Cost Basis (0.01 tolerance)
    cost_basis_match = True
    for isin, b_pos in broker_positions.items():
        b_cost = b_pos.get("cost_basis")
        if b_cost is not None and b_pos["quantity"] > Decimal("0"):
            l_cost = ledger_fifo.get(isin, Decimal("0"))
            c_diff = abs(l_cost - b_cost)
            if c_diff > COST_TOLERANCE:
                cost_basis_match = False
                discrepancies.append(
                    DiscrepancyItem(
                        dimension="COST_BASIS",
                        entity=isin,
                        ledger_val=str(l_cost),
                        broker_val=str(b_cost),
                        diff_val=str(c_diff),
                        tolerance=str(COST_TOLERANCE),
                        reason=f"Birim maliyet farkı: Defter={l_cost}, Broker={b_cost}",
                    )
                )

    is_reconciled = shares_match and cash_match and valuation_match and cost_basis_match
    status_str = "RECONCILED" if is_reconciled else "DISCREPANCY"

    # Format discrepancies JSON
    disc_list = [
        {
            "dimension": d.dimension,
            "entity": d.entity,
            "ledger_val": d.ledger_val,
            "broker_val": d.broker_val,
            "diff_val": d.diff_val,
            "tolerance": d.tolerance,
            "reason": d.reason,
        }
        for d in discrepancies
    ]
    discrepancies_json = canonical_json(disc_list)

    rec_id = f"rec_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).isoformat()

    row_dict = {
        "broker_snapshot_id": pos_snapshot_id,
        "cash_gap_eur": str(cash_gap_eur) if cash_gap_eur != Decimal("0") else None,
        "cash_match": 1 if cash_match else 0,
        "cash_observation_id": cash_observation_id,
        "cost_basis_match": 1 if cost_basis_match else 0,
        "created_at": created_at,
        "discrepancies_count": len(discrepancies),
        "discrepancies_json": discrepancies_json,
        "notes": f"Reconciliation executed for run {active_run_id}",
        "observation_lag_seconds": str(observation_lag_seconds) if observation_lag_seconds is not None else None,
        "reconciliation_id": rec_id,
        "reconciliation_time": rec_time_iso,
        "reconciliation_type": "PORTFOLIO_FULL",
        "run_id": active_run_id,
        "shares_match": 1 if shares_match else 0,
        "status": status_str,
        "valuation_match": 1 if valuation_match else 0,
    }
    rec_hash = compute_reconciliation_hash(row_dict)

    with db.transaction() as write_conn:
        write_conn.execute(
            """
            INSERT INTO reconciliations (
                reconciliation_id, run_id, reconciliation_time, reconciliation_type,
                status, broker_snapshot_id, cash_observation_id, discrepancies_count,
                discrepancies_json, shares_match, cash_match, valuation_match,
                cost_basis_match, cash_gap_eur, observation_lag_seconds, notes,
                created_at, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec_id,
                active_run_id,
                rec_time_iso,
                "PORTFOLIO_FULL",
                status_str,
                pos_snapshot_id,
                cash_observation_id,
                len(discrepancies),
                discrepancies_json,
                1 if shares_match else 0,
                1 if cash_match else 0,
                1 if valuation_match else 0,
                1 if cost_basis_match else 0,
                str(cash_gap_eur) if cash_gap_eur != Decimal("0") else None,
                str(observation_lag_seconds) if observation_lag_seconds is not None else None,
                f"Reconciliation executed for run {active_run_id}",
                created_at,
                rec_hash,
            ),
        )

    return ReconciliationSummary(
        reconciliation_id=rec_id,
        run_id=active_run_id,
        reconciliation_time=rec_time_iso,
        status=status_str,
        shares_match=shares_match,
        cash_match=cash_match,
        valuation_match=valuation_match,
        cost_basis_match=cost_basis_match,
        discrepancies=discrepancies,
        cash_gap_eur=cash_gap_eur,
        observation_lag_seconds=observation_lag_seconds,
        broker_snapshot_id=pos_snapshot_id,
        cash_observation_id=cash_observation_id,
        details={
            "ledger_shares": {k: str(v) for k, v in ledger_shares.items()},
            "broker_shares": {k: str(v["quantity"]) for k, v in broker_positions.items()},
            "ledger_cash": str(ledger_cash),
            "broker_cash": str(broker_cash),
            "record_hash": rec_hash,
        },
    )
