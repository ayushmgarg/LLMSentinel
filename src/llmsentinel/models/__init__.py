"""Scoring systems: the shared interface, baselines and the fused detector."""

from __future__ import annotations

from .base import Scorer, ScoreResult, timed_scores

__all__ = ["ScoreResult", "Scorer", "timed_scores"]
