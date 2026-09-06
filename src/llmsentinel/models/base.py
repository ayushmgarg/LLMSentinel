"""Common interface for every scoring system.

Baselines, the rule engine, the transformer and the fusion model are all used
through this one interface, so the evaluation harness has no special cases and
"the same splits and thresholds for every system" is enforced by construction
rather than by discipline.

A scorer returns a risk score in ``[0, 1]`` per record.  It is *not* required to
be calibrated -- ranking metrics do not need it, and calibration is the fusion
layer's job -- but it must be deterministic given its fitted state.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..schema import CorpusRecord

__all__ = ["ScoreResult", "Scorer", "timed_scores"]


class Scorer(ABC):
    """Base class for anything that turns records into risk scores."""

    #: Stable name used in result tables and the experiment log.
    name: str = "scorer"

    def fit(self, records: Sequence[CorpusRecord]) -> Scorer:
        """Fit on *training* records.  Stateless systems may ignore this."""

        return self

    @abstractmethod
    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        """Risk scores in ``[0, 1]``, one per record, in input order."""

    # ------------------------------------------------------------- utilities
    def score_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Score raw strings by wrapping them in throwaway records."""

        from ..schema import Channel, Label

        records = [
            CorpusRecord(
                record_id=f"adhoc-{index}",
                source_dataset="adhoc",
                source_document_id=f"adhoc-{index}",
                source_license="n/a",
                raw_text=text,
                label=Label.BENIGN,
                channel=Channel.UNKNOWN,
            )
            for index, text in enumerate(texts)
        ]
        return self.score(records)

    def save(self, path: str | Path) -> None:  # pragma: no cover - optional
        raise NotImplementedError(f"{type(self).__name__} does not support saving")

    @classmethod
    def load(cls, path: str | Path) -> Scorer:  # pragma: no cover - optional
        raise NotImplementedError(f"{cls.__name__} does not support loading")

    def describe(self) -> dict[str, Any]:
        """Configuration recorded alongside results in the experiment log."""

        return {"name": self.name, "type": type(self).__name__}

    def __repr__(self) -> str:  # pragma: no cover - display helper
        return f"<{type(self).__name__} name={self.name!r}>"


class ScoreResult:
    """Scores plus per-record latency, returned by :func:`timed_scores`."""

    __slots__ = ("latencies_ms", "scores")

    def __init__(self, scores: np.ndarray, latencies_ms: list[float]) -> None:
        self.scores = scores
        self.latencies_ms = latencies_ms


def timed_scores(
    scorer: Scorer, records: Sequence[CorpusRecord], *, batch: int = 1
) -> ScoreResult:
    """Score records while measuring latency the way the demo experiences it.

    Latency is measured per batch and divided by the batch size.  With
    ``batch=1`` (the default, and what the harness uses for the latency table)
    the figure is the true single-document cost, which is the number that
    matters for a guard sitting in a request path.
    """

    scores: list[float] = []
    latencies: list[float] = []
    for start in range(0, len(records), batch):
        chunk = records[start : start + batch]
        began = time.perf_counter()
        chunk_scores = scorer.score(chunk)
        elapsed_ms = (time.perf_counter() - began) * 1000.0
        scores.extend(np.asarray(chunk_scores, dtype=float).tolist())
        latencies.extend([elapsed_ms / max(1, len(chunk))] * len(chunk))
    return ScoreResult(np.asarray(scores, dtype=float), latencies)
