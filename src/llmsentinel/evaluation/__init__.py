"""Metrics and evaluation utilities."""

from __future__ import annotations

from .harness import (
    SystemResult,
    load_splits,
    results_table,
    run_system,
    run_systems,
    save_results,
)
from .metrics import (
    BinaryMetrics,
    average_precision,
    bootstrap_ci,
    confusion_at,
    evaluate_scores,
    roc_auc,
    roc_curve,
    threshold_at_fpr,
    tpr_at_fpr,
    validate_inputs,
)

__all__ = [
    "BinaryMetrics",
    "SystemResult",
    "average_precision",
    "bootstrap_ci",
    "confusion_at",
    "evaluate_scores",
    "load_splits",
    "results_table",
    "roc_auc",
    "roc_curve",
    "run_system",
    "run_systems",
    "save_results",
    "threshold_at_fpr",
    "tpr_at_fpr",
    "validate_inputs",
]
