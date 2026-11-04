"""Tests for the integrated calc and research modules under masa."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest

from masa.calc import (
    performance,
    lookthrough,
    rebalancing,
    optimization,
    valuation,
)
from masa.research import (
    critic,
    agent,
)


def test_modules_importable():
    """Verify all algorithmic modules are importable from masa package."""
    assert hasattr(performance, "calculate_performance")
    assert hasattr(lookthrough, "compute_lookthrough")
    assert hasattr(rebalancing, "calculate_rebalancing")
    assert hasattr(optimization, "optimize_portfolio")
    assert hasattr(valuation, "analyze")
    assert hasattr(critic, "audit_report")
    assert hasattr(agent, "ResearchAgent")


def test_red_team_critic_self_test():
    """Verify built-in self test cases for red_team_critic pass."""
    assert hasattr(critic, "_self_test")
    critic._self_test()


def test_llm_research_agent_self_test():
    """Verify built-in self test cases for llm_research_agent pass."""
    assert hasattr(agent, "_self_test")
    agent._self_test()


def test_performance_engine_basic_call():
    """Verify performance engine calculates basic metrics deterministically."""
    payload = {
        "evaluation_period": {
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-06-30T23:59:59Z",
            "calendar_days": 180
        },
        "initial_valuation": {
            "total_equity": 10000.0,
            "cash_balance": 1000.0,
            "positions_value": 9000.0
        },
        "terminal_valuation": {
            "total_equity": 11500.0,
            "cash_balance": 1200.0,
            "positions_value": 10300.0
        },
        "cash_flows": [
            {
                "flow_id": "cf_1",
                "timestamp": "2026-03-31T12:00:00Z",
                "amount": 500.0,
                "currency": "EUR",
                "raw_description": "External Deposit",
                "classified_type": "EXTERNAL_DEPOSIT"
            }
        ],
        "transactions": [],
        "accounting_options": {
            "compute_modified_dietz": True,
            "compute_true_twr": True,
            "compute_xirr": True
        }
    }
    
    result = performance.calculate_performance(payload)
    assert result is not None
    assert result.engine_metadata is not None
    assert result.returns_summary is not None
    assert result.returns_summary.modified_dietz_pct is not None
    assert result.returns_summary.xirr_annualized_pct is not None
    assert result.returns_summary.xirr_convergence_status == "CONVERGED"
    assert result.reconciliation_diagnostics is not None
