"""Run the perturbation transforms over a labelled sample and report the damage.

For a sample of injection positives we measure how often detection survives each
transform (detection rate at the dev operating point) and how the mean risk
moves. For a sample of hard negatives we measure whether the same transforms
manufacture false positives. Both matter: a transform that keeps recall but
inflates the benign false-positive rate is still a failure.

Nothing is tuned here and no threshold is selected; the dev threshold is passed
in and applied unchanged, so this is measurement, not model selection.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from ..models.base import Scorer
from ..schema import CorpusRecord, Label
from .perturbations import PERTURBATIONS

__all__ = ["PerturbationResult", "SuiteResult", "run_suite"]


@dataclass(slots=True)
class PerturbationResult:
    name: str
    group: str
    pos_detection: float
    pos_mean_risk: float
    neg_fpr: float

    def detection_drop(self, baseline: float) -> float:
        return baseline - self.pos_detection

    def fpr_rise(self, baseline: float) -> float:
        return self.neg_fpr - baseline


@dataclass(slots=True)
class SuiteResult:
    threshold: float
    n_pos: int
    n_neg: int
    results: list[PerturbationResult] = field(default_factory=list)

    @property
    def baseline(self) -> PerturbationResult:
        return next(r for r in self.results if r.name == "original")

    def failures(self, *, detection_drop: float = 0.10, fpr_rise: float = 0.05) -> list[str]:
        """Transforms that materially lose recall or gain false positives."""

        base = self.baseline
        bad = []
        for r in self.results:
            if r.name == "original":
                continue
            if r.detection_drop(base.pos_detection) > detection_drop or r.fpr_rise(base.neg_fpr) > fpr_rise:
                bad.append(r.name)
        return bad


def _sample(records: Sequence[CorpusRecord], predicate, n: int, seed: int) -> list[CorpusRecord]:
    pool = [r for r in records if predicate(r)]
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


def _take(pool: Sequence[CorpusRecord], n: int, seed: int) -> list[CorpusRecord]:
    rng = random.Random(seed)
    return rng.sample(list(pool), min(n, len(pool)))


def _detected_positives(
    records: Sequence[CorpusRecord], scorer: Scorer, threshold: float, cap: int
) -> list[CorpusRecord]:
    """Injection records the scorer already flags at baseline (original text)."""

    positives = [r for r in records if r.label is Label.INJECTION]
    if not positives:
        return []
    baseline = _records_for(positives, "original", cap)
    scores = np.asarray(scorer.score(baseline), dtype=float)
    return [record for record, score in zip(positives, scores, strict=True) if score >= threshold]


def _records_for(
    originals: Sequence[CorpusRecord], name: str, cap: int
) -> list[CorpusRecord]:
    from .perturbations import apply

    out = []
    for base in originals:
        text = apply(name, base.raw_text[:cap])
        # Content-addressed id: a cache keyed on record_id must not collide when
        # the same text is wrapped in different calls or at a different position.
        digest = hashlib.sha1(f"{name}:{text}".encode()).hexdigest()[:12]
        out.append(
            CorpusRecord(
                record_id=f"robust-{name}-{digest}",
                source_dataset="robustness",
                source_document_id=base.record_id,
                source_license="n/a",
                raw_text=text,
                label=base.label,
                channel=base.channel,
                attack_type=base.attack_type,
                host_task=base.host_task,
                json_path=base.json_path,
            )
        )
    return out


def run_suite(
    records: Sequence[CorpusRecord],
    scorer: Scorer,
    *,
    threshold: float,
    n_pos: int = 60,
    n_neg: int = 60,
    seed: int = 0,
    char_cap: int = 2000,
) -> SuiteResult:
    # Robustness is measured as recall *kept*: start from positives the detector
    # already catches at baseline, then perturb. Measuring against positives it
    # never detected would report noise, not robustness.
    detected = _detected_positives(records, scorer, threshold, char_cap)
    positives = _take(detected, n_pos, seed)
    negatives = _sample(records, lambda r: r.is_hard_negative, n_neg, seed + 1)
    if not positives or not negatives:
        raise ValueError(
            "need detected injection positives and hard negatives; "
            f"detected={len(detected)} hard_negatives={sum(r.is_hard_negative for r in records)}"
        )

    suite = SuiteResult(threshold=threshold, n_pos=len(positives), n_neg=len(negatives))
    for name, (_fn, group) in PERTURBATIONS.items():
        pos_scores = np.asarray(scorer.score(_records_for(positives, name, char_cap)), dtype=float)
        neg_scores = np.asarray(scorer.score(_records_for(negatives, name, char_cap)), dtype=float)
        suite.results.append(
            PerturbationResult(
                name=name,
                group=group,
                pos_detection=float(np.mean(pos_scores >= threshold)),
                pos_mean_risk=float(np.mean(pos_scores)),
                neg_fpr=float(np.mean(neg_scores >= threshold)),
            )
        )
    return suite
