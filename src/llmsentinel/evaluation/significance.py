"""Paired significance tests between two systems scored on the same records.

Two questions, two tests:

* **Is one system's ranking better?** A paired bootstrap on the AUPRC difference:
  resample records with replacement, recompute both AUPRCs on the *same* resample,
  and read the interval and a two-sided p-value off the distribution of
  differences. Pairing matters: both systems see the same hard records.
* **Do they make different decisions at their operating points?** McNemar's exact
  test on the records where exactly one of the two is correct.

Neither test needs anything but per-record scores, which is why the evaluation
scripts persist them. The canonical test split's per-record scores were never
saved, and re-scoring test would break the score-once protocol, so these tests
are run on dev and on the fresh set only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from scipy.stats import binomtest

from .metrics import average_precision, validate_inputs

__all__ = ["McNemarResult", "PairedDelta", "mcnemar", "paired_bootstrap_delta"]


@dataclass(frozen=True, slots=True)
class PairedDelta:
    system_a: str
    system_b: str
    metric: str
    a: float
    b: float
    delta: float  # a - b
    ci_low: float
    ci_high: float
    p_value: float
    iterations: int

    def to_dict(self) -> dict[str, float | str | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class McNemarResult:
    system_a: str
    system_b: str
    only_a_correct: int
    only_b_correct: int
    p_value: float

    def to_dict(self) -> dict[str, float | str | int]:
        return asdict(self)


def paired_bootstrap_delta(
    y_true: Sequence[int],
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    *,
    names: tuple[str, str] = ("a", "b"),
    iterations: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> PairedDelta:
    """AUPRC(a) - AUPRC(b) with a paired percentile bootstrap interval."""

    labels, a = validate_inputs(y_true, scores_a)
    _, b = validate_inputs(y_true, scores_b)
    rng = np.random.default_rng(seed)
    size = labels.size
    deltas: list[float] = []
    for _ in range(iterations):
        index = rng.integers(0, size, size)
        resampled = labels[index]
        if resampled.sum() == 0 or resampled.sum() == size:
            continue
        deltas.append(average_precision(resampled, a[index]) - average_precision(resampled, b[index]))
    observed_a = average_precision(labels, a)
    observed_b = average_precision(labels, b)
    values = np.asarray(deltas)
    if values.size == 0:
        low = high = p = float("nan")
    else:
        low, high = (float(x) for x in np.quantile(values, [alpha / 2, 1 - alpha / 2]))
        # Two-sided: how often the resampled difference lands on the other side of 0.
        p = float(min(1.0, 2 * min(np.mean(values <= 0), np.mean(values >= 0))))
    return PairedDelta(
        system_a=names[0],
        system_b=names[1],
        metric="auprc",
        a=round(observed_a, 6),
        b=round(observed_b, 6),
        delta=round(observed_a - observed_b, 6),
        ci_low=round(low, 6),
        ci_high=round(high, 6),
        p_value=round(p, 6),
        iterations=int(values.size),
    )


def mcnemar(
    y_true: Sequence[int],
    predicted_a: Sequence[bool],
    predicted_b: Sequence[bool],
    *,
    names: tuple[str, str] = ("a", "b"),
) -> McNemarResult:
    """Exact McNemar test on the records where exactly one system is right."""

    labels = np.asarray(y_true, dtype=int)
    correct_a = np.asarray(predicted_a, dtype=bool) == labels.astype(bool)
    correct_b = np.asarray(predicted_b, dtype=bool) == labels.astype(bool)
    only_a = int(np.sum(correct_a & ~correct_b))
    only_b = int(np.sum(~correct_a & correct_b))
    disagreements = only_a + only_b
    p = 1.0 if disagreements == 0 else float(binomtest(only_a, disagreements, 0.5).pvalue)
    return McNemarResult(names[0], names[1], only_a, only_b, round(p, 6))
