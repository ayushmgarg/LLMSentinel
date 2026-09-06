"""Baselines.

Four systems, in increasing order of what they are allowed to know:

``MajorityBaseline``
    Predicts the training prior for every record.  Its AUPRC is the positive
    rate; anything that does not beat it has learned nothing.
``KeywordBaseline``
    A flat list of injection phrases, matched case-insensitively with no
    normalisation, no context and no scoring.  This is what a team ships in an
    afternoon, and it is the bar the rule engine has to clear to justify its
    complexity.
``TfidfBaseline``
    Word n-grams plus logistic regression.
``TfidfCharBaseline``
    Adds character n-grams, which is the standard defence against the spacing
    and homoglyph tricks that break word tokenisation.

All four are fitted on ``train`` only.  Thresholds are never chosen here -- the
harness selects them on ``dev`` and applies them to ``test``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from ..schema import CorpusRecord
from .base import Scorer

__all__ = [
    "KEYWORD_PATTERNS",
    "KeywordBaseline",
    "MajorityBaseline",
    "TfidfBaseline",
    "TfidfCharBaseline",
]

#: Deliberately naive: substrings a practitioner would grep for.  No word
#: boundaries, no context, no normalisation -- that is the point of the baseline.
KEYWORD_PATTERNS: Final[tuple[str, ...]] = (
    "ignore all previous",
    "ignore previous",
    "ignore the previous",
    "disregard previous",
    "disregard the above",
    "forget the above",
    "forget your instructions",
    "system prompt",
    "you are now",
    "from now on you",
    "new instructions",
    "override",
    "do not tell the user",
    "do not mention",
    "act as",
    "pretend you are",
    "send the api key",
    "send your api key",
    "api key to",
    "password to",
    "exfiltrate",
    "<|im_start|>",
    "[inst]",
    "### system",
    "always call this tool",
)


class MajorityBaseline(Scorer):
    """Constant score equal to the training positive rate."""

    name = "majority"

    def __init__(self) -> None:
        self.prior = 0.0

    def fit(self, records: Sequence[CorpusRecord]) -> MajorityBaseline:
        self.prior = float(np.mean([record.y for record in records])) if records else 0.0
        return self

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        return np.full(len(records), self.prior, dtype=float)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "prior": self.prior}


class KeywordBaseline(Scorer):
    """Fraction of the keyword list present in the record, capped at 1."""

    name = "keyword"

    def __init__(self, patterns: Sequence[str] = KEYWORD_PATTERNS, saturate_at: int = 2) -> None:
        self.patterns = tuple(patterns)
        #: Number of distinct hits at which the score reaches 1.0.  Kept low so
        #: the baseline stays a *detector*, not a graded model.
        self.saturate_at = max(1, saturate_at)
        self._regex = re.compile(
            "|".join(f"(?:{re.escape(pattern)})" for pattern in self.patterns), re.IGNORECASE
        )

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        scores = np.zeros(len(records), dtype=float)
        for index, record in enumerate(records):
            hits = len({match.group(0).lower() for match in self._regex.finditer(record.text)})
            scores[index] = min(1.0, hits / self.saturate_at)
        return scores

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "patterns": len(self.patterns), "saturate_at": self.saturate_at}


class TfidfBaseline(Scorer):
    """TF-IDF word n-grams plus L2 logistic regression."""

    name = "tfidf-word"

    def __init__(self, *, seed: int = 0, use_char_ngrams: bool = False, regularisation: float = 4.0) -> None:
        self.seed = seed
        self.use_char_ngrams = use_char_ngrams
        #: Inverse L2 strength (scikit-learn's ``C``).
        self.regularisation = regularisation
        self.pipeline: Pipeline | None = None

    def _build(self) -> Pipeline:
        word = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            min_df=2,
            sublinear_tf=True,
            strip_accents="unicode",
            lowercase=True,
        )
        if self.use_char_ngrams:
            char = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                min_df=2,
                sublinear_tf=True,
                lowercase=True,
            )
            features: Any = FeatureUnion([("word", word), ("char", char)])
        else:
            features = word
        return Pipeline(
            [
                ("features", features),
                (
                    "clf",
                    LogisticRegression(
                        C=self.regularisation,
                        max_iter=2000,
                        # The corpus is ~3:1 benign; without this the model
                        # optimises accuracy by under-predicting the class the
                        # whole project exists to catch.
                        class_weight="balanced",
                        random_state=self.seed,
                    ),
                ),
            ]
        )

    def fit(self, records: Sequence[CorpusRecord]) -> TfidfBaseline:
        if not records:
            raise ValueError("cannot fit on an empty training split")
        self.pipeline = self._build()
        self.pipeline.fit([record.text for record in records], [record.y for record in records])
        return self

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        if self.pipeline is None:
            raise RuntimeError(f"{self.name} must be fitted before scoring")
        if not records:
            return np.zeros(0, dtype=float)
        return self.pipeline.predict_proba([record.text for record in records])[:, 1]

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "char_ngrams": self.use_char_ngrams,
            "C": self.regularisation,
            "seed": self.seed,
        }


class TfidfCharBaseline(TfidfBaseline):
    """TF-IDF word **and** character n-grams plus logistic regression."""

    name = "tfidf-word+char"

    def __init__(self, *, seed: int = 0, regularisation: float = 4.0) -> None:
        super().__init__(seed=seed, use_char_ngrams=True, regularisation=regularisation)
