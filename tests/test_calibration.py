"""Per-source calibration: group integrity, the FPR guarantee, and the budget curve."""

from __future__ import annotations

import numpy as np

from llmsentinel.evaluation.calibration import (
    budget_curve,
    calibrated_threshold,
    evaluate_threshold,
    split_by_group,
)
from llmsentinel.schema import Channel, CorpusRecord, Label


def _record(i: int, group: str, label: int) -> CorpusRecord:
    return CorpusRecord(
        record_id=f"r{i}", source_dataset="t", source_document_id=group, source_license="n/a",
        raw_text=f"text {i}", label=Label.INJECTION if label else Label.BENIGN,
        channel=Channel.RAG_DOCUMENT, attack_type="exfiltration" if label else "none", group_id=group,
    )


def test_split_keeps_groups_whole_and_is_deterministic():
    records = [_record(i, f"g{i // 3}", i % 2) for i in range(60)]
    cal, ev = split_by_group(records, seed=7)
    assert {r.group_id for r in cal}.isdisjoint({r.group_id for r in ev})
    assert len(cal) + len(ev) == len(records)
    assert [r.record_id for r in cal] == [r.record_id for r in split_by_group(records, seed=7)[0]]
    assert [r.record_id for r in cal] != [r.record_id for r in split_by_group(records, seed=8)[0]]


def test_records_sharing_a_document_stay_on_one_side():
    # A clean page and an injected copy of the same host have different group ids
    # but the same source document; they must not be split.
    records = []
    for i in range(40):
        clean = _record(2 * i, f"host:{i}", 0)
        injected = _record(2 * i + 1, f"family:{i % 5}", 1)
        clean.source_document_id = injected.source_document_id = f"doc{i}"
        records += [clean, injected]
    cal, ev = split_by_group(records, seed=3)
    assert {r.source_document_id for r in cal}.isdisjoint({r.source_document_id for r in ev})


def test_calibrated_threshold_never_exceeds_the_budget_on_its_own_pages():
    rng = np.random.default_rng(0)
    for n in (99, 100, 250, 1000):
        scores = rng.random(n)
        threshold, allowed, guaranteed = calibrated_threshold(scores, 0.01)
        assert guaranteed and allowed == int(np.floor(0.01 * (n + 1) + 1e-9)) - 1
        assert int((scores >= threshold).sum()) <= allowed


def test_the_bound_holds_on_new_clean_pages():
    # Split-conformal: on fresh draws from the same distribution the flag rate stays <= target.
    rng = np.random.default_rng(1)
    rates = []
    for _ in range(400):
        threshold, _, _ = calibrated_threshold(rng.random(199), 0.01)
        rates.append(float((rng.random(2000) >= threshold).mean()))
    assert np.mean(rates) <= 0.01 + 0.002


def test_with_too_few_pages_no_false_positive_is_allowed():
    threshold, allowed, guaranteed = calibrated_threshold([0.1, 0.4, 0.9], 0.01)
    assert allowed == 0 and threshold > 0.9 and not guaranteed


def test_evaluate_threshold_and_budget_curve():
    labels = [1, 1, 0, 0]
    result = evaluate_threshold(labels, [0.9, 0.2, 0.1, 0.95], 0.5)
    assert (result.recall, result.fpr) == (0.5, 0.5)
    curve = budget_curve(np.linspace(0, 0.5, 200), [1, 1, 0], [0.9, 0.6, 0.1], sizes=(25, 100, 500), target_fpr=0.01)
    assert [row["clean_pages"] for row in curve] == [25, 100]  # 500 > pool size is skipped
    assert curve[1]["allowed_false_positives"] == 0 and curve[1]["guaranteed"] is True  # floor(0.01*101)-1
    assert curve[0]["guaranteed"] is False
