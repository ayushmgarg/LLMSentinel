"""Per-source threshold calibration (REMAINING_THINGS B1 / F7).

The out-of-distribution study found that a threshold chosen on dev does not survive a
change of source: the transformer still *ranked* held-out BIPIA reasonably (AUPRC
0.673) but caught 4% of its injections at the dev 1%-FPR threshold. Temperature
scaling cannot fix that -- it is monotone, so the ranking and any fixed-FPR cut-off
behave the same. What can fix it is choosing the threshold *on the target source*.

The realistic version needs no attacks from the target: a deployer has plenty of the
source's **clean** pages and none of its injections. So the threshold is set at the
target false-positive rate over clean calibration pages only, and judged on a
separate evaluation part of the same source:

* the source is split into a calibration part and an evaluation part along connected
  components of shared group *and* shared source document, so a clean page and an
  injected copy of the same host never land on opposite sides;
* only the calibration part's **benign** scores choose the threshold; its injections
  are never looked at;
* recall and realised FPR are reported on the evaluation part, beside the dev
  threshold's, and a budget curve shows how many clean pages are needed.

**The guarantee is for new pages, not the calibration pages.** With ``n`` clean
calibration scores and a new clean page from the same source (exchangeable), a
threshold just above the ``(k+1)``-th highest calibration score flags the new page
with probability at most ``(k+1)/(n+1)``. To keep that at or under the target ``f``
the rule allows ``k = floor(f * (n + 1)) - 1`` calibration false positives (a
split-conformal bound). That needs ``n >= 1/f - 1`` clean pages -- 99 for 1% --
and with fewer the bound cannot reach the target at all: the result says so
(``guaranteed`` is False) rather than pretending.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from ..schema import CorpusRecord

__all__ = [
    "CalibrationResult",
    "budget_curve",
    "calibrated_threshold",
    "evaluate_threshold",
    "split_by_group",
]


def _components(records: Sequence[CorpusRecord]) -> dict[str, str]:
    """Union-find over group_id and source_document_id: record_id-free component keys."""

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for record in records:
        a, b = find(f"g:{record.group_id}"), find(f"d:{record.source_document_id}")
        if a != b:
            parent[max(a, b)] = min(a, b)
    return {f"g:{r.group_id}": find(f"g:{r.group_id}") for r in records}


def split_by_group(
    records: Sequence[CorpusRecord], *, fraction: float = 0.5, seed: int = 0
) -> tuple[list[CorpusRecord], list[CorpusRecord]]:
    """(calibration, evaluation): whole connected components go to one side, deterministically."""

    component = _components(records)
    keys = sorted(set(component.values()))
    ranked = sorted(keys, key=lambda k: hashlib.sha256(f"{seed}|{k}".encode()).hexdigest())
    chosen = set(ranked[: round(fraction * len(ranked))])
    calibration = [r for r in records if component[f"g:{r.group_id}"] in chosen]
    evaluation = [r for r in records if component[f"g:{r.group_id}"] not in chosen]
    return calibration, evaluation


def calibrated_threshold(benign_scores: Sequence[float], target_fpr: float) -> tuple[float, int, bool]:
    """Threshold whose false-positive rate on *new* clean pages is at most ``target_fpr``.

    Returns ``(threshold, allowed_calibration_false_positives, guaranteed)``. A record is
    flagged when its score is ``>= threshold``. ``guaranteed`` is False when there are
    too few clean pages for the bound to reach the target; the threshold is then the
    strictest possible (just above the highest clean score).
    """

    scores = np.sort(np.asarray(benign_scores, dtype=float))[::-1]
    if scores.size == 0:
        raise ValueError("no clean pages to calibrate on")
    if np.isnan(scores).any():
        raise ValueError("NaN in the clean scores")
    k = math.floor(target_fpr * (scores.size + 1) + 1e-9) - 1
    guaranteed = k >= 0
    allowed = max(0, k)
    # Just above the (allowed+1)-th highest clean score; ties can only flag fewer.
    threshold = float(np.nextafter(scores[allowed], np.inf)) if allowed < scores.size else float(scores[-1])
    return threshold, allowed, guaranteed


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    threshold: float
    recall: float
    fpr: float
    positives: int
    negatives: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def evaluate_threshold(labels: Sequence[int], scores: Sequence[float], threshold: float) -> CalibrationResult:
    y = np.asarray(labels, dtype=int)
    s = np.asarray(scores, dtype=float)
    flagged = s >= threshold
    positives, negatives = int(y.sum()), int((1 - y).sum())
    return CalibrationResult(
        threshold=round(float(threshold), 6),
        recall=round(float(flagged[y == 1].mean()), 4) if positives else float("nan"),
        fpr=round(float(flagged[y == 0].mean()), 4) if negatives else float("nan"),
        positives=positives,
        negatives=negatives,
    )


def budget_curve(
    calibration_benign: Sequence[float],
    evaluation_labels: Sequence[int],
    evaluation_scores: Sequence[float],
    *,
    sizes: Sequence[int],
    target_fpr: float,
    draws: int = 20,
    seed: int = 0,
) -> list[dict[str, float]]:
    """Recall and FPR on the evaluation part when only ``n`` clean pages are available."""

    rng = np.random.default_rng(seed)
    pool = np.asarray(calibration_benign, dtype=float)
    rows = []
    for size in sizes:
        if size > pool.size:
            continue
        recalls, fprs = [], []
        for _ in range(draws):
            sample = rng.choice(pool, size=size, replace=False)
            threshold, allowed, guaranteed = calibrated_threshold(sample, target_fpr)
            result = evaluate_threshold(evaluation_labels, evaluation_scores, threshold)
            recalls.append(result.recall)
            fprs.append(result.fpr)
        rows.append(
            {
                "clean_pages": int(size),
                "allowed_false_positives": allowed,
                "guaranteed": guaranteed,
                "fpr_bound": round((allowed + 1) / (size + 1), 4),
                "recall_mean": round(float(np.mean(recalls)), 4),
                "recall_std": round(float(np.std(recalls)), 4),
                "fpr_mean": round(float(np.mean(fprs)), 4),
                "fpr_std": round(float(np.std(fprs)), 4),
            }
        )
    return rows
