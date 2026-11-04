"""Scalable Capital CLI capabilities baseline and drift detection engine.

Freezes the Scalable CLI v1.0.0 37-command baseline and provides risk-categorized
drift detection (CLEAN, INFO, WARNING, CRITICAL).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field

# Dondurulmuş Scalable CLI v1.0.0 komut seti (37 komut)
SCALABLE_CLI_BASELINE_V100: frozenset[str] = frozenset({
    "login",
    "logout",
    "whoami",
    "overnight",
    "overnight.transactions",
    "broker.context.show",
    "broker.context.select",
    "broker.overview",
    "broker.analytics",
    "broker.cash-breakdown",
    "broker.transactions",
    "broker.transaction.details",
    "broker.holdings",
    "broker.portfolio-groups",
    "broker.portfolio-groups.create",
    "broker.portfolio-groups.update",
    "broker.portfolio-groups.delete",
    "broker.portfolio-groups.assign",
    "broker.portfolio-groups.unassign",
    "broker.watchlist",
    "broker.watchlist.add",
    "broker.watchlist.remove",
    "broker.search",
    "broker.derivatives.search",
    "broker.chart",
    "broker.quote",
    "broker.security-news",
    "broker.price-alerts",
    "broker.price-alerts.add",
    "broker.price-alerts.remove",
    "broker.savings-plans",
    "broker.savings-plans.add",
    "broker.savings-plans.config",
    "broker.savings-plans.remove",
    "broker.trade.buy",
    "broker.trade.sell",
    "broker.trade.cancel",
    "capabilities",
})

# Masa sisteminin veri akışı için kritik okuma komutları
CORE_READ_COMMANDS: frozenset[str] = frozenset({
    "whoami",
    "broker.holdings",
    "broker.quote",
    "broker.cash-breakdown",
    "broker.transactions",
    "broker.chart",
    "broker.watchlist",
    "broker.context.show",
    "capabilities",
})

# Mutasyon / Yazma belirteçleri
MUTATION_TOKENS: frozenset[str] = frozenset({
    "trade",
    "buy",
    "sell",
    "order",
    "cancel",
    "transfer",
    "delete",
    "withdraw",
    "post",
    "put",
    "add",
    "remove",
    "modify",
    "create",
    "update",
})


class DriftLevel(str, Enum):
    """Komut seti değişim risk seviyesi."""
    CLEAN = "CLEAN"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CapabilitiesResult(BaseModel):
    """Pydantic v2 model for 'sc capabilities --json'."""
    model_config = ConfigDict(frozen=True)

    version: str
    output: Optional[str] = None
    commands: List[str]
    auth_modes: List[str] = Field(default_factory=list)
    exit_codes: Dict[str, int] = Field(default_factory=dict)
    local_trade_controls: Dict[str, Any] = Field(default_factory=dict)
    raw_payload: Optional[Dict[str, Any]] = None


class CapabilitiesDriftReport(BaseModel):
    """CLI yetenek değişim raporu."""
    model_config = ConfigDict(frozen=True)

    level: DriftLevel
    cli_version: str
    baseline_count: int
    current_count: int
    added_commands: List[str] = Field(default_factory=list)
    removed_commands: List[str] = Field(default_factory=list)
    critical_issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    ok: bool = True


def detect_capabilities_drift(
    current_commands: List[str] | Set[str],
    cli_version: str = "1.0.0",
) -> CapabilitiesDriftReport:
    """Compare current CLI commands against frozen v1.0.0 baseline."""
    current_set = set(current_commands)
    added = sorted(current_set - SCALABLE_CLI_BASELINE_V100)
    removed = sorted(SCALABLE_CLI_BASELINE_V100 - current_set)

    critical_issues: List[str] = []
    warnings: List[str] = []

    # 1. Kontrol: Masa'nın bağımlı olduğu temel okuma komutlarından biri silinmiş mi?
    for cmd in removed:
        if cmd in CORE_READ_COMMANDS:
            critical_issues.append(f"Kritik okuma komutu kaldırılmış: '{cmd}'")
        else:
            warnings.append(f"Mevcut komut kaldırılmış: '{cmd}'")

    # 2. Kontrol: Yeni eklenen komutlar arasında mutatif / yazma komutu var mı?
    for cmd in added:
        cmd_tokens = set(cmd.lower().replace("-", ".").split("."))
        mutation_found = cmd_tokens & MUTATION_TOKENS
        if mutation_found:
            critical_issues.append(f"Yeni potansiyel mutatif komut eklendi ({mutation_found}): '{cmd}'")
        else:
            warnings.append(f"Yeni komut eklendi: '{cmd}'")

    # Risk seviyesini belirleme
    if critical_issues:
        level = DriftLevel.CRITICAL
        ok = False
    elif warnings:
        # Eğer yalnızca yeni salt-okunur komutlar eklendiyse INFO veya WARNING
        if added and not removed:
            level = DriftLevel.INFO
            ok = True
        else:
            level = DriftLevel.WARNING
            ok = True
    else:
        level = DriftLevel.CLEAN
        ok = True

    return CapabilitiesDriftReport(
        level=level,
        cli_version=cli_version,
        baseline_count=len(SCALABLE_CLI_BASELINE_V100),
        current_count=len(current_set),
        added_commands=added,
        removed_commands=removed,
        critical_issues=critical_issues,
        warnings=warnings,
        ok=ok,
    )
