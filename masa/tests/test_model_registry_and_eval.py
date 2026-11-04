"""Unit and adversarial test suite for İP-7: Model Registry, Evaluations, and Run Manifests."""

from decimal import Decimal
import json
import sqlite3
import pytest

from masa.model_registry.evaluator import ModelEvaluator
from masa.model_registry.manager import (
    IneligibleModelError,
    MissingManifestError,
    ModelRegistryManager,
)
from masa.model_registry.models import (
    ModelAccessTier,
    ModelEvaluationRecord,
    ModelManifest,
    ModelPrivacyClass,
    ModelRecord,
    ModelRunRecord,
    ModelRunStatus,
    ModelStatus,
    TaskCategory,
)
from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import compute_model_registry_hash


@pytest.fixture
def test_db(tmp_path):
    """Isolated SQLite database manager initialized with full schema and triggers."""
    db_file = tmp_path / "test_model_desk.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()
    return mgr


# ============================================================================
# Acceptance Test 1: Manifestsiz çalışma reddedilir
# ============================================================================

def test_manifestless_execution_rejected(test_db):
    """A model run attempt without an authoritative ModelManifest is strictly rejected."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    with pytest.raises(MissingManifestError, match="Manifestsiz çalışma reddedilir"):
        mgr.record_run(manifest=None)


# ============================================================================
# Acceptance Test 2: paused model seçilmez
# ============================================================================

def test_paused_and_revoked_models_ineligible(test_db):
    """Paused or revoked models cannot be selected for execution runs."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    # Register a paused model
    paused_model = ModelRecord(
        model_id="mod_test_paused",
        provider="test",
        model_name="paused-v1",
        access_tier=ModelAccessTier.LOCAL,
        status=ModelStatus.PAUSED,
    )
    mgr.register_model(paused_model)

    # Attempt to run with paused model
    manifest = ModelManifest(
        task_name="test_task",
        quick_provider="test",
        quick_model="paused-v1",
        deep_provider="google",
        deep_model="gemini-1.5-pro",
        prompt_summary="test prompt",
        tools=[],
        rationale="testing paused model rejection",
    )

    with pytest.raises(IneligibleModelError, match="durumu 'paused' olduğundan seçilemez"):
        mgr.record_run(manifest=manifest)

    # Register a revoked model
    revoked_model = ModelRecord(
        model_id="mod_test_revoked",
        provider="test",
        model_name="revoked-v1",
        access_tier=ModelAccessTier.LOCAL,
        status=ModelStatus.REVOKED,
    )
    mgr.register_model(revoked_model)

    manifest_revoked = ModelManifest(
        task_name="test_task_2",
        quick_provider="google",
        quick_model="gemini-1.5-pro",
        deep_provider="test",
        deep_model="revoked-v1",
        prompt_summary="test prompt 2",
        tools=[],
        rationale="testing revoked model rejection",
    )

    with pytest.raises(IneligibleModelError, match="durumu 'revoked' olduğundan seçilemez"):
        mgr.record_run(manifest=manifest_revoked)


# ============================================================================
# Acceptance Test 3: Kota hatası waiting_quota durumuna geçirir
# ============================================================================

def test_quota_error_transitions_to_waiting_quota(test_db):
    """When quota exhaustion occurs, the run transitions to waiting_quota and links a fallback sub-run."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    initial_manifest = ModelManifest(
        task_name="portfolio_deep_dive",
        quick_provider="google",
        quick_model="gemini-3.8-flash",
        deep_provider="chatgpt",
        deep_model="gpt-6.1-sol",
        prompt_summary="initial analysis prompt",
        tools=["market", "news"],
        rationale="primary route",
    )

    initial_run = mgr.record_run(manifest=initial_manifest, status=ModelRunStatus.RUNNING)
    assert initial_run.status == ModelRunStatus.RUNNING

    fallback_manifest = ModelManifest(
        task_name="portfolio_deep_dive_fallback",
        quick_provider="chatgpt",
        quick_model="gpt-6.1-sol",
        deep_provider="chatgpt",
        deep_model="gpt-6.1-sol",
        prompt_summary="fallback prompt",
        tools=["market", "news"],
        rationale="fallback route after google 429",
    )

    held_run, fallback_run = mgr.record_quota_hold(
        parent_run=initial_run,
        fallback_manifest=fallback_manifest,
        quota_detail="HTTP 429: Resource Exhausted (reset in 2h)",
    )

    assert held_run.status == ModelRunStatus.WAITING_QUOTA
    assert held_run.parent_run_id == initial_run.run_id
    assert fallback_run.status == ModelRunStatus.COMPLETED
    assert fallback_run.parent_run_id == held_run.run_id

    # Verify rows in DB
    conn = test_db.get_connection()
    try:
        r1 = conn.execute("SELECT status FROM model_runs WHERE run_id = ?", (held_run.run_id,)).fetchone()
        assert r1["status"] == "waiting_quota"
        r2 = conn.execute("SELECT status, parent_run_id FROM model_runs WHERE run_id = ?", (fallback_run.run_id,)).fetchone()
        assert r2["status"] == "completed"
        assert r2["parent_run_id"] == held_run.run_id
    finally:
        conn.close()


# ============================================================================
# Acceptance Test 4: Değerlendirme skorları sürümlü saklanır & terfi kuralı
# ============================================================================

def test_eval_scores_versioned_and_stored(test_db):
    """Evaluation scorecards are versioned and stored with canonical SHA-256 hashes."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    eval_rec = ModelEvaluationRecord(
        model_id="mod_google_gemini_pro",
        eval_dataset_version="v1.0",
        task_category=TaskCategory.TABLE_EXTRACTION,
        score_pct=Decimal("94.50"),
        critical_error_passed=False,
        is_champion=True,
        eval_metrics={"precision": "0.95", "recall": "0.94"},
    )

    sealed = mgr.record_evaluation(eval_rec)
    assert sealed.record_hash is not None
    assert sealed.score_pct == Decimal("94.50")
    assert sealed.eval_dataset_version == "v1.0"

    # Query back
    conn = test_db.get_connection()
    try:
        row = conn.execute("SELECT * FROM model_evaluations WHERE evaluation_id = ?", (sealed.evaluation_id,)).fetchone()
        assert row["eval_dataset_version"] == "v1.0"
        assert row["score_pct"] == "94.50"
        assert row["is_champion"] == 1
    finally:
        conn.close()


def test_critical_error_prevents_champion_promotion(test_db):
    """A model that accepts a critical flawed report sample is barred from becoming champion."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    # Attempt to mark model as champion even though critical_error_passed is True
    eval_fail = ModelEvaluationRecord(
        model_id="mod_google_gemini_flash",
        eval_dataset_version="v1.0",
        task_category=TaskCategory.FLAWED_REPORT_DETECTION,
        score_pct=Decimal("85.00"),
        critical_error_passed=True,  # Critical error slipped through!
        is_champion=True,            # Caller attempted champion
    )

    sealed = mgr.record_evaluation(eval_fail)
    assert sealed.is_champion is False  # Invariant: forced to False!

    conn = test_db.get_connection()
    try:
        row = conn.execute("SELECT is_champion FROM model_evaluations WHERE evaluation_id = ?", (sealed.evaluation_id,)).fetchone()
        assert row["is_champion"] == 0
    finally:
        conn.close()


# ============================================================================
# Acceptance Test 5: İmmutability Triggers on Model Tables (9 Triggers)
# ============================================================================

def test_immutability_triggers_on_model_tables(test_db):
    """UPDATE, DELETE, and duplicate INSERT are strictly aborted by SQLite triggers."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    model = mgr.get_model("mod_local_deterministic")
    assert model is not None

    conn = test_db.get_connection()
    try:
        # 1. UPDATE on model_registry must fail
        with pytest.raises(sqlite3.IntegrityError, match="model_registry degistirilemez"):
            conn.execute("UPDATE model_registry SET status = 'paused' WHERE model_id = ?", (model.model_id,))

        # 2. DELETE on model_registry must fail
        with pytest.raises(sqlite3.IntegrityError, match="model_registry kaydi silinemez"):
            conn.execute("DELETE FROM model_registry WHERE model_id = ?", (model.model_id,))

        # 3. Duplicate INSERT (REPLACE) on model_registry must fail
        with pytest.raises(sqlite3.IntegrityError, match="model_registry: mevcut kaydin uzerine yazma"):
            conn.execute(
                """
                INSERT OR REPLACE INTO model_registry (
                    model_id, provider, model_name, access_tier, region_compliance,
                    quota_info, privacy_class, status, created_at, record_hash
                ) VALUES (
                    ?, 'local', 'det', 'local', 'EU_LOCAL', 'unl', 'confidential_anonymized', 'eligible', '2026-10-31', ?
                )
                """,
                (model.model_id, model.record_hash),
            )

        # 4. Triggers on model_runs
        manifest = ModelManifest(
            task_name="immutability_run",
            quick_provider="google",
            quick_model="gemini-1.5-pro",
            deep_provider="chatgpt",
            deep_model="gpt-6.1-sol",
            prompt_summary="test",
            tools=[],
            rationale="test",
        )
        run_rec = mgr.record_run(manifest)

        with pytest.raises(sqlite3.IntegrityError, match="model_runs degistirilemez"):
            conn.execute("UPDATE model_runs SET status = 'failed' WHERE run_id = ?", (run_rec.run_id,))

        with pytest.raises(sqlite3.IntegrityError, match="model_runs kaydi silinemez"):
            conn.execute("DELETE FROM model_runs WHERE run_id = ?", (run_rec.run_id,))

        # 5. Triggers on model_evaluations
        eval_rec = mgr.record_evaluation(
            ModelEvaluationRecord(
                model_id=model.model_id,
                eval_dataset_version="v1.0",
                task_category=TaskCategory.TURKISH_SEMANTICS,
                score_pct=Decimal("100.00"),
                critical_error_passed=False,
                is_champion=True,
            )
        )

        with pytest.raises(sqlite3.IntegrityError, match="model_evaluations degistirilemez"):
            conn.execute("UPDATE model_evaluations SET score_pct = '50.00' WHERE evaluation_id = ?", (eval_rec.evaluation_id,))

        with pytest.raises(sqlite3.IntegrityError, match="model_evaluations kaydi silinemez"):
            conn.execute("DELETE FROM model_evaluations WHERE evaluation_id = ?", (eval_rec.evaluation_id,))
    finally:
        conn.close()


# ============================================================================
# Acceptance Test 6: ModelEvaluator End-to-End Suite
# ============================================================================

def test_model_evaluator_end_to_end(test_db):
    """ModelEvaluator executes all 4 task categories and updates champions view."""
    mgr = ModelRegistryManager(test_db)
    mgr.seed_default_models()

    evaluator = ModelEvaluator(db=test_db)
    results = evaluator.evaluate_model("mod_local_deterministic")

    assert len(results) == 4
    for r in results:
        assert r.eval_dataset_version == "v1.0"
        assert r.score_pct >= Decimal("0.00")
        assert r.record_hash is not None

    champions = mgr.get_champions()
    assert len(champions) >= 1
    assert any(c["model_id"] == "mod_local_deterministic" for c in champions)
