"""Corpus construction: loaders, deduplication, grouped splits, leakage audit."""

from __future__ import annotations

from .build import (
    MIN_POSITIVES_PER_CELL,
    BuildResult,
    build_corpus,
    corpus_warnings,
    default_loaders,
)
from .corpus_card import render_corpus_card, split_summary, write_corpus_card
from .leakage import LeakageReport, check_leakage
from .splits import SplitConfig, SplitManifest, apply_splits, assign_group_splits

__all__ = [
    "MIN_POSITIVES_PER_CELL",
    "BuildResult",
    "LeakageReport",
    "SplitConfig",
    "SplitManifest",
    "apply_splits",
    "assign_group_splits",
    "build_corpus",
    "check_leakage",
    "corpus_warnings",
    "default_loaders",
    "render_corpus_card",
    "split_summary",
    "write_corpus_card",
]
