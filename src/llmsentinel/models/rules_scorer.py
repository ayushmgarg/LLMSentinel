"""The rule engine as a :class:`~llmsentinel.models.base.Scorer`.

Two things live here rather than in :mod:`llmsentinel.rules`:

* the adapter that turns a corpus record into a normalised unit and back into a
  single score, so the rule engine can be evaluated exactly like every other
  system;
* the feature extractor the fusion layer consumes, which reuses the *same*
  analysis pass, so a feature vector can never disagree with the score shown in
  the demo for the same record.

Reports are cached by record id because the harness scores the same split with
several systems, and re-normalising a document three times is pure waste.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from ..normalize.units import NormalizedUnit
from ..rules.base import RuleReport
from ..rules.engine import RuleEngine, RuleEngineConfig
from ..schema import CorpusRecord
from .base import Scorer

__all__ = ["RulesScorer"]


class RulesScorer(Scorer):
    """Rules-only detector; also the feature source for fusion."""

    name = "rules-only"

    def __init__(
        self,
        engine: RuleEngine | None = None,
        *,
        config: RuleEngineConfig | None = None,
        cache: bool = True,
    ) -> None:
        self.engine = engine or RuleEngine(config=config)
        self._cache: dict[str, RuleReport] = {}
        self._use_cache = cache

    # ------------------------------------------------------------------ core
    def unit_for(self, record: CorpusRecord) -> NormalizedUnit:
        """Normalise a record, carrying provenance and host task into the unit."""

        return self.engine.normalizer.normalize_text(
            record.raw_text,
            channel=record.channel,
            json_path=record.json_path,
            unit_id=record.record_id,
            metadata={"host_task": record.host_task} if record.host_task else None,
        )

    def report_for(self, record: CorpusRecord) -> RuleReport:
        if self._use_cache and record.record_id in self._cache:
            return self._cache[record.record_id]
        report = self.engine.analyse(self.unit_for(record))
        if self._use_cache:
            self._cache[record.record_id] = report
        return report

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        return np.asarray([self.report_for(record).score for record in records], dtype=float)

    # -------------------------------------------------------------- features
    @property
    def feature_names(self) -> tuple[str, ...]:
        return self.engine.feature_names

    def features(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        """Fixed-layout rule feature matrix, shape ``(len(records), n_features)``."""

        return np.asarray(
            [self.engine.feature_vector(self.report_for(record)) for record in records],
            dtype=float,
        )

    # ------------------------------------------------------------------ misc
    def describe(self) -> dict[str, Any]:
        return {**super().describe(), **self.engine.describe()}

    def clear_cache(self) -> None:
        self._cache.clear()
