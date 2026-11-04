"""End-to-End Pipeline Integration Test for ETF Yatırım Masası (Phase 0 & Phase 1).

This test suite executes the complete, unified data pipeline across all core subsystems:
1. JobQueue initialization, deduplication, and state machine lifecycle.
2. Read-only ScalableReader ingestion of holdings, cash-breakdown, and quotes via mock fixtures.
3. IdentityRegistry resolution and ISO 6166 Luhn Modulus-10 ISIN verification.
4. CalendarAdapter XETR market session and quote age evaluation with zero-assumption fallback.
5. Append-only persistence in SQLite SnapshotStore (raw_objects, snapshots, observations, quotes).
6. Engine-level BEFORE UPDATE and BEFORE DELETE immutability trigger enforcement.
7. Cryptographic SHA-256 hash chain verification across snapshots and audit_events.
8. Controlled progression to PUBLISHED state with immutable valuation summary.
9. External AI prompt specifications loading and SHA-256 audit manifest verification.
10. Tax module passivation contract and zero-import AST forensic audit.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
import pytest

from masa.audit import (
    AuditLogger,
    InvalidStateTransitionError,
    JobQueue,
    JobState,
    JobStateError,
    WorkQueue,
)
from masa.calendar import (
    CalendarAdapter,
    MarketSessionState,
    QuoteAgeAssessment,
    TradingCalendarAdapter,
)
from masa.identity import (
    IdentityRegistry,
    Instrument,
    InstrumentType,
    Issuer,
    Listing,
    calculate_isin_check_digit,
    is_valid_isin,
    validate_isin,
)
from masa.ingestion import (
    CashBreakdownResult,
    PositionsResult,
    QuoteData,
    ScalableReader,
    ScalableSecurityViolation,
    SingleISINViolation,
)
from masa.prompts import (
    LoadedPrompt,
    PromptIntegrityError,
    PromptLoader,
    PromptMetadata,
)
from masa.storage import (
    GENESIS_HASH,
    DatabaseManager,
    HashChainEngine,
    SnapshotStore,
    get_database_connection,
    verify_hash_chain,
)
from masa.tax import TAX_LEDGER_ENABLED, TaxLedgerStub


class TestE2EPipelineFullWorkflow:
    """Verifies the complete Phase 0 & Phase 1 operational workflow end-to-end."""

    def test_e2e_complete_ingestion_validation_and_publishing_lifecycle(
        self, tmp_path: Path, mock_runner_factory, mock_fixture_loader
    ) -> None:
        """Execute complete pipeline run:

        queued -> collecting -> validating -> calculating -> reviewing -> published.
        """
        # ---------------------------------------------------------------------
        # 1. SETUP: Initialize Database, Storage, Audit, and JobQueue
        # ---------------------------------------------------------------------
        db_file = tmp_path / "private" / "e2e_masa.db"
        db_mgr = DatabaseManager(db_path=db_file)
        db_mgr.initialize_schema()

        # Verify directory & file permissions
        assert oct(db_file.parent.stat().st_mode)[-3:] == "700"
        assert oct(db_file.stat().st_mode)[-3:] == "600"

        audit_logger = AuditLogger(db_mgr)
        job_queue = JobQueue(db_mgr, audit_logger=audit_logger)
        snapshot_store = SnapshotStore(db_mgr)

        # ---------------------------------------------------------------------
        # 2. STATE MACHINE: Enqueue Job (Idempotency & Initial State)
        # ---------------------------------------------------------------------
        job_type = "e2e_portfolio_sync"
        dedup_key = "2026-10-30:e2e_run_001"
        job_params = {"source": "scalable_cli", "environment": "production_test"}

        enqueued_dict, is_new = job_queue.enqueue(
            job_type=job_type,
            dedup_key=dedup_key,
            params=job_params,
        )
        assert is_new is True
        job_id = enqueued_dict["job_id"]
        assert enqueued_dict["status"] == JobState.QUEUED.value

        # Idempotency assertion: re-enqueueing same dedup_key returns identical record
        dup_dict, is_dup_new = job_queue.enqueue(
            job_type=job_type,
            dedup_key=dedup_key,
            params=job_params,
        )
        assert is_dup_new is False
        assert dup_dict["job_id"] == job_id

        # ---------------------------------------------------------------------
        # 3. STATE MACHINE: Transition to COLLECTING
        # ---------------------------------------------------------------------
        job_queue.transition(job_id, to_status=JobState.COLLECTING)
        current_job = job_queue.get_job(job_id)
        assert current_job is not None
        assert current_job.status == JobState.COLLECTING
        assert current_job.started_at is not None

        # ---------------------------------------------------------------------
        # 4. INGESTION: Read Holdings, Cash, and Quote via ScalableReader
        # ---------------------------------------------------------------------
        runner = mock_runner_factory()
        reader = ScalableReader(runner=runner)

        # A. Ingest Holdings
        positions_res: PositionsResult = reader.get_positions()
        assert positions_res.count == 2
        assert len(positions_res.items) == 2

        pos_spdr = next(p for p in positions_res.items if p.isin == "IE00B3YLTY66")
        assert pos_spdr.name == "SPDR MSCI ACWI IMI"
        assert pos_spdr.quantity == Decimal("158")
        assert pos_spdr.valuation == Decimal("1843.23")
        assert pos_spdr.valuation_currency == "EUR"
        assert pos_spdr.fifo_price == Decimal("11.593165")

        pos_ishares = next(p for p in positions_res.items if p.isin == "IE00BKM4GZ66")
        assert pos_ishares.name == "iShares Core MSCI EM IMI"
        assert pos_ishares.quantity == Decimal("22")
        assert pos_ishares.valuation == Decimal("989.92")

        # B. Ingest Cash
        cash_res: CashBreakdownResult = reader.get_cash()
        assert cash_res.cash_balance == Decimal("1250.50")
        assert cash_res.buying_power == Decimal("1250.50")
        assert cash_res.available_credit_line == Decimal("0")

        # C. Ingest Quote
        quote_apple: QuoteData = reader.get_quote("US0378331005")
        assert quote_apple.isin == "US0378331005"
        assert quote_apple.name == "Apple Inc."
        assert quote_apple.bid == Decimal("309.65")
        assert quote_apple.ask == Decimal("309.85")
        assert quote_apple.mid == Decimal("309.75")
        assert quote_apple.computed_mid == Decimal("309.75")
        assert quote_apple.spread == Decimal("0.20")
        expected_spread_pct = (Decimal("0.20") / Decimal("309.75")) * Decimal("100")
        assert quote_apple.spread_pct == expected_spread_pct
        assert quote_apple.is_outdated is False

        # ---------------------------------------------------------------------
        # 5. STATE MACHINE: Transition to VALIDATING
        # ---------------------------------------------------------------------
        job_queue.transition(job_id, to_status=JobState.VALIDATING)
        assert job_queue.get_job(job_id).status == JobState.VALIDATING

        # ---------------------------------------------------------------------
        # 6. IDENTITY & CONTRACT VALIDATION: Luhn Check & IdentityRegistry
        # ---------------------------------------------------------------------
        all_ingested_isins = [p.isin for p in positions_res.items] + [quote_apple.isin]

        # Assert all valid ISINs pass ISO 6166 Luhn check
        for candidate_isin in all_ingested_isins:
            assert is_valid_isin(candidate_isin) is True
            assert validate_isin(candidate_isin) == candidate_isin

        # Assert adversarial corrupted ISIN fails check digit verification
        corrupted_isin = "IE00B3YLTY67"  # Check digit 6 tampered to 7
        assert is_valid_isin(corrupted_isin) is False
        with pytest.raises(ValueError, match="check digit mismatch"):
            validate_isin(corrupted_isin)

        # Build IdentityRegistry catalogue
        registry = IdentityRegistry()

        # Register Issuers
        iss_ssga = Issuer(
            issuer_id="iss_ssga_ie",
            name="State Street Global Advisors Europe Limited",
            country="IE",
        )
        iss_ishares = Issuer(
            issuer_id="iss_ishares_ie",
            name="BlackRock Asset Management Ireland Limited",
            country="IE",
        )
        iss_apple = Issuer(
            issuer_id="iss_apple_us",
            name="Apple Inc.",
            country="US",
        )
        registry.register_issuer(iss_ssga)
        registry.register_issuer(iss_ishares)
        registry.register_issuer(iss_apple)

        # Register Instruments (UCITS explicit invariant)
        inst_spdr = Instrument(
            instrument_id="inst_spdr_acwi",
            isin="IE00B3YLTY66",
            name="SPDR MSCI ACWI IMI UCITS ETF",
            instrument_type=InstrumentType.ETF,
            issuer_id=iss_ssga.issuer_id,
            is_ucits=True,  # Explicitly asserted; never inferred from country
            base_currency="EUR",
        )
        inst_ishares = Instrument(
            instrument_id="inst_ishares_em",
            isin="IE00BKM4GZ66",
            name="iShares Core MSCI EM IMI UCITS ETF",
            instrument_type=InstrumentType.ETF,
            issuer_id=iss_ishares.issuer_id,
            is_ucits=True,
            base_currency="EUR",
        )
        inst_apple = Instrument(
            instrument_id="inst_apple_equity",
            isin="US0378331005",
            name="Apple Inc. Common Stock",
            instrument_type=InstrumentType.EQUITY,
            issuer_id=iss_apple.issuer_id,
            is_ucits=False,
            base_currency="USD",
        )
        registry.register_instrument(inst_spdr)
        registry.register_instrument(inst_ishares)
        registry.register_instrument(inst_apple)

        # Register Listings
        list_spdr_xetr = Listing(
            listing_id="list_xetr_spyi_eur",
            instrument_id=inst_spdr.instrument_id,
            mic="XETR",
            ticker="SPYI",
            currency="EUR",
            is_primary=True,
        )
        list_ishares_xetr = Listing(
            listing_id="list_xetr_is3n_eur",
            instrument_id=inst_ishares.instrument_id,
            mic="XETR",
            ticker="IS3N",
            currency="EUR",
            is_primary=True,
        )
        list_apple_xnas = Listing(
            listing_id="list_xnas_aapl_usd",
            instrument_id=inst_apple.instrument_id,
            mic="XNAS",
            ticker="AAPL",
            currency="USD",
            is_primary=True,
        )
        registry.register_listing(list_spdr_xetr)
        registry.register_listing(list_ishares_xetr)
        registry.register_listing(list_apple_xnas)

        # Verify lookup contracts
        resolved_spdr = registry.get_instrument_by_isin("IE00B3YLTY66")
        assert resolved_spdr is not None
        assert resolved_spdr.is_ucits is True
        assert registry.get_instrument_by_isin("US0378331005").is_ucits is False

        # ---------------------------------------------------------------------
        # 7. TEMPORAL & CALENDAR VALIDATION: Session State & Quote Age
        # ---------------------------------------------------------------------
        calendar_adapter = CalendarAdapter(venue_mic="XETR")
        # Observation time during open regular XETR session (Friday, 2026-10-30 09:31 UTC)
        obs_time = datetime(2026, 10, 30, 9, 31, 0, tzinfo=timezone.utc)

        # A. Verified XETR exchange evaluation
        assessment_xetr: QuoteAgeAssessment = calendar_adapter.assess_quote_freshness(
            quote_time=quote_apple.timestamp_utc,
            snapshot_time=obs_time,
            venue_mic="XETR",
        )
        assert assessment_xetr.session_state == MarketSessionState.OPEN
        assert assessment_xetr.is_stale is False
        assert assessment_xetr.calendar_name == "XETR"
        assert assessment_xetr.age_seconds > 0.0

        # B. Zero-Assumption Rule: Unknown/Consolidated exchange must NOT assume XETR
        assessment_unverified = calendar_adapter.assess_quote_freshness(
            quote_time=quote_apple.timestamp_utc,
            snapshot_time=obs_time,
            venue_mic=None,  # No exchange specified
        )
        assert assessment_unverified.session_state == MarketSessionState.UNKNOWN
        assert assessment_unverified.calendar_name is None
        assert "XETR calendar NOT assumed" in assessment_unverified.diagnostic_note

        # C. Temporal causality: Future quote must be rejected
        future_quote_time = obs_time + timedelta(minutes=10)
        with pytest.raises(ValueError, match="Future quote rejected"):
            calendar_adapter.assess_quote_freshness(
                quote_time=future_quote_time,
                snapshot_time=obs_time,
                venue_mic="XETR",
            )

        # ---------------------------------------------------------------------
        # 8. PERSISTENCE: Record Raw Objects and Snapshots into SnapshotStore
        # ---------------------------------------------------------------------
        raw_holdings_text = mock_fixture_loader("sample_holdings.json")
        raw_cash_text = mock_fixture_loader("sample_cash_breakdown.json")
        raw_quote_text = mock_fixture_loader("sample_quote_apple.json")

        raw_id_holdings, is_new_h = snapshot_store.store_raw_object(
            source="sc_cli.holdings",
            raw_payload=raw_holdings_text,
            retrieved_at=obs_time,
            record_count=len(positions_res.items),
        )
        assert is_new_h is True

        raw_id_cash, is_new_c = snapshot_store.store_raw_object(
            source="sc_cli.cash",
            raw_payload=raw_cash_text,
            retrieved_at=obs_time,
            record_count=1,
        )
        assert is_new_c is True

        raw_id_quote, is_new_q = snapshot_store.store_raw_object(
            source="sc_cli.quote",
            raw_payload=raw_quote_text,
            retrieved_at=obs_time,
            record_count=1,
        )
        assert is_new_q is True

        # Save Positions Snapshot
        positions_payload = [
            {
                "isin": p.isin,
                "display_name": p.name,
                "quantity": str(p.quantity),
                "unit_price_displayed": str(p.quote_mid_price),
                "value_eur": str(p.valuation),
                "currency": p.valuation_currency,
                "broker_cost_basis": str(p.fifo_price),
                "observed_at": p.quote_timestamp_utc.isoformat(),
            }
            for p in positions_res.items
        ]
        snap_id_pos = snapshot_store.save_position_snapshot(
            snapshot_id="snap_pos_001",
            raw_object_id=raw_id_holdings,
            source="sc_cli",
            started_at=obs_time,
            completed_at=obs_time,
            positions_data=positions_payload,
        )
        assert snap_id_pos == "snap_pos_001"

        # Save Cash Snapshot
        cash_payload = [
            {
                "account_id_masked": cash_res.account_id or "ACC_MASKED_01",
                "currency": "EUR",
                "settled_cash": str(cash_res.cash_balance),
                "total_cash": str(cash_res.cash_balance),
                "observed_at": obs_time.isoformat(),
            }
        ]
        snap_id_cash = snapshot_store.save_cash_snapshot(
            snapshot_id="snap_cash_001",
            raw_object_id=raw_id_cash,
            source="sc_cli",
            started_at=obs_time,
            completed_at=obs_time,
            cash_data=cash_payload,
        )
        assert snap_id_cash == "snap_cash_001"

        # Save Quote Snapshot
        quotes_payload = [
            {
                "isin": quote_apple.isin,
                "currency": quote_apple.currency,
                "bid": str(quote_apple.bid),
                "ask": str(quote_apple.ask),
                "provider_mid": str(quote_apple.mid),
                "computed_mid": str(quote_apple.computed_mid),
                "spread": str(quote_apple.spread),
                "spread_pct": str(quote_apple.spread_pct),
                "quote_timestamp": quote_apple.timestamp_utc.isoformat(),
                "retrieved_at": obs_time.isoformat(),
                "quality_status": "FRESH",
            }
        ]
        snap_id_quote = snapshot_store.save_quote_snapshot(
            snapshot_id="snap_quote_001",
            raw_object_id=raw_id_quote,
            source="sc_cli",
            started_at=obs_time,
            completed_at=obs_time,
            quotes_data=quotes_payload,
        )
        assert snap_id_quote == "snap_quote_001"

        # ---------------------------------------------------------------------
        # 9. ENGINE IMMUTABILITY TRIGGERS: Assert UPDATE / DELETE Abort
        # ---------------------------------------------------------------------
        with db_mgr.transaction() as conn:
            cursor = conn.cursor()

            # Attempt UPDATE on snapshots
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
                cursor.execute(
                    "UPDATE snapshots SET quality_status = 'TAMPERED' WHERE snapshot_id = 'snap_pos_001'"
                )

            # Attempt DELETE on snapshots
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
                cursor.execute("DELETE FROM snapshots WHERE snapshot_id = 'snap_pos_001'")

            # Attempt UPDATE on position_observations
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
                cursor.execute(
                    "UPDATE position_observations SET value_eur = '99999.99' WHERE isin = 'IE00B3YLTY66'"
                )

            # Attempt DELETE on quotes
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="silinemez"):
                cursor.execute("DELETE FROM quotes WHERE isin = 'US0378331005'")

            # Attempt UPDATE on cash_observations
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
                cursor.execute("UPDATE cash_observations SET total_cash = '0.00'")

            # Attempt UPDATE on audit_events
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
                cursor.execute("UPDATE audit_events SET actor = 'tampered_actor'")

        # ---------------------------------------------------------------------
        # 10. CRYPTOGRAPHIC INTEGRITY: Verify SHA-256 Hash Chains
        # ---------------------------------------------------------------------
        # Verify snapshot hash chain
        valid_snapshots, snap_err = snapshot_store.verify_integrity()
        assert valid_snapshots is True, f"Snapshot chain compromised: {snap_err}"
        assert snap_err is None

        # Verify audit events hash chain
        valid_audit, audit_err = audit_logger.verify_integrity()
        assert valid_audit is True, f"Audit chain compromised: {audit_err}"
        assert audit_err is None

        # Verify cryptographic linking in database rows
        with db_mgr.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT snapshot_id, prev_hash, curr_hash FROM snapshots ORDER BY rowid ASC")
            rows = cur.fetchall()
            assert len(rows) == 3
            assert rows[0]["prev_hash"] == GENESIS_HASH
            assert rows[1]["prev_hash"] == rows[0]["curr_hash"]
            assert rows[2]["prev_hash"] == rows[1]["curr_hash"]

        # ---------------------------------------------------------------------
        # 11. STATE MACHINE: Advance to PUBLISHED with Valuation Summary
        # ---------------------------------------------------------------------
        # Verify illegal jump directly to published is rejected
        with pytest.raises((JobStateError, InvalidStateTransitionError)):
            job_queue.transition(job_id, to_status=JobState.PUBLISHED)

        # Advance legally: validating -> calculating -> reviewing -> published
        job_queue.transition(job_id, to_status=JobState.CALCULATING)
        assert job_queue.get_job(job_id).status == JobState.CALCULATING

        job_queue.transition(job_id, to_status=JobState.REVIEWING)
        assert job_queue.get_job(job_id).status == JobState.REVIEWING

        total_holdings_val = sum((p.valuation for p in positions_res.items), Decimal("0"))
        total_portfolio_equity = total_holdings_val + cash_res.cash_balance

        published_summary = {
            "portfolio_id": positions_res.portfolio_id or "PORT_TEST_MASKED_01",
            "positions_count": len(positions_res.items),
            "total_holdings_eur": str(total_holdings_val),
            "cash_balance_eur": str(cash_res.cash_balance),
            "total_portfolio_equity_eur": str(total_portfolio_equity),
            "snapshots": [snap_id_pos, snap_id_cash, snap_id_quote],
        }

        job_queue.transition(
            job_id,
            to_status=JobState.PUBLISHED,
            result=published_summary,
        )

        final_job = job_queue.get_job(job_id)
        assert final_job is not None
        assert final_job.status == JobState.PUBLISHED
        assert final_job.completed_at is not None
        assert final_job.result == published_summary
        assert final_job.result["total_portfolio_equity_eur"] == str(Decimal("1843.23") + Decimal("989.92") + Decimal("1250.50"))

        # Re-verify audit hash chain after final publishing
        valid_audit_final, audit_err_final = audit_logger.verify_integrity()
        assert valid_audit_final is True, f"Audit chain broken after publish: {audit_err_final}"

        # ---------------------------------------------------------------------
        # 12. PROMPTS SPECIFICATION & MANIFEST AUDIT
        # ---------------------------------------------------------------------
        prompt_loader = PromptLoader()
        verified_prompts = prompt_loader.validate_required_prompts()
        assert len(verified_prompts) == 7

        manifest = prompt_loader.get_audit_manifest()
        for required_file in PromptLoader.CANONICAL_REQUIRED_PROMPTS:
            stem = required_file.removesuffix(".md")
            assert stem in manifest, f"Required prompt '{stem}' missing from audit manifest"

            entry = manifest[stem]
            assert entry["filename"] == required_file
            assert len(entry["sha256"]) == 64
            assert entry["size_bytes"] > 2000

            # Verify on-disk file hash matches manifest SHA-256 exactly
            disk_bytes = (prompt_loader.prompts_dir / required_file).read_bytes()
            assert hashlib.sha256(disk_bytes).hexdigest() == entry["sha256"]

        # Verify template rendering without financial side-effects
        research_prompt: LoadedPrompt = prompt_loader.load_prompt("llm_research_agent")
        assert research_prompt.metadata.name == "llm_research_agent"
        assert len(research_prompt.metadata.sha256) == 64

        runtime_prompt = LoadedPrompt(
            metadata=research_prompt.metadata,
            raw_content="Portfolio: {{ portfolio_id }}\nEvidence: {{ EVIDENCE_BUNDLE_JSON }}\n\n"
            + research_prompt.raw_content,
            detected_placeholders=["portfolio_id", "EVIDENCE_BUNDLE_JSON"],
        )
        rendered_prompt = runtime_prompt.render(
            {
                "portfolio_id": published_summary["portfolio_id"],
                "EVIDENCE_BUNDLE_JSON": json.dumps(published_summary),
            },
            allow_missing=False,
        )
        assert published_summary["portfolio_id"] in rendered_prompt
        assert "EVIDENCE_BUNDLE_JSON" not in rendered_prompt

        # Record prompt audit event
        audit_logger.log_event(
            actor="pipeline_verifier",
            action="PROMPT_MANIFEST_VERIFIED",
            entity_type="prompt_manifest",
            entity_id="v1.0",
            payload={"verified_count": len(verified_prompts)},
        )
        assert audit_logger.verify_integrity()[0] is True

        # ---------------------------------------------------------------------
        # 13. TAX MODULE PASSIVATION & FORENSIC AST AUDIT
        # ---------------------------------------------------------------------
        assert TAX_LEDGER_ENABLED is False

        tax_stub = TaxLedgerStub()
        with pytest.raises(NotImplementedError, match="Vergi defteri modülü devre dışıdır"):
            tax_stub.record_transaction()

        with pytest.raises(NotImplementedError, match="Vergi defteri modülü devre dışıdır"):
            tax_stub.calculate_capital_gains()

        with pytest.raises(NotImplementedError, match="Vergi defteri modülü devre dışıdır"):
            tax_stub.get_exemption_remaining()

        with pytest.raises(NotImplementedError, match="Vergi defteri modülü devre dışıdır"):
            tax_stub.generate_tax_report()

        with pytest.raises(NotImplementedError, match="Vergi defteri modülü devre dışıdır"):
            _ = tax_stub.any_arbitrary_unimplemented_tax_method()


class TestE2EImmutabilityAndSecurityEnforcement:
    """Verifies security boundaries, zero write path, and database immutability."""

    def test_zero_broker_write_path_and_single_isin_security(self) -> None:
        """Assert ScalableReader strictly forbids write commands and batch ISINs."""
        reader = ScalableReader()

        # Reject write commands
        for forbidden_cmd in ["buy", "sell", "trade", "cancel", "savings-plan", "order"]:
            with pytest.raises(ScalableSecurityViolation, match="Unauthorized broker command"):
                reader._validate_command_safety(forbidden_cmd)

        # Reject argument injection containing write tokens
        with pytest.raises(ScalableSecurityViolation, match="forbidden write token"):
            reader._validate_command_safety("quote", extra_args=["--action", "buy"])

        # Reject comma-separated batch ISIN queries
        with pytest.raises(SingleISINViolation, match="Single ISIN queries only"):
            reader.get_quote("US0378331005,IE00B3YLTY66")

        with pytest.raises(SingleISINViolation, match="Single ISIN queries only"):
            reader.get_quote("US0378331005;IE00B3YLTY66")


class TestE2EIdempotencyAndRestartRecovery:
    """Verifies database deduplication on restart and in-flight job crash recovery."""

    def test_e2e_deduplication_on_restart(
        self, tmp_path: Path, mock_fixture_loader
    ) -> None:
        """Verify identical raw payloads and snapshots do not duplicate rows on restart."""
        db_mgr = DatabaseManager(tmp_path / "dedup_e2e.db")
        db_mgr.initialize_schema()
        store = SnapshotStore(db_mgr)

        now = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
        raw_text = mock_fixture_loader("sample_holdings.json")

        # First ingestion
        raw_id_1, is_new_1 = store.store_raw_object("sc_holdings", raw_text, now)
        assert is_new_1 is True

        # Second ingestion with identical payload
        raw_id_2, is_new_2 = store.store_raw_object("sc_holdings", raw_text, now)
        assert is_new_2 is False
        assert raw_id_1 == raw_id_2

        # Verify raw_objects row count is exactly 1
        with db_mgr.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM raw_objects")
            assert cur.fetchone()[0] == 1

    def test_e2e_crash_recovery_during_pipeline(self, tmp_path: Path) -> None:
        """Verify uncommitted in-flight jobs are safely recovered and marked FAILED."""
        db_mgr = DatabaseManager(tmp_path / "crash_recovery_e2e.db")
        db_mgr.initialize_schema()
        audit = AuditLogger(db_mgr)
        queue = JobQueue(db_mgr, audit_logger=audit)

        # Enqueue and advance job to COLLECTING (simulating crash before completion)
        job_dict, _ = queue.enqueue("daily_ingest", "crash_dedup_001")
        job_id = job_dict["job_id"]
        queue.transition(job_id, to_status=JobState.COLLECTING)

        # System restart: execute crash recovery
        recovered = queue.recover_in_flight_jobs()
        assert recovered == 1

        recovered_job = queue.get_job(job_id)
        assert recovered_job.status == JobState.FAILED
        assert recovered_job.error_message == "SYSTEM_CRASH_OR_UNEXPECTED_SHUTDOWN"
        assert recovered_job.completed_at is not None

        # Verify audit chain integrity remains valid after crash recovery
        valid, err = audit.verify_integrity()
        assert valid is True
        assert err is None


class TestE2ETaxZeroImportForensicAST:
    """Forensic AST audit verifying zero tax imports across all core masa modules."""

    def test_ast_proves_zero_tax_imports_in_core_modules(self) -> None:
        src_dir = Path(__file__).parents[1] / "src" / "masa"
        assert src_dir.exists(), f"Source directory not found: {src_dir}"

        core_packages = ["identity", "calendar", "storage", "ingestion", "audit", "prompts"]
        violations = []

        for pkg in core_packages:
            pkg_path = src_dir / pkg
            if not pkg_path.exists():
                continue

            for py_file in pkg_path.rglob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "tax" in alias.name:
                                violations.append((str(py_file), alias.name))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and "tax" in node.module:
                            violations.append((str(py_file), node.module))

        assert not violations, f"Forbidden tax imports found in core masa packages: {violations}"


class TestE2EAdversarialStressScenarios:
    """Empirical adversarial stress-tests covering corruption, state transitions, and invalid ISINs."""

    def test_adversarial_database_corruption_detected_by_hash_chains(
        self, tmp_path: Path
    ) -> None:
        """Verify that tampering with snapshots, quotes, or audit events is strictly detected."""
        db_mgr = DatabaseManager(tmp_path / "corruption_stress.db")
        db_mgr.initialize_schema()
        store = SnapshotStore(db_mgr)
        audit = AuditLogger(db_mgr)
        now = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)

        raw_id_1, _ = store.store_raw_object("sc_quote", '{"isin": "US0378331005"}', now)
        raw_id_2, _ = store.store_raw_object("sc_quote", '{"isin": "IE00BKM4GZ66"}', now)

        q1 = [
            {
                "isin": "US0378331005",
                "currency": "EUR",
                "bid": "300.00",
                "ask": "301.00",
                "computed_mid": "300.50",
                "spread": "1.00",
                "spread_pct": "0.33",
                "quote_timestamp": "2026-10-30T10:00:00Z",
                "retrieved_at": "2026-10-30T10:01:00Z",
                "quality_status": "FRESH",
            }
        ]
        q2 = [
            {
                "isin": "IE00BKM4GZ66",
                "currency": "EUR",
                "bid": "45.00",
                "ask": "45.10",
                "computed_mid": "45.05",
                "spread": "0.10",
                "spread_pct": "0.22",
                "quote_timestamp": "2026-10-30T10:05:00Z",
                "retrieved_at": "2026-10-30T10:06:00Z",
                "quality_status": "FRESH",
            }
        ]

        store.save_quote_snapshot("snap_c1", raw_id_1, "sc", now, now, q1)
        store.save_quote_snapshot("snap_c2", raw_id_2, "sc", now, now, q2)
        audit.log_event("tester", "INGEST_QUOTE", "quote", "US0378331005", {"status": "ok"})
        audit.log_event("tester", "INGEST_QUOTE", "quote", "IE00BKM4GZ66", {"status": "ok"})

        # Initial baseline verification
        assert store.verify_integrity()[0] is True
        assert audit.verify_integrity()[0] is True

        # 1a. Tamper with the DATA (bid) but leave record_hash untouched -> must be detected
        with db_mgr.transaction() as conn:
            original_hash = conn.execute(
                "SELECT record_hash FROM quotes WHERE isin = 'US0378331005'").fetchone()[0]
            conn.execute("DROP TRIGGER IF EXISTS prevent_update_quotes")
            conn.execute("UPDATE quotes SET bid = '999.00' WHERE isin = 'US0378331005'")
        valid_d, err_d = store.verify_integrity()
        assert valid_d is False
        assert err_d is not None and "Record tampered in quotes" in err_d
        with db_mgr.transaction() as conn:
            conn.execute("UPDATE quotes SET bid = '300.00' WHERE isin = 'US0378331005'")
        assert store.verify_integrity()[0] is True

        # 1b. Corrupt quote record_hash in database
        with db_mgr.transaction() as conn:
            conn.execute("UPDATE quotes SET record_hash = 'corrupted_quote_hash' WHERE isin = 'US0378331005'")
        valid_q, err_q = store.verify_integrity()
        assert valid_q is False
        assert err_q is not None and "Record tampered in quotes" in err_q

        # Revert quote record_hash
        with db_mgr.transaction() as conn:
            conn.execute("UPDATE quotes SET record_hash = ? WHERE isin = 'US0378331005'", (original_hash,))
        assert store.verify_integrity()[0] is True

        # 2. Corrupt snapshot curr_hash
        with db_mgr.transaction() as conn:
            conn.execute("DROP TRIGGER IF EXISTS prevent_update_snapshots")
            conn.execute("UPDATE snapshots SET curr_hash = 'tampered_snap_curr_hash' WHERE snapshot_id = 'snap_c1'")
        valid_s, err_s = store.verify_integrity()
        assert valid_s is False
        assert err_s is not None and "curr_hash mismatch at snap_c1" in err_s

        # 3. Corrupt snapshot prev_hash linkage
        with db_mgr.transaction() as conn:
            conn.execute("UPDATE snapshots SET prev_hash = 'broken_prev_link_hash' WHERE snapshot_id = 'snap_c2'")
        valid_link, err_link = store.verify_integrity()
        assert valid_link is False
        assert err_link is not None

        # 4. Corrupt audit_events curr_hash
        with db_mgr.transaction() as conn:
            conn.execute("DROP TRIGGER IF EXISTS prevent_update_audit_events")
            conn.execute("UPDATE audit_events SET curr_hash = 'tampered_audit_curr' WHERE event_id = 1")
        valid_a1, err_a1 = audit.verify_integrity()
        assert valid_a1 is False
        assert err_a1 is not None and "Audit hash mismatch at event_id 1" in err_a1

        # 5. Corrupt audit_events prev_hash linkage
        with db_mgr.transaction() as conn:
            conn.execute("UPDATE audit_events SET prev_hash = 'tampered_audit_prev' WHERE event_id = 2")
        valid_a2, err_a2 = audit.verify_integrity()
        assert valid_a2 is False
        assert err_a2 is not None

    def test_adversarial_invalid_state_transitions_strictly_rejected(
        self, tmp_path: Path
    ) -> None:
        """Verify strict rejection of invalid state jumps and transitions from terminal states."""
        db_mgr = DatabaseManager(tmp_path / "state_stress.db")
        db_mgr.initialize_schema()
        queue = JobQueue(db_mgr)

        # Enqueue job -> state is QUEUED
        job_dict, _ = queue.enqueue("stress_job", "dedup_stress_001")
        job_id = job_dict["job_id"]

        # Invalid from QUEUED: cannot jump to PUBLISHED or CALCULATING
        for illegal in [JobState.PUBLISHED, JobState.CALCULATING, JobState.REVIEWING, JobState.RESEARCHING]:
            with pytest.raises(InvalidStateTransitionError, match="Invalid state transition"):
                queue.transition(job_id, to_status=illegal)

        # Advance to COLLECTING
        queue.transition(job_id, to_status=JobState.COLLECTING)

        # Invalid from COLLECTING: cannot jump directly to PUBLISHED or CALCULATING
        for illegal in [JobState.PUBLISHED, JobState.CALCULATING, JobState.REVIEWING, JobState.RESEARCHING]:
            with pytest.raises(InvalidStateTransitionError, match="Invalid state transition"):
                queue.transition(job_id, to_status=illegal)

        # Advance through valid path: COLLECTING -> VALIDATING -> CALCULATING -> REVIEWING -> PUBLISHED
        queue.transition(job_id, to_status=JobState.VALIDATING)
        queue.transition(job_id, to_status=JobState.CALCULATING)
        queue.transition(job_id, to_status=JobState.REVIEWING)
        queue.transition(job_id, to_status=JobState.PUBLISHED, result={"status": "done"})

        # Terminal state: PUBLISHED cannot transition to ANY state
        for illegal in list(JobState):
            with pytest.raises(InvalidStateTransitionError, match="Invalid state transition"):
                queue.transition(job_id, to_status=illegal)

        # Second job: verify CANCELLED is also terminal
        job_dict_2, _ = queue.enqueue("stress_cancel", "dedup_stress_002")
        job_id_2 = job_dict_2["job_id"]
        queue.transition(job_id_2, to_status=JobState.CANCELLED)
        for illegal in list(JobState):
            with pytest.raises(InvalidStateTransitionError, match="Invalid state transition"):
                queue.transition(job_id_2, to_status=illegal)

    def test_adversarial_corrupted_isins_luhn_rejection_matrix(self) -> None:
        """Verify Luhn modulus-10 algorithm deterministically rejects all corrupted ISIN variants."""
        valid_isin = "US0378331005"
        prefix11 = valid_isin[:11]
        correct_check = 5
        assert calculate_isin_check_digit(prefix11) == correct_check

        # 1. Reject all 9 incorrect check digits
        for wrong_digit in range(10):
            if wrong_digit == correct_check:
                continue
            corrupted = f"{prefix11}{wrong_digit}"
            assert is_valid_isin(corrupted) is False
            with pytest.raises(ValueError, match="check digit mismatch"):
                validate_isin(corrupted)

        # 2. Reject transposition of adjacent digits (10 -> 01)
        transposed = "US0378330105"
        assert is_valid_isin(transposed) is False
        with pytest.raises(ValueError):
            validate_isin(transposed)

        # 3. Reject invalid lengths
        for bad_len in ["", "US", "US123", "US037833100", "US03783310055", "US0378331005_TOOLONG"]:
            assert is_valid_isin(bad_len) is False
            with pytest.raises(ValueError, match="must be exactly 12 characters"):
                validate_isin(bad_len)

        # 4. Reject invalid characters (lowercase, symbols, non-ASCII)
        for bad_char in ["us0378331005", "US-378331005", "US 378331005", "US.378331005", "US!378331005", "US037833100Ö"]:
            assert is_valid_isin(bad_char) is False
            with pytest.raises(ValueError):
                validate_isin(bad_char)

        # 5. Reject non-string data types with TypeError
        for non_string in [None, 123456789012, 12.34, ["US0378331005"], {"isin": "US0378331005"}]:
            assert is_valid_isin(non_string) is False
            with pytest.raises(TypeError, match="ISIN must be a string"):
                validate_isin(non_string)

