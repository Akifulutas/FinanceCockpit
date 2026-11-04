"""Unit tests for ScalableReader read-only CLI wrapper."""

from decimal import Decimal
import pytest

from masa.ingestion.exceptions import (
    ScalableCommandError,
    ScalableParsingError,
    ScalableSecurityViolation,
    SingleISINViolation,
)
from masa.ingestion.sc_reader import FORBIDDEN_TOKENS, ScalableReader


class TestScalableReaderSecurity:
    """Security tests enforcing whitelist and zero write paths."""

    def test_forbidden_write_commands_rejected(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        forbidden_ops = ["trade", "buy", "sell", "cancel", "savings-plan", "watchlist", "price-alerts"]
        for op in forbidden_ops:
            with pytest.raises(ScalableSecurityViolation):
                reader._execute_raw(op)

    def test_forbidden_tokens_in_arguments_rejected(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        for token in FORBIDDEN_TOKENS:
            with pytest.raises(ScalableSecurityViolation):
                reader._execute_raw("positions", extra_args=[f"--note={token}"])

    def test_single_isin_enforced(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        # Comma-separated query must be strictly rejected
        with pytest.raises(SingleISINViolation):
            reader.get_quote("US0378331005,IE00B3YLTY66")

        # Semicolon separated query rejected
        with pytest.raises(SingleISINViolation):
            reader.get_quote("US0378331005;IE00B3YLTY66")

        # Whitespace separated query rejected
        with pytest.raises(SingleISINViolation):
            reader.get_quote("US0378331005 IE00B3YLTY66")

        # Pipe separated query rejected
        with pytest.raises(SingleISINViolation):
            reader.get_quote("US0378331005|IE00B3YLTY66")

        # Malformed length rejected
        with pytest.raises(ValueError):
            reader.get_quote("SHORT")

    def test_no_write_methods_exist_on_reader(self) -> None:
        reader_methods = [m for m in dir(ScalableReader) if not m.startswith("_")]
        # Assert none of the dangerous write verbs exist in reader methods
        for forbidden in ["buy", "sell", "trade", "cancel", "post", "put", "delete", "create_plan"]:
            assert forbidden not in reader_methods


class TestScalableReaderParsing:
    """Parsing and lossless Decimal precision tests."""

    def test_quote_parsing_lossless_decimal(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        quote = reader.get_quote("US0378331005")

        assert quote.isin == "US0378331005"
        assert quote.currency == "EUR"
        assert isinstance(quote.bid, Decimal)
        assert isinstance(quote.ask, Decimal)
        assert isinstance(quote.mid, Decimal)
        assert isinstance(quote.computed_mid, Decimal)
        assert isinstance(quote.spread, Decimal)
        assert isinstance(quote.spread_pct, Decimal)

        assert quote.bid == Decimal("309.65")
        assert quote.ask == Decimal("309.85")
        assert quote.mid == Decimal("309.75")
        assert quote.computed_mid == Decimal("309.75")
        assert quote.spread == Decimal("0.20")
        assert quote.is_outdated is False

    def test_holdings_parsing_decimal(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        pos = reader.get_positions()
        assert pos.count == 2
        assert len(pos.items) == 2

        item1 = pos.items[0]
        assert item1.isin == "IE00B3YLTY66"
        assert isinstance(item1.quantity, Decimal)
        assert item1.quantity == Decimal("158")
        assert item1.fifo_price == Decimal("11.593165")
        assert item1.valuation == Decimal("1843.23")

    def test_cash_breakdown_parsing(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        cash = reader.get_cash()
        assert isinstance(cash.cash_balance, Decimal)
        assert cash.cash_balance == Decimal("1250.50")
        assert cash.buying_power == Decimal("1250.50")

    def test_transactions_parsing(self, mock_runner_factory) -> None:
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        tx = reader.get_history()
        assert tx.count == 2
        assert len(tx.items) == 2
        assert tx.items[0].type == "CASH_TRANSACTION"
        assert tx.items[0].amount == Decimal("-4.99")
        assert tx.items[1].type == "SECURITY_TRANSACTION"
        assert tx.items[1].quantity == Decimal("4")
        assert tx.items[1].limit_price == Decimal("50.571")

    def test_cli_error_raises_scalable_command_error(self, mock_runner_factory) -> None:
        runner = mock_runner_factory(
            overrides={"broker quote": (1, '{"ok": false, "error": "Session expired"}', "Session error")}
        )
        reader = ScalableReader(runner=runner)

        with pytest.raises(ScalableCommandError) as exc_info:
            reader.get_quote("US0378331005")
        assert "Session expired" in str(exc_info.value)

    def test_invalid_json_raises_scalable_parsing_error(self, mock_runner_factory) -> None:
        runner = mock_runner_factory(
            overrides={"broker quote": (0, "MALFORMED_NON_JSON", "")}
        )
        reader = ScalableReader(runner=runner)

        with pytest.raises(ScalableParsingError):
            reader.get_quote("US0378331005")
