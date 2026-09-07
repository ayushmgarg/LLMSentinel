"""Calibrated fusion of rule features and the transformer probability.

Why fuse at all
---------------
The two components fail differently.  Rules are precise and explainable but
brittle: a payload family nobody wrote a pattern for scores zero.  The
transformer generalises across paraphrase but produces a number with no reason
attached, and it cannot see that a document was base64-encoded before it was
read.  Fusion keeps the transformer's recall and the rules' evidence.

Where it is fitted, and why that matters
----------------------------------------
The meta-model is fitted on **dev**, never on train.  Fitting a stacker on the
same split the transformer memorised would teach it that the transformer is
always right.  Dev is the only split where the base systems behave the way they
will at test time.

That creates a second problem: numbers reported on dev would then be in-sample.
So :meth:`FusionScorer.fit` also computes **out-of-fold** predictions with a
grouped K-fold -- grouped by ``group_id`` so a payload family cannot appear in
both a fold's training and validation halves -- and :meth:`score` returns those
for any record it has an out-of-fold prediction for.  Dev numbers are therefore
honest, and test is scored by the model refitted on all of dev.

Calibration is the fusion model itself: a logistic regression fitted with log
loss outputs probabilities calibrated to the dev distribution, which is what the
threshold selection consumes.  No separate Platt or isotonic stage is applied,
because on this corpus size a second calibration split costs more than it buys.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from ..constants import DEFAULT_SEED
from ..schema import CorpusRecord
from .base import Scorer
from .rules_scorer import RulesScorer

__all__ = ["FusionScorer"]


@dataclass(slots=True)
class FusionState:
    """Everything needed to reproduce a fused score."""

    feature_names: list[str] = field(default_factory=list)
    coefficients: list[float] = field(default_factory=list)
    intercept: float = 0.0
    folds: int = 0
    n_fit: int = 0
    used_transformer: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": self.feature_names,
            "coefficients": [round(value, 5) for value in self.coefficients],
            "intercept": round(self.intercept, 5),
            "folds": self.folds,
            "n_fit": self.n_fit,
            "used_transformer": self.used_transformer,
        }

    def top_features(self, limit: int = 8) -> list[tuple[str, float]]:
        pairs = list(zip(self.feature_names, self.coefficients, strict=False))
        return sorted(pairs, key=lambda pair: abs(pair[1]), reverse=True)[:limit]


class FusionScorer(Scorer):
    """Logistic regression over rule features plus the transformer probability."""

    name = "hybrid"

    #: Dev scores are served from the out-of-fold cache, so timing a dev pass
    #: measures a dictionary lookup rather than the detector. The harness reads
    #: this flag and reports no latency instead of a misleading zero.
    scores_from_cache = True

    def __init__(
        self,
        rules: RulesScorer | None = None,
        transformer: Scorer | None = None,
        *,
        seed: int = DEFAULT_SEED,
        folds: int = 5,
        regularisation: float = 1.0,
    ) -> None:
        self.rules = rules or RulesScorer()
        self.transformer = transformer
        self.seed = seed
        self.folds = folds
        self.regularisation = regularisation
        self.state = FusionState()
        self._scaler: StandardScaler | None = None
        self._model: LogisticRegression | None = None
        self._oof: dict[str, float] = {}

    # -------------------------------------------------------------- features
    def _matrix(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        blocks = [self.rules.features(records)]
        if self.transformer is not None:
            probability = np.asarray(self.transformer.score(records), dtype=float).reshape(-1, 1)
            # The logit is included as well: near 0 and 1 the probability
            # saturates, and a linear model cannot separate "confident" from
            # "very confident" without it.
            clipped = np.clip(probability, 1e-6, 1 - 1e-6)
            blocks.append(probability)
            blocks.append(np.log(clipped / (1 - clipped)))
        return np.hstack(blocks)

    def _names(self) -> list[str]:
        names = list(self.rules.feature_names)
        if self.transformer is not None:
            names += ["transformer.probability", "transformer.logit"]
        return names

    def _new_model(self) -> LogisticRegression:
        return LogisticRegression(
            C=self.regularisation,
            max_iter=5000,
            class_weight="balanced",
            random_state=self.seed,
        )

    # ------------------------------------------------------------------- fit
    def fit(self, records: Sequence[CorpusRecord]) -> FusionScorer:
        """Fit on the **dev** split; also store grouped out-of-fold predictions."""

        if len(records) < 2 * self.folds:
            raise ValueError(
                f"fusion needs at least {2 * self.folds} records to cross-validate, "
                f"got {len(records)}"
            )
        features = self._matrix(records)
        labels = np.asarray([record.y for record in records], dtype=int)
        groups = np.asarray([record.group_id for record in records], dtype=object)

        self._oof = {}
        usable_folds = min(self.folds, len(set(groups.tolist())))
        if usable_folds >= 2:
            splitter = GroupKFold(n_splits=usable_folds)
            for train_index, test_index in splitter.split(features, labels, groups):
                if len(set(labels[train_index].tolist())) < 2:
                    continue
                scaler = StandardScaler().fit(features[train_index])
                model = self._new_model().fit(
                    scaler.transform(features[train_index]), labels[train_index]
                )
                probabilities = model.predict_proba(scaler.transform(features[test_index]))[:, 1]
                for position, probability in zip(test_index, probabilities, strict=True):
                    self._oof[records[position].record_id] = float(probability)

        self._scaler = StandardScaler().fit(features)
        self._model = self._new_model().fit(self._scaler.transform(features), labels)
        self.state = FusionState(
            feature_names=self._names(),
            coefficients=self._model.coef_[0].tolist(),
            intercept=float(self._model.intercept_[0]),
            folds=usable_folds,
            n_fit=len(records),
            used_transformer=self.transformer is not None,
        )
        return self

    # ----------------------------------------------------------------- score
    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        if self._model is None or self._scaler is None:
            raise RuntimeError("fusion must be fitted on the dev split before scoring")
        if not records:
            return np.zeros(0, dtype=float)

        unseen = [
            index for index, record in enumerate(records) if record.record_id not in self._oof
        ]
        scores = np.asarray(
            [self._oof.get(record.record_id, np.nan) for record in records], dtype=float
        )
        if unseen:
            subset = [records[index] for index in unseen]
            probabilities = self._model.predict_proba(
                self._scaler.transform(self._matrix(subset))
            )[:, 1]
            scores[unseen] = probabilities
        return scores

    # ------------------------------------------------------------------ misc
    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "seed": self.seed,
            "regularisation": self.regularisation,
            "fitted_on": "dev (out-of-fold predictions reported for dev)",
            **self.state.to_dict(),
            "top_features": [
                {"feature": name, "weight": round(weight, 4)}
                for name, weight in self.state.top_features()
            ],
        }
