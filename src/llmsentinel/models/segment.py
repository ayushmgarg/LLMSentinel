"""Segment-level scoring: a passage is as risky as its riskiest sentence.

Motivation (docs/EXPERIMENTS.md, 2026-09-27): on the fresh evaluation set the
transformer scored a blatant injection 0.996-1.000 on its own and 0.000-0.050 once
it sat inside a benign paragraph. The documents fit in one window, so the existing
max-over-windows did not help: the surrounding prose masked the instruction.

``SegmentScorer`` wraps an already-trained scorer and takes the maximum over the
whole passage and each of its segments -- sentences of prose, and the sentences of
each string leaf when the passage is a JSON tool result. Nothing is retrained. The
segmentation rule and ``MIN_WORDS`` were fixed before the scorer was run on any data;
thresholds come from the canonical dev split like every other system.

The expected cost is on hard negatives: a quoted attack sentence scored without the
sentence around it can look like the attack itself. Dev thresholds absorb part of
that; the rest is what the confirmatory fresh set measures.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import numpy as np

from ..normalize.segment import segment_sentences
from ..schema import CorpusRecord
from .base import Scorer

__all__ = ["MIN_WORDS", "SegmentScorer", "segments"]

#: Sentences shorter than this are not scored on their own: a fragment such as
#: "Thanks." carries no instruction and only adds noise. Fixed a priori.
MIN_WORDS = 4


def _leaves(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in _leaves(value)]
    if isinstance(node, list):
        return [leaf for value in node for leaf in _leaves(value)]
    return []


def segments(text: str, *, min_words: int = MIN_WORDS) -> list[str]:
    """Sentences worth scoring on their own (JSON tool results: per string leaf)."""

    stripped = text.strip()
    pieces = [text]
    if stripped[:1] in "{[":
        try:
            pieces = _leaves(json.loads(stripped)) or [text]
        except ValueError:
            pieces = [text]
    out: list[str] = []
    for piece in pieces:
        for sentence in segment_sentences(piece):
            candidate = sentence.text.strip()
            if len(candidate.split()) >= min_words and candidate != stripped:
                out.append(candidate)
    return out


class SegmentScorer(Scorer):
    """Max over the passage and its segments, using an already-trained ``base``."""

    def __init__(self, base: Scorer, *, min_words: int = MIN_WORDS) -> None:
        self.base = base
        self.min_words = min_words
        self.name = f"{base.name}-segment"

    def fit(self, records: Sequence[CorpusRecord]) -> SegmentScorer:
        # The base model is trained elsewhere; segmenting changes inference only.
        return self

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        texts: list[str] = []
        owner: list[int] = []
        for index, record in enumerate(records):
            texts.append(record.text)
            owner.append(index)
            for segment in segments(record.text, min_words=self.min_words):
                texts.append(segment)
                owner.append(index)
        scores = np.asarray(self.base.score_texts(texts), dtype=float)
        out = np.zeros(len(records), dtype=float)
        np.maximum.at(out, np.asarray(owner, dtype=int), scores)
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base": self.base.describe(),
            "segments": "passage + sentences (JSON: sentences of each string leaf)",
            "min_words": self.min_words,
        }
