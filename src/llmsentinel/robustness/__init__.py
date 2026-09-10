"""Robustness and generalisation probes (section 12).

Meaning-preserving perturbations and a suite that measures how much recall a
detector loses — and how many false positives it gains — under each, at a fixed
dev operating point. Measurement only; no threshold is selected here.
"""

from __future__ import annotations

from .perturbations import PERTURBATIONS, apply, families
from .suite import PerturbationResult, SuiteResult, run_suite

__all__ = [
    "PERTURBATIONS",
    "PerturbationResult",
    "SuiteResult",
    "apply",
    "families",
    "run_suite",
]
