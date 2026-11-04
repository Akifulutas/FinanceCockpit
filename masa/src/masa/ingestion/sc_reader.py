"""Read-only wrapper for Scalable Capital CLI (/opt/homebrew/bin/sc).

Guarantees:
1. shell=False strictly enforced on all executions; fixed absolute binary path
   (MASA_SC_BIN or /opt/homebrew/bin/sc), never resolved through PATH.
2. Whitelisted read commands ONLY (whoami, context, positions, cash, quote,
   history, chart) and a per-command flag allowlist with value validation.
3. ABSOLUTELY ZERO BROKER WRITE PATH (no buy, sell, cancel, savings-plan, watchlist modification).
4. Lossless Decimal parsing for all numeric values.
5. Single ISIN queries only (rejection of comma-separated batching).
6. Dependency-injected runner for offline testing with fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from masa.ingestion.exceptions import (
    ScalableCommandError,
    ScalableParsingError,
    ScalableReaderError,
    ScalableSecurityViolation,
    ScalableTimeoutError,
    SingleISINViolation,
)
from masa.ingestion.models import (
    CashBreakdownResult,
    ChartPoint,
    ChartSeries,
    PositionItem,
    PositionsResult,
    QuoteData,
    RawBrokerPayload,
    TransactionItem,
    TransactionsResult,
)


class WatchlistItem(BaseModel):
    """Parsed security item from 'sc broker watchlist --json'."""
    model_config = ConfigDict(frozen=True)

    isin: str
    name: str
    quote_mid_price: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    quote_currency: str = "EUR"
    quote_timestamp_utc: Optional[datetime] = None
    quote_is_outdated: Optional[bool] = None
    security_type: str = "UNKNOWN"


class WatchlistResult(BaseModel):
    """Container for broker watchlist items."""
    model_config = ConfigDict(frozen=True)

    account_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    count: int
    items: List[WatchlistItem]
    retrieved_at: datetime


ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

ALLOWED_READ_OPERATIONS: Set[str] = {
    "whoami",
    "context",
    "positions",
    "cash",
    "quote",
    "history",
    "chart",
    "capabilities",
    "broker_watchlist",
    "broker.watchlist",
}

# logical operation -> argv words after the binary (all read-only per Scalable CLI docs)
OPERATION_TO_CLI_SUBCOMMAND: Dict[str, Tuple[str, ...]] = {
    "whoami": ("whoami",),
    "context": ("broker", "context", "show"),
    "positions": ("broker", "holdings"),
    "holdings": ("broker", "holdings"),
    "cash": ("broker", "cash-breakdown"),
    "cash-breakdown": ("broker", "cash-breakdown"),
    "quote": ("broker", "quote"),
    "history": ("broker", "transactions"),
    "transactions": ("broker", "transactions"),
    "chart": ("broker", "chart"),
    "capabilities": ("capabilities",),
    "broker_watchlist": ("broker", "watchlist"),
    "broker.watchlist": ("broker", "watchlist"),
}

CHART_TIMEFRAMES: Set[str] = {"1d", "7d", "1m", "3m", "6m", "ytd", "1y", "max"}
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_=.:+/|][A-Za-z0-9_\-=.:+/|]{0,2047}$")
_ISO_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?$")
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,127}$")

# per-subcommand flag -> value validator
ALLOWED_FLAGS: Dict[Tuple[str, ...], Dict[str, Callable[[str], bool]]] = {
    ("capabilities",): {},
    ("broker", "watchlist"): {},
    ("broker", "quote"): {"--isin": lambda v: bool(ISIN_PATTERN.match(v))},
    # sc 1.0.0: `sc broker transactions --help` -> page size 1..100 (default 20)
    ("broker", "transactions"): {
        "--cursor": lambda v: bool(_CURSOR_RE.match(v)),
        "--page-size": lambda v: v.isdigit() and 1 <= int(v) <= 100,
        "--from-time": lambda v: bool(_ISO_TS_RE.match(v)),
        "--to-time": lambda v: bool(_ISO_TS_RE.match(v)),
        "--isin": lambda v: bool(ISIN_PATTERN.match(v)),
    },
    # sc 1.0.0: chart is per security only (`--isin` and `--timeframe` both required)
    ("broker", "chart"): {
        "--isin": lambda v: bool(ISIN_PATTERN.match(v)),
        "--timeframe": lambda v: v in CHART_TIMEFRAMES,
    },
}

DEFAULT_SC_BINARIES: Tuple[str, ...] = ("/opt/homebrew/bin/sc", "/usr/local/bin/sc")


def resolve_sc_binary(explicit: Optional[str] = None) -> str:
    """Fixed absolute path; PATH is deliberately NOT consulted."""
    candidate = explicit or os.environ.get("MASA_SC_BIN")
    if candidate:
        if not os.path.isabs(candidate):
            raise ScalableSecurityViolation(f"sc binary path must be absolute: {candidate!r}")
        return candidate
    for path in DEFAULT_SC_BINARIES:
        if Path(path).exists():
            return path
    return DEFAULT_SC_BINARIES[0]

FORBIDDEN_TOKENS: Set[str] = {
    "trade",
    "buy",
    "sell",
    "cancel",
    "savings-plans",
    "savings-plan",
    "watchlist",
    "price-alerts",
    "order",
    "rm",
    "delete",
    "post",
    "put",
    "context select",
    "login",
    "logout",
    "add",
    "remove",
    "select",
}

RunnerCallable = Callable[[List[str], float], Tuple[int, str, str]]


def default_subprocess_runner(cmd: List[str], timeout: float) -> Tuple[int, str, str]:
    """Execute command safely with shell=False, strict timeout, and single-flight sc.lock."""
    from masa.ingestion.lock import sc_file_lock
    try:
        with sc_file_lock(timeout_seconds=timeout):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,  # MANDATORY SECURITY REQUIREMENT
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        raise ScalableTimeoutError(f"Command timed out after {timeout} seconds: {' '.join(cmd)}") from exc
    except FileNotFoundError as exc:
        raise ScalableReaderError(f"Scalable CLI executable not found at '{cmd[0]}'") from exc


class ScalableReader:
    """Read-only Scalable Capital CLI client."""

    def __init__(
        self,
        binary_path: Optional[str] = None,
        timeout_seconds: float = 30.0,
        runner: Optional[RunnerCallable] = None,
    ):
        self.binary_path = resolve_sc_binary(binary_path)
        self.timeout_seconds = timeout_seconds
        self._runner = runner or default_subprocess_runner
        self.last_raw: Optional[RawBrokerPayload] = None
        self.raw_log: List[RawBrokerPayload] = []

    @staticmethod
    def _tokens(arg: str) -> List[str]:
        return [t.lstrip("-") for t in re.split(r"[^a-z0-9-]+", arg.lower()) if t.strip("-")]

    def _validate_command_safety(self, operation: str, extra_args: Optional[List[str]] = None) -> Tuple[str, ...]:
        """Whitelisted operation + whole-token write-word scan + per-flag allowlist."""
        op_clean = operation.strip().lower()
        if op_clean not in OPERATION_TO_CLI_SUBCOMMAND:
            raise ScalableSecurityViolation(
                f"Unauthorized broker command '{operation}'. Allowed read-only operations: {sorted(ALLOWED_READ_OPERATIONS)}"
            )
        words = OPERATION_TO_CLI_SUBCOMMAND[op_clean]
        args = list(extra_args or [])
        for arg in args:
            if not isinstance(arg, str):
                raise ScalableSecurityViolation("CLI arguments must be strings")
        joined = " ".join(a.lower() for a in args)
        for arg in args:
            for token in self._tokens(arg):
                if token in FORBIDDEN_TOKENS or token == "confirm":
                    raise ScalableSecurityViolation(
                        f"Security violation: argument '{arg}' contains forbidden write token '{token}'."
                    )
        if "context select" in joined:
            raise ScalableSecurityViolation("Security violation: forbidden write token 'context select'.")

        allowed = ALLOWED_FLAGS.get(words, {})
        i = 0
        while i < len(args):
            flag = args[i]
            if flag not in allowed:
                raise ScalableSecurityViolation(f"Flag {flag!r} is not allowed for 'sc {' '.join(words)}'")
            if i + 1 >= len(args):
                raise ScalableSecurityViolation(f"Flag {flag!r} requires a value")
            value = args[i + 1]
            if value.startswith("-") or not allowed[flag](value):
                raise ScalableSecurityViolation(f"Invalid value for {flag}: {value!r}")
            i += 2
        return words

    def _execute_raw(self, operation: str, extra_args: Optional[List[str]] = None) -> RawBrokerPayload:
        """Execute read-only command and return RawBrokerPayload with lossless Decimal parsing."""
        words = self._validate_command_safety(operation, extra_args)
        cli_subcommand = ".".join(w for w in words if w != "broker")

        cmd = [self.binary_path, *words, "--json"]
        if extra_args:
            cmd.extend(extra_args)

        retrieved_at = datetime.now(timezone.utc)
        returncode, stdout, stderr = self._runner(cmd, self.timeout_seconds)

        if returncode != 0:
            err_details = stderr
            if stdout.strip():
                try:
                    parsed_err = json.loads(stdout)
                    if isinstance(parsed_err, dict) and "error" in parsed_err:
                        err_details = f"{stderr} {parsed_err['error']}".strip() if stderr else str(parsed_err['error'])
                except Exception:
                    pass
            raise ScalableCommandError(command=cmd, returncode=returncode, stderr=err_details)

        if not stdout.strip():
            raise ScalableParsingError(f"Empty output received from command: {' '.join(cmd)}")

        try:
            # Parse floats directly to Decimal to avoid IEEE-754 precision loss
            parsed = json.loads(stdout, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise ScalableParsingError(f"Failed to decode CLI JSON: {exc}\nOutput: {stdout[:200]}") from exc

        if not isinstance(parsed, dict) or not parsed.get("ok", False):
            err_msg = parsed.get("error", "Unknown CLI error") if isinstance(parsed, dict) else stdout
            raise ScalableCommandError(command=cmd, returncode=returncode, stderr=str(err_msg))

        payload_sha256 = hashlib.sha256(stdout.encode("utf-8")).hexdigest()

        raw_payload = RawBrokerPayload(
            command=".".join(words),
            args=cmd[1:],
            retrieved_at=retrieved_at,
            stdout_raw=stdout,
            parsed_json=parsed,
            payload_sha256=payload_sha256,
        )
        self.last_raw = raw_payload
        self.raw_log.append(raw_payload)
        return raw_payload

    def get_quote(self, isin: str) -> QuoteData:
        """Fetch current bid/ask quote for a single ISIN.

        Constraints:
        - Exactly one ISIN. Comma-separated batching is strictly rejected.
        - Must match ISO 6166 12-char format.
        - Computed mid and spread calculated with Decimal arithmetic.
        """
        if not isinstance(isin, str):
            raise TypeError("ISIN must be a string")

        isin_clean = isin.strip().upper()

        if "," in isin_clean or ";" in isin_clean or " " in isin_clean or "|" in isin_clean:
            raise SingleISINViolation(
                f"Single ISIN queries only. Comma-separated batching is forbidden: '{isin}'"
            )

        if not ISIN_PATTERN.match(isin_clean):
            raise ValueError(f"Invalid ISIN format: '{isin_clean}'. Must be 12 alphanumeric characters.")

        raw = self._execute_raw("quote", extra_args=["--isin", isin_clean])
        data = raw.parsed_json.get("data", {})
        result = data.get("result", {})

        if not result or result.get("isin") != isin_clean:
            raise ScalableParsingError(f"Quote result missing or ISIN mismatch for '{isin_clean}'")

        bid = Decimal(str(result["quote_bid_price"]))
        ask = Decimal(str(result["quote_ask_price"]))
        reported_mid = Decimal(str(result["quote_mid_price"]))

        if bid <= Decimal("0") or ask <= Decimal("0"):
            raise ValueError(f"Non-positive quote prices encountered for {isin_clean}: bid={bid}, ask={ask}")
        if ask < bid:
            raise ValueError(f"Ask price ({ask}) cannot be strictly lower than bid price ({bid}) for {isin_clean}")

        computed_mid = (bid + ask) / Decimal("2")
        spread = ask - bid
        spread_pct = (spread / computed_mid) * Decimal("100") if computed_mid > Decimal("0") else Decimal("0")

        ts_raw = result.get("quote_timestamp_utc")
        if ts_raw:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            ts = raw.retrieved_at

        outdated = result.get("quote_is_outdated")
        if outdated is not None and not isinstance(outdated, bool):
            outdated = None

        performances: Dict[str, Decimal] = {}
        for perf in result.get("quote_performances") or []:
            if isinstance(perf, dict) and perf.get("timeframe") and perf.get("performance") is not None:
                performances[str(perf["timeframe"])] = Decimal(str(perf["performance"]))

        return QuoteData(
            performances=performances,
            isin=isin_clean,
            name=result.get("name", ""),
            security_type=result.get("security_type", "UNKNOWN"),
            bid=bid,
            ask=ask,
            mid=reported_mid,
            computed_mid=computed_mid,
            spread=spread,
            spread_pct=spread_pct,
            currency=result.get("quote_currency", "EUR"),
            is_outdated=outdated,
            timestamp_utc=ts,
            account_id=result.get("account_id"),
            portfolio_id=result.get("portfolio_id"),
        )

    def get_positions(self) -> PositionsResult:
        """Fetch current broker holdings/positions."""
        raw = self._execute_raw("positions")
        data = raw.parsed_json.get("data", {})
        result = data.get("result", {})

        items: List[PositionItem] = []
        for raw_item in result.get("items", []):
            isin = raw_item["isin"].strip().upper()
            qty = Decimal(str(raw_item.get("quantity", 0)))
            fifo_raw = raw_item.get("fifo_price")
            fifo = Decimal(str(fifo_raw)) if fifo_raw is not None else None
            mid = Decimal(str(raw_item.get("quote_mid_price", 0)))
            valuation = Decimal(str(raw_item.get("valuation", 0)))
            blocked = Decimal(str(raw_item.get("blocked_quantity", 0)))
            pending = Decimal(str(raw_item.get("pending_quantity", 0)))

            ts_raw = raw_item.get("quote_timestamp_utc")
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else raw.retrieved_at

            items.append(
                PositionItem(
                    isin=isin,
                    name=raw_item.get("name", ""),
                    security_type=raw_item.get("security_type", "UNKNOWN"),
                    quantity=qty,
                    fifo_price=fifo,
                    quote_mid_price=mid,
                    quote_currency=raw_item.get("quote_currency", "EUR"),
                    quote_timestamp_utc=ts,
                    valuation=valuation,
                    valuation_currency=raw_item.get("valuation_currency", "EUR"),
                    blocked_quantity=blocked,
                    pending_quantity=pending,
                )
            )

        return PositionsResult(
            account_id=result.get("account_id", ""),
            portfolio_id=result.get("portfolio_id", ""),
            count=result.get("count", len(items)),
            items=items,
            retrieved_at=raw.retrieved_at,
        )

    def get_cash(self) -> CashBreakdownResult:
        """Fetch broker cash and buying power breakdown."""
        raw = self._execute_raw("cash")
        data = raw.parsed_json.get("data", {})
        result = data.get("result", {})

        return CashBreakdownResult(
            account_id=result.get("account_id", ""),
            portfolio_id=result.get("portfolio_id", ""),
            cash_balance=Decimal(str(result.get("cash_balance", 0))),
            buying_power=Decimal(str(result.get("buying_power", 0))),
            buying_power_without_credit=Decimal(str(result.get("buying_power_without_credit", 0))),
            available_credit_line=Decimal(str(result.get("available_credit_line", 0))),
            derivatives_buying_power=Decimal(str(result.get("derivatives_buying_power", 0))),
            pending_buy_orders_amount=Decimal(str(result.get("pending_buy_orders_amount", 0))),
            possible_taxes=Decimal(str(result.get("possible_taxes", 0))),
            retrieved_at=raw.retrieved_at,
        )

    def get_history(
        self,
        page_size: Optional[int] = None,
        cursor: Optional[str] = None,
        from_time: Optional[datetime | str] = None,
        to_time: Optional[datetime | str] = None,
        isin: Optional[str] = None,
        raw_sink: Optional[List[RawBrokerPayload]] = None,
    ) -> TransactionsResult:
        """Fetch one page of broker transactions (--page-size only if explicitly given)."""
        extra_args: List[str] = []
        if page_size is not None:
            extra_args.extend(["--page-size", str(page_size)])
        if cursor:
            extra_args.extend(["--cursor", cursor])
        if from_time is not None:
            ts_from = (
                from_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if isinstance(from_time, datetime)
                else str(from_time)
            )
            extra_args.extend(["--from-time", ts_from])
        if to_time is not None:
            ts_to = (
                to_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if isinstance(to_time, datetime)
                else str(to_time)
            )
            extra_args.extend(["--to-time", ts_to])
        if isin is not None:
            extra_args.extend(["--isin", isin.strip().upper()])

        raw = self._execute_raw("history", extra_args=extra_args or None)
        if raw_sink is not None:
            raw_sink.append(raw)
        data = raw.parsed_json.get("data", {})
        result = data.get("result", {})

        items: List[TransactionItem] = []
        for it in result.get("items", []):
            amt = Decimal(str(it.get("amount", 0)))
            qty_raw = it.get("quantity")
            qty = Decimal(str(qty_raw)) if qty_raw is not None else None
            limit_raw = it.get("limit_price")
            limit_price = Decimal(str(limit_raw)) if limit_raw is not None else None

            dt_raw = it.get("last_event_datetime")
            dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00")) if dt_raw else raw.retrieved_at

            items.append(
                TransactionItem(
                    id=str(it.get("id", "")),
                    type=str(it.get("type", "UNKNOWN")),
                    cash_transaction_type=it.get("cash_transaction_type"),
                    security_transaction_type=it.get("security_transaction_type"),
                    side=it.get("side"),
                    isin=it.get("isin"),
                    description=it.get("description"),
                    amount=amt,
                    currency=str(it.get("currency", "EUR")),
                    quantity=qty,
                    limit_price=limit_price,
                    status=str(it.get("status", "UNKNOWN")),
                    is_cancellation=bool(it.get("is_cancellation", False)),
                    last_event_datetime=dt,
                )
            )

        return TransactionsResult(
            account_id=result.get("account_id", ""),
            portfolio_id=result.get("portfolio_id", ""),
            count=result.get("count", len(items)),
            total=result.get("total"),
            cursor=result.get("cursor"),
            items=items,
            retrieved_at=raw.retrieved_at,
        )

    # ------------------------------------------------------------------
    # Generic read-only payloads (shape-agnostic; parsed by masa.ingestion.parsers)
    def get_whoami(self) -> RawBrokerPayload:
        """Session check (`sc whoami --json`)."""
        return self._execute_raw("whoami")

    def get_context(self) -> RawBrokerPayload:
        """Selected account/portfolio context (`sc broker context show --json`)."""
        return self._execute_raw("context")

    def get_chart(self, isin: str, timeframe: str = "1y") -> ChartSeries:
        """Security price history (`sc broker chart --isin X --timeframe T --json`)."""
        isin_clean = isin.strip().upper()
        if not ISIN_PATTERN.match(isin_clean):
            raise ValueError(f"Invalid ISIN format: '{isin_clean}'")
        raw = self._execute_raw("chart", extra_args=["--timeframe", timeframe, "--isin", isin_clean])
        data = raw.parsed_json.get("data", {})
        if data.get("isin") not in (None, isin_clean):
            raise ScalableParsingError(f"Chart ISIN mismatch for {isin_clean}")
        points = []
        for pt in data.get("data_points", []):
            ts = pt.get("timestamp_utc")
            mid = pt.get("mid_price")
            if ts is None or mid is None:
                continue
            points.append(ChartPoint(timestamp_utc=datetime.fromisoformat(ts.replace("Z", "+00:00")),
                                     mid_price=Decimal(str(mid))))
        ref = data.get("closing_reference_point") or {}
        reference = None
        if ref.get("timestamp_utc") and ref.get("mid_price") is not None:
            reference = ChartPoint(timestamp_utc=datetime.fromisoformat(ref["timestamp_utc"].replace("Z", "+00:00")),
                                   mid_price=Decimal(str(ref["mid_price"])))
        if not points:
            raise ScalableParsingError(f"Chart for {isin_clean} returned no data points")
        return ChartSeries(isin=isin_clean, currency=str(data.get("currency", "EUR")),
                           source=str(data.get("source", "UNKNOWN")), timeframe=str(data.get("timeframe", timeframe)),
                           reference=reference, points=sorted(points, key=lambda p: p.timestamp_utc),
                           retrieved_at=raw.retrieved_at)

    def get_all_transactions(
        self,
        page_size: int = 100,
        max_pages: int = 200,
        from_time: Optional[datetime | str] = None,
        to_time: Optional[datetime | str] = None,
        isin: Optional[str] = None,
    ) -> Tuple[List[TransactionItem], List[RawBrokerPayload]]:
        """Follow the cursor until the broker returns no further page."""
        items: List[TransactionItem] = []
        raws: List[RawBrokerPayload] = []
        seen_ids: Set[str] = set()
        seen_cursors: Set[str] = set()
        cursor: Optional[str] = None
        for _ in range(max_pages):
            page = self.get_history(
                page_size=page_size,
                cursor=cursor,
                from_time=from_time,
                to_time=to_time,
                isin=isin,
                raw_sink=raws,
            )
            new = [t for t in page.items if t.id not in seen_ids]
            for t in new:
                seen_ids.add(t.id)
            items.extend(new)
            cursor = page.cursor
            if not page.items or not new or not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        else:
            raise ScalableReaderError(f"Transaction pagination exceeded {max_pages} pages")
        return items, raws

    def get_capabilities(self) -> Any:
        """Fetch CLI capabilities and supported command list."""
        from masa.ingestion.capabilities import CapabilitiesResult
        raw = self._execute_raw("capabilities")
        data = raw.parsed_json.get("data", {})
        auth_data = data.get("auth", {})
        return CapabilitiesResult(
            version=str(data.get("version", "unknown")),
            output=data.get("output"),
            commands=list(data.get("commands", [])),
            auth_modes=list(auth_data.get("modes", [])),
            exit_codes={k: int(v) for k, v in data.get("exit_codes", {}).items()},
            local_trade_controls=dict(data.get("local_trade_controls", {})),
            raw_payload=raw.parsed_json,
        )

    def get_watchlist(self) -> WatchlistResult:
        """Fetch broker watchlist items read-only."""
        raw = self._execute_raw("broker_watchlist")
        data = raw.parsed_json.get("data", {})
        result = data.get("result", {})
        items_raw = result.get("items", [])

        items: List[WatchlistItem] = []
        for it in items_raw:
            ts_raw = it.get("quote_timestamp_utc")
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else raw.retrieved_at
            mid_raw = it.get("quote_mid_price")
            mid_val = Decimal(str(mid_raw)) if mid_raw is not None else None
            items.append(
                WatchlistItem(
                    isin=str(it.get("isin", "")).strip().upper(),
                    name=str(it.get("name", "")),
                    quote_mid_price=mid_val,
                    quote_currency=str(it.get("quote_currency", "EUR")),
                    quote_timestamp_utc=ts,
                    quote_is_outdated=it.get("quote_is_outdated"),
                    security_type=str(it.get("security_type", "UNKNOWN")),
                )
            )

        return WatchlistResult(
            account_id=result.get("account_id") or data.get("account_id"),
            portfolio_id=result.get("portfolio_id") or data.get("portfolio_id"),
            count=result.get("count", len(items)),
            items=items,
            retrieved_at=raw.retrieved_at,
        )

