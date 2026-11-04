"""Adversarial stress-testing suite for Investment Thesis Module (IP-5 Step 02 CRITIQUE).

Covers:
1. Linear DAG / Forking attacks & DAG hijacking.
2. Immutability & trigger bypasses (UPDATE, DELETE, REPLACE, UPSERT, IGNORE).
3. Rationale bypasses & whitespace injection.
4. Falsification trigger validation & duplicate triggers.
5. Unregistered / invalid ISIN rejection (Luhn check digit, inactive instruments).
6. Latest view (v_theses_current) querying accuracy & review date auditing.
"""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import pytest

from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.thesis.manager import ThesisManager
from masa.thesis.models import (
    ThesisCategory,
    ThesisHorizon,
    ThesisRecord,
    ThesisStatus,
)


@pytest.fixture
def isolated_db(tmp_path: Path):
    """Provide a strictly isolated SQLite database initialized with Schema v3."""
    db_path = tmp_path / "ip5_critique.db"
    db = DatabaseManager(db_path)
    db.initialize_schema()
    IdentityRegistry(db=db).seed_from_configs()
    return db


# ============================================================================
# 1. Linear DAG / Forking Attacks & DAG Hijacking
# ============================================================================
class TestAdversarialDAGAndForking:
    """Stress-test DAG linearity, partial unique indexes, and branching vectors."""

    def test_branching_from_superseded_version_blocked(self, isolated_db):
        """Revision branching from an already superseded version must be blocked by idx_tv_unique_supersedes."""
        mgr = ThesisManager(isolated_db)
        v1 = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Linear DAG Parent",
                one_line_summary="Açıklayıcı özet metni en az 10 karakter.",
                economic_rationale="Gerekçe açıklaması en az 10 karakter.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
            )
        )
        # Legitimate child v2
        mgr.revise_thesis(v1.thesis_id, rationale="Geçerli revizyon gerekçesi 12345")

        # Rogue attempt to attach a second child to v1
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
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
                        'thv_rogue_branch', ?, ?, 2, 'IE00B3YLTY66', 'CORE', 'LONG_TERM',
                        'ACTIVE', 'Rogue Fork', 'Açıklayıcı özet metni.', 'Gerekçe açıklaması.',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]', NULL, NULL,
                        'Rogue fork rationale 12345', 'adversary', '2026-10-31T12:00:00Z',
                        'fakehashrogue000000000000000000000000000000000000000000000000000'
                    )
                    """,
                    (v1.thesis_id, v1.version_id),
                )
        finally:
            conn.close()

    def test_cross_thesis_supersedes_hijacking_prevented(self, isolated_db):
        """Hardened: create_thesis rejects version > 1 / supersedes_id, and v_theses_current prevents cross-thesis hijacking."""
        mgr = ThesisManager(isolated_db)
        th_a = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Thesis A Core",
                one_line_summary="SPDR MSCI ACWI IMI summary text.",
                economic_rationale="Gerekçe açıklaması en az 10 karakter.",
                falsification_triggers=["T1", "T2"],
            )
        )
        assert mgr.get_thesis(th_a.thesis_id) is not None

        # Attacker crafts thesis B with supersedes_id pointing to th_a.version_id
        rogue_b = ThesisRecord(
            isin="IE00BP3QZ825",
            category=ThesisCategory.FACTOR,
            horizon=ThesisHorizon.MEDIUM_TERM,
            title="Thesis B Hijack",
            one_line_summary="World Momentum summary text.",
            economic_rationale="Gerekçe açıklaması en az 10 karakter.",
            falsification_triggers=["T1", "T2"],
            version_number=2,
            supersedes_id=th_a.version_id,
            revision_rationale="Cross-thesis hijack rationale 12345",
        )
        # create_thesis strictly rejects this
        with pytest.raises(ValueError, match="create_thesis yalnızca ilk sürüm"):
            mgr.create_thesis(rogue_b)

        # Even with raw SQL insertion claiming th_a.version_id as supersedes_id,
        # v_theses_current checks child.thesis_id = tv.thesis_id, so th_a remains visible
        conn = isolated_db.get_connection()
        try:
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
                    'thv_rogue_b', 'th_rogue_b', ?, 2, 'IE00BP3QZ825', 'FACTOR', 'MEDIUM_TERM',
                    'ACTIVE', 'Rogue B', 'World Momentum summary text.', 'Gerekçe açıklaması 10.',
                    '[]', NULL, '["T1","T2"]', 'ref', '[]', NULL, NULL,
                    'Cross-thesis hijack rationale 12345', 'adversary', '2026-10-31T12:00:00Z',
                    'fakehashrogueb00000000000000000000000000000000000000000000000000'
                )
                """,
                (th_a.version_id,),
            )
        finally:
            conn.close()

        # Thesis A is still safely in v_theses_current!
        head_a = mgr.get_thesis(th_a.thesis_id)
        assert head_a is not None, "th_a was protected from cross-thesis hijacking!"
        assert head_a.version_id == th_a.version_id

    def test_multiple_roots_duplicate_thesis_id_blocked(self, isolated_db):
        """Hardened: idx_tv_unique_root ensures only ONE root per thesis_id."""
        conn = isolated_db.get_connection()
        try:
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
                    'thv_root_1', 'th_dup_roots', NULL, 1,
                    'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                    'Root 1', 'Summary 1234567890', 'Rationale 1234567890',
                    '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]',
                    NULL, NULL, NULL, 'user', '2026-10-31T10:00:00Z', 'hash_root_1_00000000000000000000000000000000000000000000000000000'
                )
                """
            )
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: thesis_versions.thesis_id"):
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
                        'thv_root_2', 'th_dup_roots', NULL, 1,
                        'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'Root 2', 'Summary 1234567890', 'Rationale 1234567890',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]',
                        NULL, NULL, NULL, 'user', '2026-10-31T10:01:00Z', 'hash_root_2_00000000000000000000000000000000000000000000000000000'
                    )
                    """
                )
        finally:
            conn.close()

    def test_duplicate_version_number_blocked(self, isolated_db):
        """Hardened: idx_tv_thesis_version prevents duplicate version numbers for the same thesis."""
        conn = isolated_db.get_connection()
        try:
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
                    'thv_vn1', 'th_vnum_test', NULL, 1,
                    'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                    'V1', 'Summary 1234567890', 'Rationale 1234567890',
                    '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]',
                    NULL, NULL, NULL, 'user', '2026-10-31T10:00:00Z', 'hash_vn1_000000000000000000000000000000000000000000000000000000'
                )
                """
            )
            # Insert child with duplicate version_number = 1 instead of 2 must fail
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
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
                        'thv_vn2', 'th_vnum_test', 'thv_vn1', 1,
                        'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'V2 Illegal', 'Summary 1234567890', 'Rationale 1234567890',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]',
                        NULL, NULL, 'Revision rationale 12345', 'user', '2026-10-31T10:01:00Z', 'hash_vn2_000000000000000000000000000000000000000000000000000000'
                    )
                    """
                )
        finally:
            conn.close()

    def test_self_referencing_supersedes_black_hole_blocked(self, isolated_db):
        """Hardened: CHECK constraint and model validation block supersedes_id = version_id."""
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
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
                        'thv_blackhole', 'th_blackhole', 'thv_blackhole', 1,
                        'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'Blackhole Thesis', 'Summary 1234567890', 'Rationale 1234567890',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]',
                        NULL, NULL, 'Revision rationale 12345', 'user', '2026-10-31T10:00:00Z', 'hash_blackhole_000000000000000000000000000000000000000000000000'
                    )
                    """
                )
        finally:
            conn.close()

        # Model-level check
        with pytest.raises(ValueError, match="supersedes_id != version_id"):
            ThesisRecord(
                version_id="thv_same",
                thesis_id="th_same",
                supersedes_id="thv_same",
                version_number=2,
                revision_rationale="Self referencing attempt 12345",
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Self Ref",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )


# ============================================================================
# 2. Immutability & Trigger Attacks
# ============================================================================
class TestAdversarialImmutabilityAndTriggers:
    """Challenge the append-only SQLite triggers on thesis_versions."""

    def test_direct_update_blocked_by_trigger(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Immutability Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions degistirilemez"):
                conn.execute("UPDATE thesis_versions SET title = 'Hacked' WHERE version_id = ?", (rec.version_id,))
        finally:
            conn.close()

    def test_direct_delete_blocked_by_trigger(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Delete Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions kaydi silinemez"):
                conn.execute("DELETE FROM thesis_versions WHERE version_id = ?", (rec.version_id,))
        finally:
            conn.close()

    def test_insert_or_replace_blocked_by_trigger(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Replace Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO thesis_versions (
                        version_id, thesis_id, isin, category, horizon, status,
                        title, one_line_summary, economic_rationale, evidence_pillars_json,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'Overwritten', 'Summary text 1234567890', 'Rationale text 1234567890',
                        '[]', '[\"t1\",\"t2\"]', 'ref', '[]', '2026-10-31T10:00:00Z', ?
                    )
                    """,
                    (rec.version_id, rec.thesis_id, rec.record_hash),
                )
        finally:
            conn.close()

    def test_upsert_blocked_by_trigger(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Upsert Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT INTO thesis_versions (
                        version_id, thesis_id, isin, category, horizon, status,
                        title, one_line_summary, economic_rationale, evidence_pillars_json,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'Upsert Title', 'Summary text 1234567890', 'Rationale text 1234567890',
                        '[]', '[\"t1\",\"t2\"]', 'ref', '[]', '2026-10-31T10:00:00Z', ?
                    )
                    ON CONFLICT(version_id) DO UPDATE SET title = 'Hacked'
                    """,
                    (rec.version_id, rec.thesis_id, rec.record_hash),
                )
        finally:
            conn.close()

    def test_insert_or_ignore_blocked_by_trigger(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Ignore Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        conn = isolated_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO thesis_versions (
                        version_id, thesis_id, isin, category, horizon, status,
                        title, one_line_summary, economic_rationale, evidence_pillars_json,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, 'IE00B3YLTY66', 'CORE', 'LONG_TERM', 'ACTIVE',
                        'Ignored Title', 'Summary text 1234567890', 'Rationale text 1234567890',
                        '[]', '[\"t1\",\"t2\"]', 'ref', '[]', '2026-10-31T10:00:00Z', 'fakehashdiff'
                    )
                    """,
                    (rec.version_id, rec.thesis_id),
                )
        finally:
            conn.close()


# ============================================================================
# 3. Rationale & Validation Bypasses
# ============================================================================
class TestAdversarialRationaleValidation:
    """Stress-test rationale lengths, whitespace stripping, and blank text bypasses."""

    @pytest.mark.parametrize(
        "bad_rationale",
        [
            "",
            "          ",
            "\t\n  \r\n",
            "kısa",
            "123456789",
            "  123456789  ",
        ],
    )
    def test_invalid_rationales_rejected(self, isolated_db, bad_rationale):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Rationale Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        # 1. revise_thesis rejection
        with pytest.raises(ValueError, match="gerekçe"):
            mgr.revise_thesis(rec.thesis_id, rationale=bad_rationale)

        # 2. invalidate_thesis rejection
        with pytest.raises(ValueError, match="gerekçe"):
            mgr.invalidate_thesis(rec.thesis_id, rationale=bad_rationale)

    def test_whitespace_title_summary_rationale_bypass_blocked(self, isolated_db):
        """Hardened: title, one_line_summary, and economic_rationale reject whitespace-only strings."""
        with pytest.raises(ValueError):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="   ",             # 3 spaces (must fail min_length after strip)
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )

        with pytest.raises(ValueError):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Valid Title",
                one_line_summary="          ",   # 10 spaces
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )

        with pytest.raises(ValueError):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Valid Title",
                one_line_summary="Summary text 1234567890",
                economic_rationale="          ", # 10 spaces
                falsification_triggers=["T1", "T2"],
            )


# ============================================================================
# 4. Falsification Trigger Validation
# ============================================================================
class TestAdversarialFalsificationTriggers:
    """Stress-test falsification trigger bounds and duplicate triggers."""

    def test_zero_triggers_rejected(self):
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="No Triggers",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=[],
            )

    def test_single_trigger_rejected(self):
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Single Trigger",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["Tek tetikleyici"],
            )

    def test_whitespace_only_triggers_rejected(self):
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Whitespace Triggers",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["   ", "   "],
            )

    def test_under_two_triggers_on_revision_rejected(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Triggers Rev Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            mgr.revise_thesis(
                rec.thesis_id,
                rationale="Valid revision rationale 12345",
                updates={"falsification_triggers": ["Sadece bir tetikleyici"]},
            )

    def test_duplicate_triggers_bypass_blocked(self):
        """Hardened: check_triggers requires at least 2 distinct falsification triggers."""
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Duplicate Trigger Thesis",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["Duplicate trigger", "Duplicate trigger"],
            )


# ============================================================================
# 5. Unregistered / Invalid ISIN Rejection
# ============================================================================
class TestAdversarialISINValidation:
    """Stress-test ISIN validation, Luhn check digits, and database foreign keys."""

    @pytest.mark.parametrize(
        "bad_isin",
        [
            "US123",            # too short
            "TOOLONG_ISIN_XYZ",  # too long
            "120378331005",     # non-alpha country code
            "US037833100$",     # illegal symbol
            "US0378331006",     # Apple with wrong check digit (expected 5)
            "IE00B3YLTY67",     # SPDR ACWI with wrong check digit (expected 6)
        ],
    )
    def test_invalid_isin_rejected(self, bad_isin):
        with pytest.raises(ValueError):
            ThesisRecord(
                isin=bad_isin,
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Bad ISIN",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )

    def test_unregistered_isin_rejected(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = ThesisRecord(
            isin="DE000BAY0017",  # Bayer AG: valid Luhn, not in instruments
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.LONG_TERM,
            title="Unregistered Stock",
            one_line_summary="Summary text 1234567890",
            economic_rationale="Rationale text 1234567890",
            falsification_triggers=["T1", "T2"],
        )
        with pytest.raises(ValueError, match="instruments tablosunda bulunamadı"):
            mgr.create_thesis(rec)

    def test_inactive_isin_rejected(self, isolated_db):
        conn = isolated_db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO instruments (instrument_id, isin, name, instrument_type, issuer_id, base_currency, is_active, created_at, record_hash)
                VALUES ('inst_inactive', 'DE000BASF111', 'BASF Inactive', 'STOCK', 'iss_basf', 'EUR', 0, '2026-10-31T10:00:00Z', 'hash_inactive')
                """
            )
        finally:
            conn.close()

        mgr = ThesisManager(isolated_db)
        rec = ThesisRecord(
            isin="DE000BASF111",
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.LONG_TERM,
            title="Inactive Instrument",
            one_line_summary="Summary text 1234567890",
            economic_rationale="Rationale text 1234567890",
            falsification_triggers=["T1", "T2"],
        )
        with pytest.raises(ValueError, match="pasif durumda"):
            mgr.create_thesis(rec)

    def test_duplicate_active_thesis_on_same_isin_rejected(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec1 = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Active Thesis 1",
            one_line_summary="Summary text 1234567890",
            economic_rationale="Rationale text 1234567890",
            falsification_triggers=["T1", "T2"],
        )
        mgr.create_thesis(rec1)

        rec2 = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Duplicate Active Thesis 2",
            one_line_summary="Summary text 1234567890",
            economic_rationale="Rationale text 1234567890",
            falsification_triggers=["T1", "T2"],
        )
        with pytest.raises(ValueError, match="zaten aktif bir tez mevcut"):
            mgr.create_thesis(rec2)


# ============================================================================
# 6. Latest View (v_theses_current) & Review Date Auditing
# ============================================================================
class TestAdversarialViewAndLifecycle:
    """Stress-test v_theses_current view accuracy and health auditing."""

    def test_view_reflects_only_active_head(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        v1 = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Head View Test v1",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        v2 = mgr.revise_thesis(
            v1.thesis_id,
            rationale="Revision rationale for v2 12345",
            updates={"title": "Head View Test v2"},
        )
        v3 = mgr.revise_thesis(
            v1.thesis_id,
            rationale="Revision rationale for v3 12345",
            updates={"title": "Head View Test v3"},
        )

        # Current view must contain ONLY v3
        conn = isolated_db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM v_theses_current WHERE thesis_id = ?", (v1.thesis_id,)).fetchall()
            assert len(rows) == 1
            assert rows[0]["version_id"] == v3.version_id
            assert rows[0]["version_number"] == 3
            assert rows[0]["title"] == "Head View Test v3"

            # Older versions must NOT be in v_theses_current
            all_current_vids = {r["version_id"] for r in conn.execute("SELECT version_id FROM v_theses_current").fetchall()}
            assert v1.version_id not in all_current_vids
            assert v2.version_id not in all_current_vids
            assert v3.version_id in all_current_vids
        finally:
            conn.close()

    def test_double_invalidation_rejected(self, isolated_db):
        mgr = ThesisManager(isolated_db)
        rec = mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Invalidation Test",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
            )
        )
        inv = mgr.invalidate_thesis(rec.thesis_id, rationale="First invalidation rationale 12345")
        assert inv.status == ThesisStatus.INVALIDATED

        with pytest.raises(ValueError, match="Tez zaten geçersiz kılınmış"):
            mgr.invalidate_thesis(rec.thesis_id, rationale="Second invalidation rationale 12345")

    def test_malformed_review_date_audit_bypass_blocked(self, isolated_db):
        """Hardened: next_review_date strictly enforces YYYY-MM-DD date format."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Malformed Date Thesis",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
                next_review_date="not-a-valid-date-string",
            )

    def test_target_allocation_unbounded_blocked(self):
        """Hardened: target_allocation_pct must be between 0.00 and 1.00."""
        with pytest.raises(ValueError):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Negative Allocation",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
                target_allocation_pct=Decimal("-0.50"),
            )

        with pytest.raises(ValueError):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Huge Allocation",
                one_line_summary="Summary text 1234567890",
                economic_rationale="Rationale text 1234567890",
                falsification_triggers=["T1", "T2"],
                target_allocation_pct=Decimal("999999.99"),
            )

