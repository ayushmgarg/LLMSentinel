"""The fresh evaluation sets: loader invariants and manifest-drift correctness (F10).

Drift detection is deterministic, so its fresh cases are a correctness test rather
than a metric: every case must come out exactly as annotated.
"""

from __future__ import annotations

import json

import pytest

from llmsentinel.evaluation.fresh import FRESH_PATH, load_fresh
from llmsentinel.rules import ManifestPin, diff_manifest

V2 = FRESH_PATH.with_name("fresh_eval_v2.yaml")
V3 = FRESH_PATH.with_name("fresh_eval_v3.yaml")
V4 = FRESH_PATH.with_name("fresh_eval_v4.yaml")


@pytest.fixture(scope="module", params=[FRESH_PATH, V2, V3, V4], ids=["v1", "v2", "v3", "v4"])
def fresh(request):
    return load_fresh(request.param, normalise=False)


def test_every_payload_span_is_exact(fresh):
    for case in fresh.cases:
        for span in case.record.injected_spans:
            if case.category == "tool":
                assert span.slice(case.record.raw_text) == case.record.raw_text
                continue
            expected = case.inserted
            if case.record.channel.value == "tool_response":
                expected = json.dumps(case.inserted, ensure_ascii=False)[1:-1]
            assert span.slice(case.record.raw_text) == expected, case.record.record_id


def test_counterparts_carry_no_payload_and_parse(fresh):
    payloads = [case.inserted for case in fresh.cases if case.inserted]
    for case in fresh.by_category("counterpart"):
        assert case.record.y == 0
        assert "{{PAYLOAD}}" not in case.record.raw_text
        assert not any(payload and payload in case.record.raw_text for payload in payloads)
        if case.record.channel.value == "tool_response":
            json.loads(case.record.raw_text)


def test_labels_match_categories(fresh):
    for case in fresh.cases:
        benign = case.category in ("counterpart", "hard_negative") or (
            case.category == "tool" and not case.record.injected_spans
        )
        assert case.record.y == (0 if benign else 1), case.record.record_id


def test_every_attacker_address_is_reserved(fresh):
    import re

    for case in fresh.cases:
        if not case.record.y:
            continue
        visible = case.record.raw_text.replace("​", "")
        for host in re.findall(r"(?:@|https?://)([A-Za-z0-9.-]+)", visible):
            # RFC 6761 reserved names only: attacker addresses are .invalid, benign
            # host senders .example.
            assert host.rstrip(".").endswith((".invalid", ".example", ".test")), (case.record.record_id, host)


def _status(approved, current) -> str:
    if approved is None:
        return "unpinned"
    diff = diff_manifest([current], [ManifestPin.from_tool(approved)])
    if diff.unchanged:
        return "unchanged"
    if diff.changed:
        return "changed"
    return "added"


def test_manifest_drift_cases_are_all_detected_correctly():
    fresh = load_fresh(FRESH_PATH, normalise=False)
    assert len(fresh.drift) == 6
    for case in fresh.drift:
        assert _status(case.approved, case.current) == case.expect, case.case_id
