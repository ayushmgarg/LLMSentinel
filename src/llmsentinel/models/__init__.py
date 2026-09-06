"""Scoring systems: the shared interface, baselines and the fused detector."""

from __future__ import annotations

from .base import Scorer, ScoreResult, timed_scores
from .baselines import (
    KEYWORD_PATTERNS,
    KeywordBaseline,
    MajorityBaseline,
    TfidfBaseline,
    TfidfCharBaseline,
)
from .fusion import FusionScorer
from .rules_scorer import RulesScorer

__all__ = [
    "KEYWORD_PATTERNS",
    "FusionScorer",
    "KeywordBaseline",
    "MajorityBaseline",
    "RulesScorer",
    "ScoreResult",
    "Scorer",
    "TfidfBaseline",
    "TfidfCharBaseline",
    "timed_scores",
]
