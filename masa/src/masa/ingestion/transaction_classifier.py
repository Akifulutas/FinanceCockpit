"""Transaction classifier re-export shim for masa.ingestion.transaction_classifier."""

from masa.calc.transaction_classifier import (
    ClassificationResult,
    ClassificationStatus,
    FlowClassification,
    SUPPORTED_CORPORATE_TYPES,
    SUPPORTED_SCALABLE_TYPES,
    classify_transaction,
    resolve_effective_type,
)

__all__ = [
    "ClassificationResult",
    "ClassificationStatus",
    "FlowClassification",
    "SUPPORTED_CORPORATE_TYPES",
    "SUPPORTED_SCALABLE_TYPES",
    "classify_transaction",
    "resolve_effective_type",
]
