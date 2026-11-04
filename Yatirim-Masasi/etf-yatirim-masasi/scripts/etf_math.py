#!/usr/bin/env python3
"""Local ETF overlap and snapshot arithmetic; never fetches or executes trades."""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


def number(value, field):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field}: a finite number is required")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field}: invalid number") from exc
    if not result.is_finite():
        raise ValueError(f"{field}: a finite number is required")
    return result


def timestamp(value, field):
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field}: ISO timestamp required") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field}: timezone required")
    return result


def read_holdings(path):
    weights = defaultdict(Decimal)
    dates = set()
    missing_dates = False
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"security_id", "weight_percent"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires security_id,weight_percent")
        for row in reader:
            ident = row["security_id"].strip()
            if not ident:
                raise ValueError("Each holding requires a security_id")
            weight = number(row["weight_percent"], "weight_percent")
            if weight < 0 or weight > 100:
                raise ValueError("weight_percent must be between 0 and 100")
            weights[ident] += weight
            day = (row.get("as_of") or "").strip()
            if day:
                datetime.strptime(day, "%Y-%m-%d")
                dates.add(day)
            else:
                missing_dates = True
    total = sum(weights.values(), Decimal(0))
    if not weights or total <= 0:
        raise ValueError("Holdings file is empty or has no positive weights")
    if total > 100:
        raise ValueError("Holdings exceed 100%; check rounding, duplicates or exposure type before comparing")
    if len(dates) > 1:
        raise ValueError("A holdings file contains multiple as_of dates")
    return weights, total, next(iter(dates), None), missing_dates


def overlap(path_a, path_b):
    a, total_a, day_a, missing_a = read_holdings(path_a)
    b, total_b, day_b, missing_b = read_holdings(path_b)
    shared = sorted(set(a) & set(b))
    common = sum((min(a[k], b[k]) for k in shared), Decimal(0))
    warnings = []
    if missing_a or missing_b:
        warnings.append("Some holdings have no as_of date; freshness is unverified")
    if day_a and day_b and day_a != day_b:
        warnings.append("Holdings dates differ; comparison is approximate")
    complete = total_a == 100 and total_b == 100
    if not complete:
        warnings.append("Weights were not normalized; overlap is observed coverage only")
    return {
        "metric": "sum_min_weights_percent",
        "overlap_percent": float(common),
        "interpretation": "full_supplied_baskets" if complete else "observed_lower_bound",
        "coverage_a_percent": float(total_a),
        "coverage_b_percent": float(total_b),
        "as_of_a": day_a,
        "as_of_b": day_b,
        "common_security_count": len(shared),
        "warnings": warnings,
        "scope_note": "Analyst must verify economic exposure, identifiers and completeness",
    }


def snapshot(data):
    if not isinstance(data, dict):
        raise ValueError("Snapshot JSON must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency: three-letter base currency required")
    start = timestamp(data.get("period_start"), "period_start")
    end = timestamp(data.get("period_end"), "period_end")
    if end <= start:
        raise ValueError("period_end must be after period_start")
    prev = number(data.get("previous_equity"), "previous_equity")
    current = number(data.get("current_equity"), "current_equity")
    tolerance = Decimal("0.02")
    issues = []
    notes = []
    result = {
        "currency": currency.upper(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "value_change": float(current - prev),
        "investment_pnl": None,
        "return_percent": None,
        "return_method": None,
    }
    has_positions = data.get("positions_value") is not None
    has_cash = data.get("cash") is not None
    if has_positions != has_cash:
        raise ValueError("positions_value and cash must be supplied together")
    if has_positions:
        total = number(data["positions_value"], "positions_value") + number(data["cash"], "cash")
        gap = current - total
        result["component_gap"] = float(gap)
        if abs(gap) > tolerance:
            issues.append("positions_value + cash does not reconcile to current_equity")
    flow_value = data.get("external_flow")
    reported = data.get("reported_pnl")
    if flow_value is None:
        notes.append("External flow is unknown; investment P/L and return are not calculated")
        if reported is not None:
            implied = current - prev - number(reported, "reported_pnl")
            result["flow_required_if_reported_pnl_is_correct"] = float(implied)
            issues.append("Reported P/L requires reconciliation; implied flow is not a confirmed flow")
    else:
        flow = number(flow_value, "external_flow")
        pnl = current - prev - flow
        result["investment_pnl"] = float(pnl)
        if reported is not None:
            gap = pnl - number(reported, "reported_pnl")
            result["reported_pnl_gap"] = float(gap)
            if abs(gap) > tolerance:
                issues.append("Reported P/L does not reconcile to the supplied external flow")
        timing = data.get("flow_timing", "unknown")
        if timing not in {"none", "start", "end", "mixed", "unknown"}:
            raise ValueError("flow_timing must be none/start/end/mixed/unknown")
        denominator = None
        if timing == "none":
            if flow != 0:
                raise ValueError("flow_timing=none requires external_flow=0")
            denominator = prev
        elif timing == "start":
            denominator = prev + flow
        elif timing == "end":
            denominator = prev
        if denominator is not None:
            if denominator <= 0:
                issues.append("Return denominator is not positive")
            elif not issues:
                result["return_percent"] = float(100 * pnl / denominator)
                result["return_method"] = f"simple_period_{timing}"
            else:
                notes.append("Return suppressed until the snapshot reconciles")
        else:
            notes.append("Flow timing is mixed/unknown; dated subperiods or cash flows are required for return")
    if not has_positions:
        notes.append("Position/cash components were not supplied; only aggregate arithmetic was checked")
    result.update(status="needs_review" if issues else "arithmetic_checked", issues=issues, notes=notes)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("overlap")
    command.add_argument("--a", required=True)
    command.add_argument("--b", required=True)
    command = commands.add_parser("snapshot")
    command.add_argument("input")
    args = parser.parse_args()
    try:
        if args.command == "overlap":
            result = overlap(args.a, args.b)
        else:
            result = snapshot(json.loads(Path(args.input).read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Input error: {exc}\n")


if __name__ == "__main__":
    main()
