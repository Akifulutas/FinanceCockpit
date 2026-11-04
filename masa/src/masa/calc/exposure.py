"""Portfolio Concentration, Single-Stock Limits, and UCITS 5/10/40 Compliance (İP-11).

Design Invariants:
1. European UCITS Directive 2009/65/EC Art. 52 (5/10/40 Rule):
   - Single-issuer limit: No single holding may exceed 10.00% (0.10) of the net asset value.
   - Aggregate group limit: The sum of all holdings that individually exceed 5.00% (0.05)
     must not exceed 40.00% (0.40) of the net asset value.
2. Exact Decimal calculations: Avoid floating point roundoff inaccuracies.
3. Informative warnings: If non-compliant, explicitly list offending positions and aggregate sums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

SINGLE_LIMIT_MAX = Decimal("0.1000")  # 10%
GROUP_THRESHOLD = Decimal("0.0500")   # 5%
GROUP_LIMIT_MAX = Decimal("0.4000")   # 40%


@dataclass(frozen=True)
class UCITSConcentrationResult:
    """Outcome of UCITS 5/10/40 concentration test."""
    is_compliant: bool
    single_limit_violations: List[Tuple[str, Decimal]]
    group_limit_violations: List[Tuple[str, Decimal]]
    sum_exceeding_5pct: Decimal
    warnings: List[str] = field(default_factory=list)


def check_ucits_5_10_40(
    weights: Dict[str, Decimal],
    cash_weight: Optional[Decimal] = None,
) -> UCITSConcentrationResult:
    """Check portfolio weights against European UCITS 5/10/40 concentration rules.

    Parameters:
    - weights: mapping of instrument ISIN/name to normalized portfolio weight (0.0 to 1.0).
    - cash_weight: optional cash proportion (excluded from issuer limits).
    """
    single_violations: List[Tuple[str, Decimal]] = []
    group_holdings: List[Tuple[str, Decimal]] = []
    warnings: List[str] = []

    sum_exceeding_5pct = Decimal("0.0000")

    for isin, weight in weights.items():
        w = Decimal(str(weight))
        if w < Decimal("0.0000"):
            continue

        # Rule 1: Single holding cannot exceed 10%
        if w > SINGLE_LIMIT_MAX:
            single_violations.append((isin, w))
            warnings.append(
                f"UCITS Tekil Limit İhlali: {isin} ağırlığı %{w * 100:.2f} (Azami: %10.00)"
            )

        # Rule 2: Holdings exceeding 5%
        if w > GROUP_THRESHOLD:
            group_holdings.append((isin, w))
            sum_exceeding_5pct += w

    # Check aggregate 40% cap
    group_violations: List[Tuple[str, Decimal]] = []
    if sum_exceeding_5pct > GROUP_LIMIT_MAX:
        group_violations = list(group_holdings)
        warnings.append(
            f"UCITS Grup Limiti İhlali: %5'i aşan varlıkların toplamı %{sum_exceeding_5pct * 100:.2f} (Azami: %40.00)"
        )

    is_compliant = len(single_violations) == 0 and len(group_violations) == 0

    return UCITSConcentrationResult(
        is_compliant=is_compliant,
        single_limit_violations=single_violations,
        group_limit_violations=group_violations,
        sum_exceeding_5pct=sum_exceeding_5pct,
        warnings=warnings,
    )
