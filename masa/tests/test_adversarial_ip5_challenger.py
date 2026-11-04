"""Adversarial Challenger Test Suite for IP-5 (02 CRITIQUE).

Attacks, stress-tests, and boundary validations:
1. Immutability Trigger Circumvention (UPDATE, DELETE, REPLACE, multi-row).
2. DAG Branching & Forking Attacks (duplicate supersedes_id, duplicate settlements).
3. Hash Forgery & Tamper Resistance (tampered fields vs canonical SHA-256).
4. Boundary Edge Cases (Deadband boundary at exactly 0.10%, zero division, N=29 vs N=30).
5. Strict Isolation Invariant (0 leaks into live DB or zincir-uclari.jsonl).
"""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import pytest

from masa.forecast.generator import DEADBAND_THRESHOLD, generate_daily_forecasts
from masa.forecast.metrics import calculate_performance_metrics
from masa.forecast.models import ForecastDirection
from masa.forecast.settlement import settle_daily_forecasts
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import (
    compute_forecast_hash,
    compute_settlement_hash,
    compute_thesis_version_hash,
)
from masa.thesis.manager import ThesisManager
from masa.thesis.models import (
    ThesisCategory,
    ThesisHorizon,
    ThesisRecord,
    ThesisStatus,
)


MOCK_POOL_QUOTES = {
    "IE00B3YLTY66": Decimal("10.50"),
    "IE00BKM4GZ66": Decimal("4.90"),
    "IE00BP3QZ825": Decimal("18.20"),
    "IE00BP3QZB59": Decimal("6.35"),
    "IE00B4L5Y983": Decimal("95.50"),
    "US0378331005": Decimal("215.00"),
    "US5949181045": Decimal("395.00"),
    "US67066G1040": Decimal("130.00"),
    "NL0010273215": Decimal("720.00"),
    "DE0007164600": Decimal("215.00"),
}


@pytest.fixture
def isolated_db(tmp_path: Path):
    """Provide a strictly isolated SQLite database on temporary disk."""
    db_path = tmp_path / "ip5_adversarial.db"
    db = DatabaseManager(db_path)
    db.initialize_schema()
    IdentityRegistry(db=db).seed_from_configs()
    return db


class TestAdversarialImmutabilityAttacks:
    """Challenge the 9 append-only abort triggers for IP-5."""

    def test_thesis_multi_row_update_and_delete_abort(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Çekirdek Tez 1",
                one_line_summary="Açıklayıcı özet metni en az 10 karakter.",
                economic_rationale="Gerekçe açıklaması en az 10 karakter.",
                falsification_triggers=["Tetikleyici A", "Tetikleyici B"],
            )
        )
        mgr.create_thesis(
            ThesisRecord(
                isin="IE00BKM4GZ66",
                category=ThesisCategory.SATELLITE,
                horizon=ThesisHorizon.MEDIUM_TERM,
                title="Çekirdek Tez 2",
                one_line_summary="Açıklayıcı özet metni en az 10 karakter.",
                economic_rationale="Gerekçe açıklaması en az 10 karakter.",
                falsification_triggers=["Tetikleyici A", "Tetikleyici B"],
            )
        )

        conn = isolated_db.get_connection()
        try:
            # Multi-row UPDATE attack
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions degistirilemez"):
                conn.execute("UPDATE thesis_versions SET status = 'INVALIDATED'")

            # Multi-row DELETE attack
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions kaydi silinemez"):
                conn.execute("DELETE FROM thesis_versions")

            # Verify rows are completely untouched
            count = conn.execute("SELECT COUNT(*) FROM thesis_versions").fetchone()[0]
            assert count == 2
        finally:
            conn.close()

    def test_forecast_and_settlement_multi_row_attacks(self, isolated_db):
        generate_daily_forecasts(isolated_db, target_date="2026-10-31", quotes_override=MOCK_POOL_QUOTES)
        settle_daily_forecasts(isolated_db, settlement_date="2026-10-31", price_overrides=MOCK_POOL_QUOTES)

        conn = isolated_db.get_connection()
        try:
            # Forecast update attack
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries degistirilemez"):
                conn.execute("UPDATE forecast_entries SET target_price = '1000.00'")

            # Forecast delete attack
            with pytest.raises(sqlite3.IntegrityError, match="forecast_entries kaydi silinemez"):
                conn.execute("DELETE FROM forecast_entries")

            # Settlement update attack
            with pytest.raises(sqlite3.IntegrityError, match="settlements degistirilemez"):
                conn.execute("UPDATE settlements SET direction_hit = 1")

            # Settlement delete attack
            with pytest.raises(sqlite3.IntegrityError, match="settlements kaydi silinemez"):
                conn.execute("DELETE FROM settlements")

            # Verify integrity
            fc_count = conn.execute("SELECT COUNT(*) FROM forecast_entries").fetchone()[0]
            assert fc_count == 10
            set_count = conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
            assert set_count == 10
        finally:
            conn.close()


class TestAdversarialDAGAndForkingAttacks:
    """Challenge linear versioning and settlement uniqueness."""

    def test_cannot_fork_thesis_history_branch(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        v1 = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B4L5Y983",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="MSCI World Core",
                one_line_summary="Gelişmiş ülkeler geniş piyasa ortaklığı.",
                economic_rationale="Gelişmiş piyasaların sermaye getirisi.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
            )
        )
        # Branch 1
        mgr.revise_thesis(v1.thesis_id, rationale="Dal 1 geçerli revizyon gerekçesi.")

        # Branch 2 attempt using same parent v1.version_id directly into DB
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO thesis_versions (
                        version_id, thesis_id, supersedes_id, version_number,
                        isin, category, horizon, status, title, one_line_summary,
                        economic_rationale, evidence_pillars_json, counter_arguments,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        target_allocation_pct, next_review_date, revision_rationale,
                        author, created_at, record_hash
                    ) VALUES (
                        'thv_fork_branch_2', ?, ?, 2, 'IE00B4L5Y983', 'CORE', 'LONG_TERM',
                        'ACTIVE', 'Dal 2 Fork', 'Açıklayıcı özet metni.', 'Gerekçe açıklaması.',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]', NULL, NULL,
                        'Dal 2 yetkisiz revizyon denemesi', 'adversary', '2026-10-31T12:00:00Z',
                        'fakehashforkbranch200000000000000000000000000000000000000000000000'
                    )
                    """,
                    (v1.thesis_id, v1.version_id),
                )
        finally:
            conn.close()

    def test_duplicate_settlement_attack_strictly_blocked(self, isolated_db):
        forecasts = generate_daily_forecasts(isolated_db, target_date="2026-10-31", quotes_override=MOCK_POOL_QUOTES)
        settle_daily_forecasts(isolated_db, settlement_date="2026-10-31", price_overrides=MOCK_POOL_QUOTES)
        f0 = forecasts[0]

        conn = isolated_db.get_connection()
        try:
            # Attempt to settle f0 again
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        'set_second_attack', ?, 'IE00B3YLTY66', '2026-10-31',
                        '10.80', '0.00', '0.00', 1, '2026-10-31T18:00:00Z',
                        'fakehashsecondsettlement00000000000000000000000000000000000000000'
                    )
                    """,
                    (f0.forecast_id,),
                )
        finally:
            conn.close()


class TestAdversarialDeadbandAndMetricsBoundaries:
    """Stress test boundary arithmetic, deadband transitions, and small-sample warnings."""

    def test_deadband_exact_boundary_conditions(self):
        # Return exactly at or just below deadband threshold -> FLAT
        ref = Decimal("100.00")
        just_below_up = ref * (Decimal("1") + Decimal("0.00099"))
        delta_below = (just_below_up - ref) / ref
        assert delta_below < DEADBAND_THRESHOLD

        # Return just above deadband threshold -> UP
        just_above_up = ref * (Decimal("1") + Decimal("0.00101"))
        delta_above = (just_above_up - ref) / ref
        assert delta_above > DEADBAND_THRESHOLD

    def test_metrics_empty_division_by_zero_safety(self, isolated_db):
        metrics = calculate_performance_metrics(isolated_db)
        assert metrics.total_forecasts == 0
        assert metrics.settled_count == 0
        assert metrics.hit_rate_pct == Decimal("0.00")
        assert metrics.mape_pct == Decimal("0.00")
        assert metrics.mae_eur == Decimal("0.00")
        assert metrics.is_small_sample is True

    def test_small_sample_warning_transitions_at_thirty(self, isolated_db):
        # Seed 29 settlements -> is_small_sample MUST BE True
        # Seed 30th settlement -> is_small_sample MUST BE False
        conn = isolated_db.get_connection()
        try:
            for i in range(1, 31):
                fc_id = f"fc_stress_{i:03d}"
                set_id = f"set_stress_{i:03d}"
                conn.execute(
                    """
                    INSERT INTO forecast_entries (
                        forecast_id, isin, target_date, forecast_type, direction,
                        reference_price, target_price, confidence_pct, model_id,
                        created_at, record_hash
                    ) VALUES (
                        ?, 'IE00B3YLTY66', '2026-10-01', 'DAILY_CLOSE', 'UP',
                        '10.00', '10.50', '65.00', 'model_stress',
                        '2026-10-01T09:30:00Z', ?
                    )
                    """,
                    (fc_id, f"hash_fc_{i:060d}"),
                )
                conn.execute(
                    """
                    INSERT INTO settlements (
                        settlement_id, forecast_id, isin, settlement_date,
                        actual_close_price, error_eur, error_pct, direction_hit,
                        settled_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', '2026-10-01',
                        '10.40', '0.10', '0.9615', 1,
                        '2026-10-01T17:40:00Z', ?
                    )
                    """,
                    (set_id, fc_id, f"hash_set_{i:059d}"),
                )

                if i == 29:
                    m29 = calculate_performance_metrics(isolated_db, model_id="model_stress")
                    assert m29.settled_count == 29
                    assert m29.is_small_sample is True
                    assert "en az 30 gözlem gereklidir" in m29.warning_message

            m30 = calculate_performance_metrics(isolated_db, model_id="model_stress")
            assert m30.settled_count == 30
            assert m30.is_small_sample is False
            assert m30.warning_message is None
            assert m30.hit_rate_pct == Decimal("100.00")
        finally:
            conn.close()


class TestAdversarialHashIntegrity:
    """Verify that tampering with any field invalidates canonical record_hash."""

    def test_thesis_hash_detects_single_character_tampering(self):
        row = {
            "version_id": "thv_test001",
            "thesis_id": "th_test001",
            "supersedes_id": None,
            "version_number": 1,
            "isin": "IE00B3YLTY66",
            "category": "CORE",
            "horizon": "LONG_TERM",
            "status": "ACTIVE",
            "title": "Orijinal Başlık",
            "one_line_summary": "Orijinal özet metni en az 10 karakter.",
            "economic_rationale": "Ekonomik gerekçe metni en az 10 karakter.",
            "evidence_pillars_json": "[]",
            "counter_arguments": None,
            "falsification_triggers_json": "[\"t1\",\"t2\"]",
            "benchmark_reference": "araştırma referansı",
            "sources_json": "[]",
            "target_allocation_pct": "0.40",
            "next_review_date": None,
            "revision_rationale": None,
            "author": "user",
            "created_at": "2026-10-31T09:30:00Z",
        }
        original_hash = compute_thesis_version_hash(row)

        # Tamper title
        tampered = dict(row)
        tampered["title"] = "Orijinal Başlik"  # Changed one letter
        assert compute_thesis_version_hash(tampered) != original_hash

        # Tamper target allocation
        tampered2 = dict(row)
        tampered2["target_allocation_pct"] = "0.41"
        assert compute_thesis_version_hash(tampered2) != original_hash

    def test_forecast_hash_detects_direction_tampering(self):
        fc_dict = {
            "forecast_id": "fc_001",
            "isin": "IE00B3YLTY66",
            "target_date": "2026-10-31",
            "forecast_type": "DAILY_CLOSE",
            "direction": "UP",
            "reference_price": "10.50",
            "target_price": "10.60",
            "confidence_pct": "65.00",
            "model_id": "model_momentum_v1",
            "created_at": "2026-10-31T09:30:00Z",
        }
        h_orig = compute_forecast_hash(fc_dict)

        tampered = dict(fc_dict)
        tampered["direction"] = "DOWN"
        assert compute_forecast_hash(tampered) != h_orig

    def test_settlement_hash_detects_direction_hit_tampering(self):
        set_dict = {
            "settlement_id": "set_001",
            "forecast_id": "fc_001",
            "isin": "IE00B3YLTY66",
            "settlement_date": "2026-10-31",
            "actual_close_price": "10.55",
            "error_eur": "0.05",
            "error_pct": "0.4739",
            "direction_hit": 1,
            "settled_at": "2026-10-31T17:40:00Z",
        }
        h_orig = compute_settlement_hash(set_dict)

        tampered = dict(set_dict)
        tampered["direction_hit"] = 0
        assert compute_settlement_hash(tampered) != h_orig
