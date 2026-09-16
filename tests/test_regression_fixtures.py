"""Replay every promoted analyst fixture against the current rule engine.

A reviewed injection must not score lower, and a reviewed benign case must not
score higher, than it did when it was promoted (within the recorded tolerance).
With no promoted fixtures yet, only the file's shape is checked.
"""

from __future__ import annotations

import pytest

from llmsentinel.analyst.fixtures import DISCOVERED_PATH, load_fixtures
from llmsentinel.rules import RuleEngine

FIXTURES = load_fixtures(DISCOVERED_PATH)
ENGINE = RuleEngine()


def test_fixture_file_is_well_formed() -> None:
    assert DISCOVERED_PATH.is_file()
    for fixture in FIXTURES:
        assert fixture["label"] in ("injection", "benign")
        assert fixture["text"] and fixture["rationale"]
        assert ".invalid" in fixture["text"] or "://" not in fixture["text"] or "example" in fixture["text"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_promoted_fixture_has_not_regressed(fixture: dict) -> None:
    _, report = ENGINE.analyse_text(fixture["text"], channel=fixture["channel"])
    tolerance = float(fixture.get("tolerance", 0.05))
    if fixture["label"] == "injection":
        assert report.score >= fixture["rule_score"] - tolerance, fixture["id"]
    else:
        assert report.score <= fixture["rule_score"] + tolerance, fixture["id"]
