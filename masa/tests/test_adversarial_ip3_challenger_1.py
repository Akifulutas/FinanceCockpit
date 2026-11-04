"""Adversarial Stress Test Suite for IP-3 (Challenger 1).

Covers:
1. Overlapping Ingestion Deduplication & Boundary Stress
   - Multi-batch overlapping fetches with interleaved arrivals
   - Numerical format invariance (Decimal string precision)
   - Absolute row count and record_hash uniqueness verification
2. Status Mutation, Multi-step Lineage & DAG Branching Defense
   - Multi-step transitions (PENDING -> SETTLED -> CANCELLED)
   - Leaf resolution in v_transactions_current
   - Rejection of DAG branching / fork attempts via idx_txv_unique_supersedes
   - Tamper-resistance triggers (UPDATE, DELETE, REPLACE)
3. Unknown / Malformed Transaction Types & Fail-Safe Protection
   - Ingestion of exotic/malicious types (CRYPTO_STAKING, UNKNOWN_REWARD, SQLi strings)
   - NEEDS_REVIEW classification and TRANSACTION_CLASSIFICATION_FAILED audit event logging
   - Strict halt of realized_returns (available=False, zero hallucinated data)
4. CLI Flag Injection & Security Harassment
   - Adversarial payloads against --from-time and --to-time (command separators, SQLi, shell expansions, buffer overflow)
   - Strict validation preventing subprocess execution
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
import pytest

from masa.analytics import realized_returns
from masa.audit.events import AuditLogger
from masa.calc.corporate import CorporateActionRecord, CorporateActionType
from masa.calc.transaction_classifier import (
    ClassificationResult,
    ClassificationStatus,
    FlowClassification,
    classify_transaction,
)
from masa.ingestion.exceptions import ScalableSecurityViolation
from masa.ingestion.models import TransactionItem
from masa.ingestion.sc_reader import ScalableReader
from masa.ingestion.transaction_ledger import (
    calculate_incremental_from_time,
    get_current_transactions,
    ingest_transaction_versions,
)
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_transaction_version_hash


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Isolated, fresh SQLite database manager with schema v3 initialized."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    db_path = tmp_path / "test_adversarial_ip3.db"
    mgr = DatabaseManager(db_path=db_path)
    mgr.initialize_schema()
    return mgr


# ==============================================================================
# SECTION 1: Overlapping Ingestion Deduplication & Boundary Stress
# ==============================================================================


class TestOverlappingIngestionDeduplication:
    """Stress-test incremental overlapping fetch deduplication across repeated runs."""

    def test_multi_batch_overlapping_idempotency(self, test_db):
        """Simulate 5 overlapping incremental fetch cycles with mixed old/new items."""
        base_time = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

        def make_tx(tx_id: str, minutes_offset: int, amount: str = "-100.00") -> TransactionItem:
            return TransactionItem(
                id=tx_id,
                type="SECURITY_TRANSACTION",
                security_transaction_type="BUY",
                side="BUY",
                isin="IE00B4L5Y983",
                description=f"Transaction {tx_id}",
                amount=Decimal(amount),
                currency="EUR",
                quantity=Decimal("2.0"),
                limit_price=Decimal("50.0"),
                status="SETTLED",
                is_cancellation=False,
                last_event_datetime=base_time + timedelta(minutes=minutes_offset),
            )

        tx_a = make_tx("TX_A", 10)
        tx_b = make_tx("TX_B", 20)
        tx_c = make_tx("TX_C", 30)
        tx_d = make_tx("TX_D", 40)
        tx_e = make_tx("TX_E", 50)

        # Batch 1: Ingest A, B, C
        s1 = ingest_transaction_versions(test_db, [tx_a, tx_b, tx_c])
        assert s1["inserted"] == 3
        assert s1["skipped"] == 0
        assert s1["updated"] == 0

        # Batch 2: Overlapping 7-day window returns B, C (unchanged) + new D
        s2 = ingest_transaction_versions(test_db, [tx_b, tx_c, tx_d])
        assert s2["inserted"] == 1
        assert s2["skipped"] == 2
        assert s2["updated"] == 0

        # Batch 3: Repeated fetch with B, C, D (100% duplicate)
        s3 = ingest_transaction_versions(test_db, [tx_b, tx_c, tx_d])
        assert s3["inserted"] == 0
        assert s3["skipped"] == 3
        assert s3["updated"] == 0

        # Batch 4: Overlapping fetch returns C, D (unchanged) + new E
        s4 = ingest_transaction_versions(test_db, [tx_c, tx_d, tx_e])
        assert s4["inserted"] == 1
        assert s4["skipped"] == 2
        assert s4["updated"] == 0

        # Batch 5: Full redundant rescan of all 5 transactions
        s5 = ingest_transaction_versions(test_db, [tx_a, tx_b, tx_c, tx_d, tx_e])
        assert s5["inserted"] == 0
        assert s5["skipped"] == 5
        assert s5["updated"] == 0

        # Verify DB state: exactly 5 rows in transaction_versions
        conn = test_db.get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0]
            assert count == 5, f"Expected exactly 5 rows, found {count}"

            # Verify every record_hash is distinct
            hashes = conn.execute("SELECT record_hash FROM transaction_versions").fetchall()
            distinct_hashes = {h[0] for h in hashes}
            assert len(distinct_hashes) == 5

            # Verify version_number is 1 for all unchanged items
            versions = conn.execute("SELECT DISTINCT version_number FROM transaction_versions").fetchall()
            assert [r[0] for r in versions] == [1]
        finally:
            conn.close()

    def test_numerical_format_invariance(self, test_db):
        """Verify that equivalent numerical representations do not trigger spurious version increments."""
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        # Initial ingestion with 2 decimal places
        t1 = TransactionItem(
            id="TX_PRECISION_01",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Precision test",
            amount=Decimal("-100.00"),
            currency="EUR",
            quantity=Decimal("2.000"),
            limit_price=Decimal("50.00"),
            status="SETTLED",
            is_cancellation=False,
            last_event_datetime=now,
        )
        s1 = ingest_transaction_versions(test_db, [t1])
        assert s1["inserted"] == 1

        # Second ingestion with identical numerical values but alternate string representations
        # e.g., Decimal("-100.0") == Decimal("-100.00"), Decimal("2.0") == Decimal("2.000")
        t1_alt = TransactionItem(
            id="TX_PRECISION_01",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Precision test",
            amount=Decimal("-100.0"),
            currency="EUR",
            quantity=Decimal("2.0"),
            limit_price=Decimal("50.0"),
            status="SETTLED",
            is_cancellation=False,
            last_event_datetime=now,
        )
        s2 = ingest_transaction_versions(test_db, [t1_alt])
        assert s2["inserted"] == 0
        assert s2["skipped"] == 1, "Spurious version increment triggered by string representation of equivalent Decimal"
        assert s2["updated"] == 0

        # Ensure still only 1 row in DB
        conn = test_db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) FROM transaction_versions").fetchone()[0] == 1
        finally:
            conn.close()


# ==============================================================================
# SECTION 2: Status Mutation & Versioning
# ==============================================================================


class TestStatusMutationAndVersioning:
    """Stress-test status transition lifecycle, DAG branch rejection, and immutability triggers."""

    def test_multistep_transition_and_leaf_view(self, test_db):
        """Test multi-step lifecycle: PENDING (v1) -> SETTLED (v2) -> CANCELLED (v3)."""
        base_time = datetime(2026, 10, 22, 9, 0, 0, tzinfo=timezone.utc)

        # 1. Version 1: PENDING
        t_v1 = TransactionItem(
            id="TX_MUTATE_99",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Step 1",
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("5.0"),
            limit_price=Decimal("100.0"),
            status="PENDING",
            is_cancellation=False,
            last_event_datetime=base_time,
        )
        ingest_transaction_versions(test_db, [t_v1])

        cur1 = get_current_transactions(test_db, isin="IE00B4L5Y983")
        assert len(cur1) == 1
        assert cur1[0]["version_number"] == 1
        assert cur1[0]["status"] == "PENDING"
        assert cur1[0]["supersedes_id"] is None
        v1_id = cur1[0]["version_id"]

        # 2. Version 2: SETTLED
        t_v2 = TransactionItem(
            id="TX_MUTATE_99",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Step 1 settled",
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("5.0"),
            limit_price=Decimal("100.0"),
            status="SETTLED",
            is_cancellation=False,
            last_event_datetime=base_time + timedelta(hours=3),
        )
        ingest_transaction_versions(test_db, [t_v2])

        cur2 = get_current_transactions(test_db, isin="IE00B4L5Y983")
        assert len(cur2) == 1
        assert cur2[0]["version_number"] == 2
        assert cur2[0]["status"] == "SETTLED"
        assert cur2[0]["supersedes_id"] == v1_id
        v2_id = cur2[0]["version_id"]

        # 3. Version 3: CANCELLED (cancellation flag = True)
        t_v3 = TransactionItem(
            id="TX_MUTATE_99",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Step 1 cancelled post-settlement",
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("5.0"),
            limit_price=Decimal("100.0"),
            status="CANCELLED",
            is_cancellation=True,
            last_event_datetime=base_time + timedelta(hours=6),
        )
        ingest_transaction_versions(test_db, [t_v3])

        cur3 = get_current_transactions(test_db, isin="IE00B4L5Y983")
        assert len(cur3) == 1
        assert cur3[0]["version_number"] == 3
        assert cur3[0]["status"] == "CANCELLED"
        assert cur3[0]["is_cancellation"] == 1
        assert cur3[0]["supersedes_id"] == v2_id

        # Directly query transaction_versions to confirm full history is intact
        conn = test_db.get_connection()
        try:
            rows = conn.execute(
                "SELECT version_id, version_number, status, supersedes_id FROM transaction_versions WHERE broker_tx_id = 'TX_MUTATE_99' ORDER BY version_number ASC"
            ).fetchall()
            assert len(rows) == 3
            assert rows[0]["version_number"] == 1 and rows[0]["supersedes_id"] is None
            assert rows[1]["version_number"] == 2 and rows[1]["supersedes_id"] == v1_id
            assert rows[2]["version_number"] == 3 and rows[2]["supersedes_id"] == v2_id

            # Verify v_transactions_current contains ONLY version 3
            view_rows = conn.execute(
                "SELECT version_id, version_number FROM v_transactions_current WHERE broker_tx_id = 'TX_MUTATE_99'"
            ).fetchall()
            assert len(view_rows) == 1
            assert view_rows[0]["version_number"] == 3
        finally:
            conn.close()

    def test_dag_branching_rejection_at_unique_index(self, test_db):
        """Attempt to fork the version DAG by inserting a second version superseding the same version_id."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Seed v1
        v1_dict = {
            "version_id": "txv_root_001",
            "broker_tx_id": "TX_FORK_01",
            "supersedes_id": None,
            "version_number": 1,
            "tx_type": "BUY",
            "amount": "-100.00",
            "currency": "EUR",
            "status": "PENDING",
            "is_cancellation": 0,
            "event_time": now_iso,
            "flow_classification": "INTERNAL_TRADE",
            "payload_json": "{}",
            "created_at": now_iso,
        }
        h1 = compute_transaction_version_hash(v1_dict)
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, supersedes_id, version_number,
                    tx_type, amount, currency, status, is_cancellation, event_time,
                    flow_classification, payload_json, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    v1_dict["version_id"], v1_dict["broker_tx_id"], v1_dict["supersedes_id"],
                    v1_dict["version_number"], v1_dict["tx_type"], v1_dict["amount"],
                    v1_dict["currency"], v1_dict["status"], v1_dict["is_cancellation"],
                    v1_dict["event_time"], v1_dict["flow_classification"],
                    v1_dict["payload_json"], v1_dict["created_at"], h1,
                ),
            )

        # Seed v2 (child of v1)
        v2_dict = {
            "version_id": "txv_child_002",
            "broker_tx_id": "TX_FORK_01",
            "supersedes_id": "txv_root_001",
            "version_number": 2,
            "tx_type": "BUY",
            "amount": "-100.00",
            "currency": "EUR",
            "status": "SETTLED",
            "is_cancellation": 0,
            "event_time": now_iso,
            "flow_classification": "INTERNAL_TRADE",
            "payload_json": "{}",
            "created_at": now_iso,
        }
        h2 = compute_transaction_version_hash(v2_dict)
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, supersedes_id, version_number,
                    tx_type, amount, currency, status, is_cancellation, event_time,
                    flow_classification, payload_json, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    v2_dict["version_id"], v2_dict["broker_tx_id"], v2_dict["supersedes_id"],
                    v2_dict["version_number"], v2_dict["tx_type"], v2_dict["amount"],
                    v2_dict["currency"], v2_dict["status"], v2_dict["is_cancellation"],
                    v2_dict["event_time"], v2_dict["flow_classification"],
                    v2_dict["payload_json"], v2_dict["created_at"], h2,
                ),
            )

        # Adversarial attempt: Insert v2_fork also superseding txv_root_001
        v2_fork_dict = {
            "version_id": "txv_fork_002_alt",
            "broker_tx_id": "TX_FORK_01",
            "supersedes_id": "txv_root_001",  # FORK ATTEMPT!
            "version_number": 2,
            "tx_type": "BUY",
            "amount": "-100.00",
            "currency": "EUR",
            "status": "REJECTED",
            "is_cancellation": 1,
            "event_time": now_iso,
            "flow_classification": "INTERNAL_TRADE",
            "payload_json": "{}",
            "created_at": now_iso,
        }
        h_fork = compute_transaction_version_hash(v2_fork_dict)

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: transaction_versions.supersedes_id"):
            with test_db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO transaction_versions (
                        version_id, broker_tx_id, supersedes_id, version_number,
                        tx_type, amount, currency, status, is_cancellation, event_time,
                        flow_classification, payload_json, created_at, record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        v2_fork_dict["version_id"], v2_fork_dict["broker_tx_id"],
                        v2_fork_dict["supersedes_id"], v2_fork_dict["version_number"],
                        v2_fork_dict["tx_type"], v2_fork_dict["amount"],
                        v2_fork_dict["currency"], v2_fork_dict["status"],
                        v2_fork_dict["is_cancellation"], v2_fork_dict["event_time"],
                        v2_fork_dict["flow_classification"], v2_fork_dict["payload_json"],
                        v2_fork_dict["created_at"], h_fork,
                    ),
                )

    def test_immutability_triggers_abort_direct_mutations(self, test_db):
        """Verify SQLite BEFORE triggers prevent direct UPDATE, DELETE, and OVERWRITE."""
        now_iso = datetime.now(timezone.utc).isoformat()
        row = {
            "version_id": "txv_locked_01",
            "broker_tx_id": "TX_LOCK_01",
            "supersedes_id": None,
            "version_number": 1,
            "tx_type": "DEPOSIT",
            "amount": "1000.00",
            "currency": "EUR",
            "status": "SETTLED",
            "is_cancellation": 0,
            "event_time": now_iso,
            "flow_classification": "EXTERNAL_INFLOW",
            "payload_json": "{}",
            "created_at": now_iso,
        }
        h = compute_transaction_version_hash(row)
        with test_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, supersedes_id, version_number,
                    tx_type, amount, currency, status, is_cancellation, event_time,
                    flow_classification, payload_json, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["version_id"], row["broker_tx_id"], row["supersedes_id"],
                    row["version_number"], row["tx_type"], row["amount"],
                    row["currency"], row["status"], row["is_cancellation"],
                    row["event_time"], row["flow_classification"],
                    row["payload_json"], row["created_at"], h,
                ),
            )

        # 1. Direct UPDATE forbidden
        with pytest.raises(sqlite3.IntegrityError, match="transaction_versions degistirilemez"):
            with test_db.transaction() as conn:
                conn.execute("UPDATE transaction_versions SET amount = '9999.00' WHERE version_id = 'txv_locked_01'")

        # 2. Direct DELETE forbidden
        with pytest.raises(sqlite3.IntegrityError, match="transaction_versions kaydi silinemez"):
            with test_db.transaction() as conn:
                conn.execute("DELETE FROM transaction_versions WHERE version_id = 'txv_locked_01'")

        # 3. Direct OVERWRITE with duplicate record_hash forbidden
        with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
            with test_db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO transaction_versions (
                        version_id, broker_tx_id, supersedes_id, version_number,
                        tx_type, amount, currency, status, is_cancellation, event_time,
                        flow_classification, payload_json, created_at, record_hash
                    ) VALUES ('txv_locked_02', 'TX_LOCK_02', NULL, 1, 'DEPOSIT', '1000.00', 'EUR', 'SETTLED', 0, ?, 'EXTERNAL_INFLOW', '{}', ?, ?)
                    """,
                    (now_iso, now_iso, h),  # Same record_hash!
                )


# ==============================================================================
# SECTION 3: Unknown / Malformed Transaction Types & Fail-Safe Protection
# ==============================================================================


class TestUnknownMalformedTransactionTypes:
    """Stress-test classifier handling of unsupported transaction types and fail-safe return halting."""

    @pytest.mark.parametrize(
        "exotic_type",
        [
            "CRYPTO_STAKING",
            "UNKNOWN_REWARD",
            "AIRDROP_BONUS",
            "NFT_MINT_FEE",
            "MARGIN_CALL_LIQUIDATION",
            "TOKEN_BURN",
            "PLEDGE_COLLATERAL",
            "",
            "   ",
            "; DROP TABLE transaction_versions; --",
            "SELECT * FROM accounts",
        ],
    )
    def test_exotic_malformed_types_classification(self, test_db, exotic_type):
        """Ensure exotic and injection transaction types are flagged as NEEDS_REVIEW and logged to audit."""
        tx_id = f"TX_EXOTIC_{hash(exotic_type) & 0xFFFFFF}"
        res = classify_transaction(
            {"type": exotic_type, "id": tx_id, "amount": "123.45"},
            db=test_db,
        )
        assert res.status == ClassificationStatus.NEEDS_REVIEW
        assert res.classification == FlowClassification.UNKNOWN
        assert res.affects_twr is False
        assert res.affects_mwr is False
        assert res.reason is not None

        # Verify audit event was logged
        conn = test_db.get_connection()
        try:
            row = conn.execute(
                "SELECT action, entity_id, payload_json FROM audit_events WHERE action = 'TRANSACTION_CLASSIFICATION_FAILED' AND entity_id = ?",
                (tx_id,),
            ).fetchone()
            assert row is not None
            payload = json.loads(row["payload_json"])
            assert payload["broker_tx_id"] == tx_id
            assert payload["amount"] == "123.45"
        finally:
            conn.close()

    def test_ingestion_of_unknown_type_and_realized_returns_halt(self, test_db):
        """Verify that ingesting an unknown type into ledger causes realized_returns to halt without hallucinating."""
        now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Normal settled deposit and buy
        t_dep = TransactionItem(
            id="TX_VALID_DEP",
            type="DEPOSIT",
            amount=Decimal("1000.00"),
            currency="EUR",
            status="SETTLED",
            last_event_datetime=now,
        )
        t_buy = TransactionItem(
            id="TX_VALID_BUY",
            type="SECURITY_TRANSACTION",
            security_transaction_type="BUY",
            side="BUY",
            isin="IE00B4L5Y983",
            description="Buy valid",
            amount=Decimal("-500.00"),
            currency="EUR",
            quantity=Decimal("5.0"),
            limit_price=Decimal("100.0"),
            status="SETTLED",
            last_event_datetime=now + timedelta(hours=1),
        )

        # 2. Rogue unknown transaction
        t_rogue = TransactionItem(
            id="TX_ROGUE_STAKE",
            type="CRYPTO_STAKING",
            description="Staking reward",
            amount=Decimal("50.00"),
            currency="EUR",
            status="SETTLED",
            last_event_datetime=now + timedelta(hours=2),
        )

        ingest_transaction_versions(test_db, [t_dep, t_buy, t_rogue])

        # Confirm ledger stored the rogue transaction as UNKNOWN
        cur = get_current_transactions(test_db)
        rogue_cur = [c for c in cur if c["broker_tx_id"] == "TX_ROGUE_STAKE"][0]
        assert rogue_cur["flow_classification"] == "UNKNOWN"

        # 3. Invoke realized_returns with current transactions
        ret = realized_returns(
            transactions=cur,
            holdings={"IE00B4L5Y983": Decimal("5.0")},
            holding_values={"IE00B4L5Y983": Decimal("550.00")},
            broker_fifo={"IE00B4L5Y983": Decimal("100.00")},
            cash_now=Decimal("550.00"),
            as_of=now + timedelta(days=1),
            series_by_isin={},
        )

        # Must halt immediately
        assert ret.available is False
        assert "Getiri hesabı durduruldu" in ret.reason
        assert "Tasarım gereği eksik veriyle uydurma getiri hesaplanmaz" in ret.reason
        assert ret.gain is None
        assert ret.twr_pct is None
        assert ret.mdietz_pct is None
        assert ret.xirr_pct is None
        assert "needs_review" in ret.warnings[0]


# ==============================================================================
# SECTION 4: CLI Flag Injection & Security Harassment
# ==============================================================================


class TestCLIFlagInjectionAndSecurity:
    """Stress-test ScalableReader against hostile CLI parameter injection payloads."""

    @pytest.mark.parametrize(
        "malicious_from_time",
        [
            # Shell command separators & expansions
            "2026-10-20; rm -rf /",
            "2026-10-20 | cat /etc/passwd",
            "2026-10-20 & echo pwned",
            "2026-10-20 && id",
            "2026-10-20\nwhoami",
            "2026-10-20`id`",
            "2026-10-20$(whoami)",
            "$(id)",
            "`uname -a`",
            "; sleep 10 ;",
            # SQL injection syntax
            "2026-10-20T00:00:00Z' OR '1'='1",
            "2026-10-20T00:00:00Z; DROP TABLE transaction_versions; --",
            "2026-10-20T00:00:00Z' UNION SELECT * FROM users --",
            # Invalid formats / non-ISO
            "yesterday",
            "now",
            "2026/10/20",
            "20-10-2026",
            "1729000000",
            # Forbidden write words
            "2026-10-20T00:00:00Z-buy",
            "2026-10-20T00:00:00Z-sell",
            "2026-10-20T00:00:00Z-trade",
            "2026-10-20T00:00:00Z-rm",
            # Buffer overflow attempt
            "2026-10-20T00:00:00Z" + "0" * 4000,
        ],
    )
    def test_from_time_injection_payloads_strictly_rejected(self, malicious_from_time):
        """Verify that any non-ISO or adversarial from_time string raises ScalableSecurityViolation before runner invocation."""
        runner_called = []

        def mock_runner(cmd, timeout=None):
            runner_called.append(cmd)
            return 0, json.dumps({"ok": True, "data": {"result": {"items": [], "cursor": None}}}), ""

        reader = ScalableReader(runner=mock_runner)

        with pytest.raises(ScalableSecurityViolation):
            reader.get_history(from_time=malicious_from_time)

        # Critical: Subprocess runner MUST NEVER have been executed!
        assert len(runner_called) == 0, f"Subprocess runner was invoked with hostile argument: {runner_called}"

    @pytest.mark.parametrize(
        "malicious_to_time",
        [
            "2026-10-25; touch /tmp/pwned",
            "2026-10-25 && rm -rf ~",
            "2026-10-25' OR '1'='1",
            "2026-10-25T12:00:00Z`reboot`",
        ],
    )
    def test_to_time_injection_payloads_strictly_rejected(self, malicious_to_time):
        """Verify that malicious to_time payloads are similarly rejected without execution."""
        runner_called = []

        def mock_runner(cmd, timeout=None):
            runner_called.append(cmd)
            return 0, json.dumps({"ok": True, "data": {"result": {"items": [], "cursor": None}}}), ""

        reader = ScalableReader(runner=mock_runner)

        with pytest.raises(ScalableSecurityViolation):
            reader.get_history(to_time=malicious_to_time)

        assert len(runner_called) == 0

    def test_unauthorized_flags_and_write_commands_rejected(self):
        """Verify that arbitrary flags or forbidden subcommands are rejected."""
        runner_called = []

        def mock_runner(cmd, timeout=None):
            runner_called.append(cmd)
            return 0, "{}", ""

        reader = ScalableReader(runner=mock_runner)

        # Attempt to pass forbidden write words or arbitrary flags
        with pytest.raises(ScalableSecurityViolation):
            reader._execute_raw("history", ["--delete", "all"])

        with pytest.raises(ScalableSecurityViolation):
            reader._execute_raw("history", ["--exec", "bash"])

        with pytest.raises(ScalableSecurityViolation):
            reader._execute_raw("history", ["--confirm"])

        assert len(runner_called) == 0


# ==============================================================================
# SECTION 5: Incremental Lookback Boundary & Corporate Actions Authorization
# ==============================================================================


class TestIncrementalLookbackAndCorporateAuth:
    """Test boundary edge cases in 7-day calculation and corporate actions authorization."""

    def test_incremental_from_time_boundary_values(self, test_db):
        """Test calculation of from_time under empty, corrupted, and extreme overlap conditions."""
        conn = test_db.get_connection()
        try:
            # 1. Empty DB -> None
            assert calculate_incremental_from_time(conn) is None

            # 2. Add an event with unparseable corrupted timestamp directly to test robustness
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO transaction_versions (
                    version_id, broker_tx_id, version_number, tx_type,
                    amount, currency, status, is_cancellation, event_time,
                    flow_classification, payload_json, created_at, record_hash
                ) VALUES ('txv_corrupt', 'BTX_CORRUPT', 1, 'BUY', '-10.0', 'EUR', 'SETTLED', 0, 'INVALID_DATE_STRING', 'INTERNAL_TRADE', '{}', ?, 'dummy_hash')
                """,
                (now_iso,),
            )
            # Should catch parsing failure and return None without crashing
            res = calculate_incremental_from_time(conn)
            assert res is None
        finally:
            conn.close()

    def test_corporate_action_approved_by_mandatory_validation(self):
        """Verify that CorporateActionRecord strictly enforces approved_by presence and non-whitespace."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Valid action
        ca = CorporateActionRecord(
            isin="IE00B4L5Y983",
            action_type=CorporateActionType.SPLIT,
            ratio=Decimal("2.0"),
            effective_date="2026-11-01",
            description="2:1 Stock Split",
            approved_by="Auditor_Alice",
            created_at=now_iso,
        )
        assert ca.approved_by == "Auditor_Alice"

        # Empty string approved_by -> ValidationError
        with pytest.raises(ValueError):
            CorporateActionRecord(
                isin="IE00B4L5Y983",
                action_type=CorporateActionType.SPLIT,
                ratio=Decimal("2.0"),
                effective_date="2026-11-01",
                description="2:1 Stock Split",
                approved_by="",
            )

        # Whitespace-only approved_by -> ValidationError
        with pytest.raises(ValueError, match="approved_by cannot be empty or whitespace"):
            CorporateActionRecord(
                isin="IE00B4L5Y983",
                action_type=CorporateActionType.SPLIT,
                ratio=Decimal("2.0"),
                effective_date="2026-11-01",
                description="2:1 Stock Split",
                approved_by="    \t \n",
            )
