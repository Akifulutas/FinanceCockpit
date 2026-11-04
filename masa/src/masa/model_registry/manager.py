"""Model Registry and Benchmark Evaluation Manager."""

from __future__ import annotations

from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from masa.audit.events import AuditLogger
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
from masa.storage.hash_chain import (
    compute_model_evaluation_hash,
    compute_model_registry_hash,
    compute_model_run_hash,
    sha256_text,
)

logger = logging.getLogger(__name__)


class MissingManifestError(RuntimeError):
    """Raised when a model invocation attempt is made without an authoritative manifest."""


class IneligibleModelError(RuntimeError):
    """Raised when an ineligible (paused, revoked, or non-evaluated) model is requested."""


class ModelEvaluationError(RuntimeError):
    """Raised when a model evaluation violates quality or safety boundaries."""


class ModelRegistryManager:
    """Manages model metadata, lifecycle states, evaluation scorecards, and run manifests."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()

    def register_model(self, model: ModelRecord) -> ModelRecord:
        """Register an immutable model entry."""
        row_for_hash = model.to_db_row(computed_hash="")
        row_for_hash.pop("record_hash", None)
        record_hash = compute_model_registry_hash(row_for_hash)

        row_data = model.to_db_row(computed_hash=record_hash)

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO model_registry (
                    model_id, provider, model_name, access_tier, region_compliance,
                    quota_info, privacy_class, status, last_verified_at, created_at, record_hash
                ) VALUES (
                    :model_id, :provider, :model_name, :access_tier, :region_compliance,
                    :quota_info, :privacy_class, :status, :last_verified_at, :created_at, :record_hash
                )
                """,
                row_data,
            )
            AuditLogger(tx).log_event(
                actor="masa.model_registry",
                action="MODEL_REGISTERED",
                entity_type="model_registry",
                entity_id=model.model_id,
                payload={
                    "provider": model.provider,
                    "model_name": model.model_name,
                    "status": model.status.value,
                    "access_tier": model.access_tier.value,
                    "record_hash": record_hash,
                },
            )

        return ModelRecord.from_db_row(row_data)

    def get_model(self, model_id: str) -> Optional[ModelRecord]:
        """Fetch model by model_id."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM model_registry WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            if not row:
                return None
            return ModelRecord.from_db_row(row)
        finally:
            conn.close()

    def list_models(self, status: Optional[ModelStatus] = None) -> List[ModelRecord]:
        """List registered models with optional status filter."""
        conn = self.db.get_connection()
        try:
            q = "SELECT * FROM model_registry WHERE 1=1"
            params: List[Any] = []
            if status is not None:
                q += " AND status = ?"
                params.append(status.value if isinstance(status, ModelStatus) else str(status))
            q += " ORDER BY created_at ASC"
            rows = conn.execute(q, tuple(params)).fetchall()
            return [ModelRecord.from_db_row(r) for r in rows]
        finally:
            conn.close()

    def seed_default_models(self) -> List[ModelRecord]:
        """Seed default supported model providers (local, free, subscription)."""
        defaults = [
            ModelRecord(
                model_id="mod_local_deterministic",
                provider="local",
                model_name="deterministic-engine",
                access_tier=ModelAccessTier.LOCAL,
                region_compliance="EU_LOCAL",
                quota_info="unlimited",
                privacy_class=ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED,
                status=ModelStatus.ELIGIBLE,
            ),
            ModelRecord(
                model_id="mod_google_gemini_pro",
                provider="google",
                model_name="gemini-1.5-pro",
                access_tier=ModelAccessTier.SUBSCRIPTION,
                region_compliance="EU_COMPLIANT",
                quota_info="google_ai_pro_plan",
                privacy_class=ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED,
                status=ModelStatus.DISCOVERED,
            ),
            ModelRecord(
                model_id="mod_google_gemini_flash",
                provider="google",
                model_name="gemini-3.8-flash",
                access_tier=ModelAccessTier.FREE,
                region_compliance="EU_COMPLIANT",
                quota_info="free_rate_limited",
                privacy_class=ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED,
                status=ModelStatus.ELIGIBLE,
            ),
            ModelRecord(
                model_id="mod_chatgpt_gpt6_sol",
                provider="chatgpt",
                model_name="gpt-6.1-sol",
                access_tier=ModelAccessTier.SUBSCRIPTION,
                region_compliance="EU_COMPLIANT",
                quota_info="chatgpt_plus_pro",
                privacy_class=ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED,
                status=ModelStatus.ELIGIBLE,
            ),
            ModelRecord(
                model_id="mod_lmstudio_local",
                provider="lmstudio",
                model_name="qwen-2.5-7b-instruct",
                access_tier=ModelAccessTier.LOCAL,
                region_compliance="EU_LOCAL",
                quota_info="unlimited",
                privacy_class=ModelPrivacyClass.CONFIDENTIAL_ANONYMIZED,
                status=ModelStatus.DISCOVERED,
            ),
        ]
        results = []
        for d in defaults:
            existing = self.get_model(d.model_id)
            if existing is None:
                results.append(self.register_model(d))
            else:
                results.append(existing)
        return results

    def record_evaluation(self, eval_record: ModelEvaluationRecord) -> ModelEvaluationRecord:
        """Record benchmark evaluation.
        
        Strict Safety Invariant:
        If critical_error_passed is True (i.e. model failed by accepting a critical error),
        the model CANNOT become a champion (is_champion is forcibly False).
        """
        is_champ = eval_record.is_champion
        if eval_record.critical_error_passed:
            is_champ = False
            logger.warning(
                f"Model {eval_record.model_id} kritik hata örneğini kabul etti; terfi engellendi."
            )

        sanitized_eval = eval_record.model_copy(update={"is_champion": is_champ})

        row_for_hash = sanitized_eval.to_db_row(computed_hash="")
        row_for_hash.pop("record_hash", None)
        record_hash = compute_model_evaluation_hash(row_for_hash)

        row_data = sanitized_eval.to_db_row(computed_hash=record_hash)

        with self.db.transaction() as tx:
            # If this is champion, unmark previous champions for this task category in audit trail
            if is_champ:
                # In append-only DB we mark newly sealed evaluations with is_champion=1
                pass

            tx.execute(
                """
                INSERT INTO model_evaluations (
                    evaluation_id, model_id, eval_dataset_version, task_category,
                    score_pct, critical_error_passed, is_champion, eval_metrics_json,
                    created_at, record_hash
                ) VALUES (
                    :evaluation_id, :model_id, :eval_dataset_version, :task_category,
                    :score_pct, :critical_error_passed, :is_champion, :eval_metrics_json,
                    :created_at, :record_hash
                )
                """,
                row_data,
            )
            AuditLogger(tx).log_event(
                actor="masa.model_eval",
                action="MODEL_EVALUATED",
                entity_type="model_evaluation",
                entity_id=sanitized_eval.evaluation_id,
                payload={
                    "model_id": sanitized_eval.model_id,
                    "task_category": sanitized_eval.task_category.value,
                    "score_pct": str(sanitized_eval.score_pct),
                    "is_champion": is_champ,
                    "record_hash": record_hash,
                },
            )

        return ModelEvaluationRecord.from_db_row(row_data)

    def record_run(
        self,
        manifest: Optional[ModelManifest],
        status: ModelRunStatus = ModelRunStatus.COMPLETED,
        parent_run_id: Optional[str] = None,
    ) -> ModelRunRecord:
        """Record model execution run.
        
        Strict Invariants:
        1. Manifestless execution is strictly rejected (MissingManifestError).
        2. Paused or revoked models cannot be selected (IneligibleModelError).
        """
        if manifest is None:
            raise MissingManifestError("Manifestsiz çalışma reddedilir (ModelManifest zorunludur).")

        # Resolve or verify model eligibility
        quick_model = self._resolve_model_record(manifest.quick_provider, manifest.quick_model)
        deep_model = self._resolve_model_record(manifest.deep_provider, manifest.deep_model)

        for m_rec in (quick_model, deep_model):
            if m_rec.status in (ModelStatus.PAUSED, ModelStatus.REVOKED):
                raise IneligibleModelError(
                    f"Model '{m_rec.model_id}' ({m_rec.model_name}) durumu '{m_rec.status.value}' olduğundan seçilemez."
                )

        route_label = f"hızlı {manifest.quick_provider}/{manifest.quick_model} · derin {manifest.deep_provider}/{manifest.deep_model}"
        prompt_hash = sha256_text(manifest.prompt_summary)
        tools_str = json.dumps(manifest.tools, sort_keys=True)

        run_record = ModelRunRecord(
            task_name=manifest.task_name,
            quick_model_id=quick_model.model_id,
            deep_model_id=deep_model.model_id,
            route_label=route_label,
            prompt_hash=prompt_hash,
            tools_used=tools_str,
            selection_rationale=manifest.rationale,
            status=status,
            parent_run_id=parent_run_id,
        )

        row_for_hash = run_record.to_db_row(computed_hash="")
        row_for_hash.pop("record_hash", None)
        record_hash = compute_model_run_hash(row_for_hash)

        row_data = run_record.to_db_row(computed_hash=record_hash)

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO model_runs (
                    run_id, task_name, quick_model_id, deep_model_id, route_label,
                    prompt_hash, tools_used, selection_rationale, status,
                    parent_run_id, created_at, record_hash
                ) VALUES (
                    :run_id, :task_name, :quick_model_id, :deep_model_id, :route_label,
                    :prompt_hash, :tools_used, :selection_rationale, :status,
                    :parent_run_id, :created_at, :record_hash
                )
                """,
                row_data,
            )
            AuditLogger(tx).log_event(
                actor="masa.model_run",
                action="MODEL_RUN_SEALED",
                entity_type="model_run",
                entity_id=run_record.run_id,
                payload={
                    "task_name": run_record.task_name,
                    "route_label": route_label,
                    "status": run_record.status.value,
                    "parent_run_id": parent_run_id,
                    "record_hash": record_hash,
                },
            )

        return ModelRunRecord.from_db_row(row_data)

    def record_quota_hold(
        self,
        parent_run: ModelRunRecord,
        fallback_manifest: ModelManifest,
        quota_detail: str,
    ) -> Tuple[ModelRunRecord, ModelRunRecord]:
        """On rate limit / quota exhaustion:
        1. Seal a child sub-run with status WAITING_QUOTA.
        2. Initiate and seal a distinct fallback sub-run rather than silently merging outputs.
        """
        # Step 1: Record quota wait state
        held_run = self.record_run(
            manifest=ModelManifest(
                task_name=parent_run.task_name,
                quick_provider=fallback_manifest.quick_provider,
                quick_model=fallback_manifest.quick_model,
                deep_provider=fallback_manifest.deep_provider,
                deep_model=fallback_manifest.deep_model,
                prompt_summary=f"QUOTA_HELD: {quota_detail}",
                tools=[],
                rationale=f"İlk deneme kota hatasına takıldı ({quota_detail}). İş waiting_quota durumunda bekletiliyor.",
            ),
            status=ModelRunStatus.WAITING_QUOTA,
            parent_run_id=parent_run.run_id,
        )

        # Step 2: Record new alternate sub-run
        fallback_run = self.record_run(
            manifest=fallback_manifest,
            status=ModelRunStatus.COMPLETED,
            parent_run_id=held_run.run_id,
        )

        return held_run, fallback_run

    def get_champions(self) -> List[Dict[str, Any]]:
        """List current eligible champion models per task category."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM v_model_champions").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _resolve_model_record(self, provider: str, model_name: str) -> ModelRecord:
        """Resolve or auto-register model."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM model_registry WHERE provider = ? AND model_name = ?",
                (provider, model_name),
            ).fetchone()
            if row:
                return ModelRecord.from_db_row(row)
        finally:
            conn.close()

        # If not present, auto-discover
        tier = ModelAccessTier.SUBSCRIPTION if provider in ("chatgpt", "google") else ModelAccessTier.LOCAL
        m_id = f"mod_{provider}_{model_name.replace('.', '_').replace('-', '_')}"
        new_rec = ModelRecord(
            model_id=m_id,
            provider=provider,
            model_name=model_name,
            access_tier=tier,
            status=ModelStatus.DISCOVERED,
        )
        return self.register_model(new_rec)
