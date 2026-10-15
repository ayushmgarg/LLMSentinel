"""Paired bootstrap and McNemar: direction, pairing and degenerate cases."""

from __future__ import annotations

import numpy as np

from llmsentinel.evaluation.significance import mcnemar, paired_bootstrap_delta


def _data(seed: int = 0, n: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    good = y + rng.normal(0, 0.4, n)
    bad = y + rng.normal(0, 2.0, n)
    return y, good, bad


def test_a_clearly_better_system_has_a_positive_interval():
    y, good, bad = _data()
    result = paired_bootstrap_delta(y, good, bad, names=("good", "bad"), iterations=500)
    assert result.delta > 0
    assert result.ci_low > 0
    assert result.p_value < 0.05


def test_identical_systems_have_zero_delta_and_no_significance():
    y, good, _ = _data()
    result = paired_bootstrap_delta(y, good, good, iterations=300)
    assert result.delta == 0
    assert result.ci_low == result.ci_high == 0
    assert result.p_value == 1.0


def test_bootstrap_is_deterministic_for_a_seed():
    y, good, bad = _data()
    assert paired_bootstrap_delta(y, good, bad, seed=3, iterations=200) == paired_bootstrap_delta(
        y, good, bad, seed=3, iterations=200
    )


def test_mcnemar_counts_only_disagreements():
    y = np.array([1, 1, 1, 1, 0, 0, 0, 0])
    a = np.array([1, 1, 1, 1, 0, 0, 0, 0])  # always right
    b = np.array([0, 0, 0, 1, 0, 0, 0, 0])  # misses three positives
    result = mcnemar(y, a, b, names=("a", "b"))
    assert (result.only_a_correct, result.only_b_correct) == (3, 0)
    assert 0 < result.p_value <= 0.25


def test_mcnemar_with_no_disagreement_is_not_significant():
    y = np.array([1, 0, 1, 0])
    assert mcnemar(y, y.astype(bool), y.astype(bool)).p_value == 1.0
