"""A logistic-regression detector over the semantic and source-aware features.

This is deliberately the *same shape* as the fusion layer (standardise, then a
balanced logistic regression fitted on train) so it is comparable to the other
systems through the evaluation harness with no special casing. It exists to
answer two questions the rule engine cannot:

* do semantic / task-conflict features add anything over a lexical baseline?
  (``scripts/semantic_eval.py``)
* do the provenance features help or hurt when the detector is moved to an
  unseen source dataset? (``scripts/provenance_transfer.py``, which flips
  ``use_source_features``)

It is an **experimental** detector: it is reported alongside the frozen systems,
never folded into them, until it is benchmarked on held-out data.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from ..constants import DEFAULT_SEED
from ..models.base import Scorer
from ..schema import CorpusRecord
from .features import SemanticFeatureExtractor
from .similarity import Embedder

__all__ = ["SemanticScorer"]


class SemanticScorer(Scorer):
    """Context-aware detector over semantic + provenance features."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        use_source_features: bool = True,
        seed: int = DEFAULT_SEED,
        regularisation: float = 1.0,
    ) -> None:
        self.extractor = SemanticFeatureExtractor(embedder, use_source_features=use_source_features)
        self.use_source_features = use_source_features
        self.seed = seed
        self.regularisation = regularisation
        self._scaler: StandardScaler | None = None
        self._model: LogisticRegression | None = None

    @property
    def name(self) -> str:
        return "semantic" if self.use_source_features else "semantic-no-source"

    def fit(self, records: Sequence[CorpusRecord]) -> SemanticScorer:
        features = self.extractor.matrix(records)
        labels = np.asarray([record.y for record in records], dtype=int)
        if len(set(labels.tolist())) < 2:
            raise ValueError("semantic scorer needs both classes in the training split")
        self._scaler = StandardScaler().fit(features)
        self._model = LogisticRegression(
            C=self.regularisation,
            max_iter=5000,
            class_weight="balanced",
            random_state=self.seed,
        ).fit(self._scaler.transform(features), labels)
        return self

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        if self._model is None or self._scaler is None:
            raise RuntimeError("semantic scorer must be fitted on train before scoring")
        if not records:
            return np.zeros(0, dtype=float)
        features = self._scaler.transform(self.extractor.matrix(records))
        return self._model.predict_proba(features)[:, 1]

    def coefficients(self) -> list[tuple[str, float]]:
        if self._model is None:
            return []
        pairs = list(zip(self.extractor.feature_names, self._model.coef_[0], strict=True))
        return sorted(pairs, key=lambda pair: abs(pair[1]), reverse=True)

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "embedder": self.extractor.embedder.name,
            "use_source_features": self.use_source_features,
            "n_features": len(self.extractor.feature_names),
            "seed": self.seed,
            "experimental": True,
            "top_features": [
                {"feature": name, "weight": round(float(weight), 4)}
                for name, weight in self.coefficients()[:8]
            ],
        }
