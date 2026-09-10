"""Metrics.

The reported figures are chosen for a *guard*, not for a balanced classifier:

``AUPRC``
    Average precision. With a rare positive class, ROC area is dominated by the
    large negative pool and looks good even when precision is unusable.
``TPR@1% FPR`` and ``TPR@0.1% FPR``
    What the guard catches at a false-positive budget an operator would accept.
    A guard that blocks one benign document in a hundred is already intrusive;
    one in a thousand is the realistic target.
``hard-negative FPR``
    The false-positive rate restricted to benign records that *look* like
    attacks. This is the number that decides whether the system is deployable,
    and it is reported separately because it is far worse than the overall FPR
    by construction.

AUROC is computed for comparison with published work only and is never used to
select a model or a threshold.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ..constants import TARGET_FPRS

__all__ = [
    "BinaryMetrics",
    "average_precision",
    "bootstrap_ci",
    "confusion_at",
    "evaluate_scores",
    "roc_auc",
    "roc_curve",
    "threshold_at_fpr",
    "tpr_at_fpr",
    "validate_inputs",
]


def validate_inputs(y_true: Sequence[int], y_score: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """Coerce and check labels/scores, failing loudly on the usual mistakes."""

    labels = np.asarray(y_true, dtype=float)
    scores = np.asarray(y_score, dtype=float)
    if labels.shape != scores.shape:
        raise ValueError(f"shape mismatch: labels {labels.shape}, scores {scores.shape}")
    if labels.ndim != 1:
        raise ValueError(f"expected 1-D inputs, got {labels.ndim}-D")
    if labels.size == 0:
        raise ValueError("no records to evaluate")
    unique = set(np.unique(labels).tolist())
    if not unique <= {0.0, 1.0}:
        raise ValueError(f"labels must be 0/1, found {sorted(unique)}")
    if not np.all(np.isfinite(scores)):
        raise ValueError("scores contain NaN or infinity")
    return labels.astype(int), scores


def roc_curve(y_true: Sequence[int], y_score: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(fpr, tpr, thresholds)`` with ties handled correctly.

    Written directly rather than delegated so that the tie handling is explicit:
    rule-based scores contain many exact ties, and a curve that splits a tie
    group reports a threshold that cannot actually be achieved.
    """

    labels, scores = validate_inputs(y_true, y_score)
    order = np.argsort(-scores, kind="mergesort")
    scores = scores[order]
    labels = labels[order]

    distinct = np.where(np.diff(scores))[0]
    cutoffs = np.r_[distinct, labels.size - 1]

    true_positives = np.cumsum(labels)[cutoffs]
    false_positives = 1 + cutoffs - true_positives

    positives = labels.sum()
    negatives = labels.size - positives
    if positives == 0 or negatives == 0:
        raise ValueError("both classes are required to compute a ROC curve")

    tpr = np.r_[0.0, true_positives / positives]
    fpr = np.r_[0.0, false_positives / negatives]
    thresholds = np.r_[np.inf, scores[cutoffs]]
    return fpr, tpr, thresholds


def roc_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    fpr, tpr, _ = roc_curve(y_true, y_score)
    return float(np.trapezoid(tpr, fpr))


def average_precision(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Area under the precision-recall curve, by the step-wise (AP) definition.

    The step-wise sum is used rather than trapezoidal interpolation because
    interpolating between operating points overstates performance where the
    curve is steep, which is exactly where a rare-positive detector lives.
    """

    labels, scores = validate_inputs(y_true, y_score)
    order = np.argsort(-scores, kind="mergesort")
    labels = labels[order]
    scores = scores[order]

    positives = labels.sum()
    if positives == 0:
        return 0.0

    distinct = np.where(np.diff(scores))[0]
    cutoffs = np.r_[distinct, labels.size - 1]
    true_positives = np.cumsum(labels)[cutoffs]
    predicted = cutoffs + 1

    precision = true_positives / predicted
    recall = true_positives / positives
    recall_gain = np.diff(np.r_[0.0, recall])
    return float(np.sum(precision * recall_gain))


def threshold_at_fpr(
    y_true: Sequence[int], y_score: Sequence[float], target_fpr: float
) -> tuple[float, float]:
    """Highest achievable TPR at or below ``target_fpr``, and its threshold.

    Returns ``(tpr, threshold)``.  Scoring at that threshold reproduces the
    reported TPR exactly, which is what makes the number auditable.
    """

    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    feasible = np.where(fpr <= target_fpr + 1e-12)[0]
    if feasible.size == 0:
        return 0.0, float("inf")
    best = feasible[np.argmax(tpr[feasible])]
    return float(tpr[best]), float(thresholds[best])


def tpr_at_fpr(y_true: Sequence[int], y_score: Sequence[float], target_fpr: float) -> float:
    return threshold_at_fpr(y_true, y_score, target_fpr)[0]


def confusion_at(
    y_true: Sequence[int], y_score: Sequence[float], threshold: float
) -> dict[str, int]:
    labels, scores = validate_inputs(y_true, y_score)
    predicted = (scores >= threshold).astype(int)
    return {
        "tp": int(np.sum((predicted == 1) & (labels == 1))),
        "fp": int(np.sum((predicted == 1) & (labels == 0))),
        "tn": int(np.sum((predicted == 0) & (labels == 0))),
        "fn": int(np.sum((predicted == 0) & (labels == 1))),
    }


def bootstrap_ci(
    y_true: Sequence[int],
    y_score: Sequence[float],
    metric: str = "auprc",
    *,
    iterations: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap interval, deterministic for a given seed."""

    labels, scores = validate_inputs(y_true, y_score)
    function = {"auprc": average_precision, "auroc": roc_auc}[metric]
    rng = np.random.default_rng(seed)
    size = labels.size
    samples: list[float] = []
    for _ in range(iterations):
        index = rng.integers(0, size, size)
        resampled = labels[index]
        if resampled.sum() == 0 or resampled.sum() == size:
            continue
        samples.append(function(resampled, scores[index]))
    if not samples:
        return (float("nan"), float("nan"))
    low, high = np.quantile(samples, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high)


@dataclass(slots=True)
class BinaryMetrics:
    """All headline numbers for one system on one split."""

    system: str
    split: str
    n: int
    positives: int
    negatives: int
    auprc: float
    auroc: float
    positive_rate: float
    tpr_at_fpr: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    #: FPR actually achieved at each operating point on *this* split.  A
    #: threshold chosen on dev does not reproduce its budget on test, so the
    #: realised rate has to be reported next to the target rather than inferred
    #: from the confusion matrix by the reader.
    fpr_achieved: dict[str, float] = field(default_factory=dict)
    #: True where ``fpr_achieved`` exceeds the operating point's target FPR.
    fpr_budget_exceeded: dict[str, bool] = field(default_factory=dict)
    hard_negative_fpr: dict[str, float] = field(default_factory=dict)
    per_channel: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Same breakdown as ``per_channel`` but keyed by source dataset, so a
    #: combined corpus cannot hide that headline AUPRC is carried by one source.
    #: Support counts are included because per-source dev/test cells are small.
    per_dataset: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Recall per attack type, keyed by operating point then by attack type --
    #: recall is meaningless without saying at which threshold it was measured.
    per_attack_recall: dict[str, dict[str, float]] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    latency_ms: dict[str, float] = field(default_factory=dict)
    ci: dict[str, tuple[float, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ci"] = {key: list(value) for key, value in self.ci.items()}
        return payload

    @property
    def budget_respected(self) -> bool:
        """False when any operating point exceeded its false-positive budget."""

        return not any(self.fpr_budget_exceeded.values())

    def headline(self) -> str:
        parts = [f"AUPRC={self.auprc:.3f}", f"AUROC={self.auroc:.3f}"]
        for key, value in self.tpr_at_fpr.items():
            achieved = self.fpr_achieved.get(key)
            marker = "!" if self.fpr_budget_exceeded.get(key) else ""
            suffix = f" (FPR={achieved:.4f}{marker})" if achieved is not None else ""
            parts.append(f"TPR@{key}={value:.3f}{suffix}")
        for key, value in self.hard_negative_fpr.items():
            parts.append(f"hardFPR@{key}={value:.3f}")
        return f"{self.system} [{self.split}] " + " ".join(parts)


def evaluate_scores(
    *,
    system: str,
    split: str,
    y_true: Sequence[int],
    y_score: Sequence[float],
    is_hard_negative: Sequence[bool] | None = None,
    channels: Sequence[str] | None = None,
    source_datasets: Sequence[str] | None = None,
    attack_types: Sequence[str] | None = None,
    target_fprs: Sequence[float] = TARGET_FPRS,
    latencies_ms: Sequence[float] | None = None,
    thresholds: dict[str, float] | None = None,
    bootstrap: int = 0,
    seed: int = 0,
) -> BinaryMetrics:
    """Compute every reported metric for one system.

    ``thresholds`` lets the caller supply operating points chosen on *dev*; when
    omitted, thresholds are derived from the data being evaluated, which is only
    valid on dev itself.  The harness passes dev thresholds explicitly when
    scoring test, and records which it used in ``notes``.
    """

    labels, scores = validate_inputs(y_true, y_score)
    positives = int(labels.sum())
    negatives = int(labels.size - positives)

    metrics = BinaryMetrics(
        system=system,
        split=split,
        n=int(labels.size),
        positives=positives,
        negatives=negatives,
        auprc=average_precision(labels, scores),
        auroc=roc_auc(labels, scores),
        positive_rate=positives / labels.size,
    )

    for target in target_fprs:
        key = _fpr_key(target)
        if thresholds and key in thresholds:
            threshold = thresholds[key]
            confusion = confusion_at(labels, scores, threshold)
            achieved = confusion["tp"] / positives if positives else 0.0
            metrics.tpr_at_fpr[key] = achieved
            metrics.thresholds[key] = threshold
            metrics.notes.append(f"threshold for {key} taken from dev: {threshold:.6f}")
        else:
            achieved, threshold = threshold_at_fpr(labels, scores, target)
            metrics.tpr_at_fpr[key] = achieved
            metrics.thresholds[key] = threshold
        confusion = confusion_at(labels, scores, threshold)
        metrics.confusion[key] = confusion

        # A threshold selected on dev is not guaranteed to hold its budget here.
        # Report what it actually cost, and say so when the budget is blown --
        # a TPR quoted at "1% FPR" that really runs at 6% is not that TPR.
        realised = confusion["fp"] / negatives if negatives else 0.0
        metrics.fpr_achieved[key] = realised
        exceeded = realised > target + 1e-12
        metrics.fpr_budget_exceeded[key] = exceeded
        if exceeded:
            metrics.warnings.append(
                f"{key}: realised FPR {realised:.4f} exceeds the {target:g} budget "
                f"({confusion['fp']} false positives on {negatives} negatives); "
                f"the reported TPR is not a {target:g}-FPR operating point on this split"
            )

        if is_hard_negative is not None:
            mask = np.asarray(is_hard_negative, dtype=bool) & (labels == 0)
            if mask.any():
                metrics.hard_negative_fpr[key] = float(
                    np.mean(scores[mask] >= threshold)
                )

    if channels is not None:
        metrics.per_channel = _per_group(labels, scores, channels, metrics.thresholds)
    if source_datasets is not None:
        metrics.per_dataset = _per_group(labels, scores, source_datasets, metrics.thresholds)
    if attack_types is not None:
        metrics.per_attack_recall = _per_attack_recall(
            labels, scores, attack_types, metrics.thresholds
        )
    if latencies_ms is not None and len(latencies_ms):
        values = np.asarray(latencies_ms, dtype=float)
        metrics.latency_ms = {
            "mean": float(values.mean()),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "max": float(values.max()),
        }
    if bootstrap:
        metrics.ci["auprc"] = bootstrap_ci(
            labels, scores, "auprc", iterations=bootstrap, seed=seed
        )
    return metrics


def _fpr_key(target: float) -> str:
    return f"fpr={target:g}"


def _per_group(
    labels: np.ndarray,
    scores: np.ndarray,
    groups: Sequence[str],
    thresholds: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Per-subgroup metrics (used for both channel and source-dataset splits).

    AUPRC/AUROC are reported only for a subgroup that carries both classes; a
    recall/FPR pair is added at each finite operating point. Support counts stay
    in every row so a metric over a handful of records is read as such.
    """

    group_array = np.asarray(groups, dtype=object)
    result: dict[str, dict[str, float]] = {}
    for group in sorted(set(group_array.tolist())):
        mask = group_array == group
        subset_labels = labels[mask]
        subset_scores = scores[mask]
        entry: dict[str, float] = {
            "n": float(mask.sum()),
            "positives": float(subset_labels.sum()),
        }
        if subset_labels.sum() and subset_labels.sum() < subset_labels.size:
            entry["auprc"] = average_precision(subset_labels, subset_scores)
            entry["auroc"] = roc_auc(subset_labels, subset_scores)
        for key, threshold in thresholds.items():
            if not math.isfinite(threshold):
                continue
            predicted = subset_scores >= threshold
            if subset_labels.sum():
                entry[f"recall@{key}"] = float(predicted[subset_labels == 1].mean())
            if (subset_labels == 0).any():
                entry[f"fpr@{key}"] = float(predicted[subset_labels == 0].mean())
        result[str(group)] = entry
    return result


def _per_attack_recall(
    labels: np.ndarray,
    scores: np.ndarray,
    attack_types: Sequence[str],
    thresholds: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Recall per attack type, reported separately at every operating point.

    Quoting one recall number without naming its threshold hides the trade-off
    that matters: a family can look well covered at 1% FPR and disappear at
    0.1%.  Each operating point therefore gets its own row, plus the support
    count so a recall computed over three examples is not read as a result.
    """

    attacks = np.asarray(attack_types, dtype=object)
    result: dict[str, dict[str, float]] = {}
    for key, threshold in thresholds.items():
        if not math.isfinite(threshold):
            continue
        row: dict[str, float] = {}
        for attack in sorted(set(attacks[labels == 1].tolist())):
            mask = (attacks == attack) & (labels == 1)
            if mask.any():
                row[str(attack)] = float(np.mean(scores[mask] >= threshold))
                row[f"{attack}__support"] = float(mask.sum())
        result[key] = row
    return result
