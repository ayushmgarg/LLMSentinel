"""The demo must behave deterministically: clean stays quiet, poisoned is flagged
and gated, manifest drift is caught. These are the Week 3 exit criteria as tests
so a change that breaks the demo fails CI, not the live presentation."""

from __future__ import annotations

from llmsentinel.demo import (
    analyse_manifest,
    analyse_rag,
    analyse_tool_response,
    load_manifest_scenarios,
    load_rag_scenarios,
    load_tool_scenarios,
    proposed_actions,
)
from llmsentinel.policy import Outcome
from llmsentinel.verdict import RiskBand

CATALOG = proposed_actions()


# ------------------------------------------------------------------------- RAG
def test_clean_rag_is_quiet() -> None:
    result = analyse_rag(load_rag_scenarios()["clean"], CATALOG)
    assert not result.flagged
    assert all(f.verdict.band == RiskBand.LOW for f in result.findings)


def test_poisoned_rag_is_flagged_and_send_blocked() -> None:
    result = analyse_rag(load_rag_scenarios()["poisoned"], CATALOG)
    assert result.flagged
    top = result.top
    assert top is not None and top.verdict.flagged_spans
    # The injected instruction is highlighted in the raw text.
    assert any("ignore all previous" in e.lower() for e in top.flagged_excerpts())
    assert result.policy_decision is not None
    assert result.policy_decision.outcome is Outcome.BLOCK


def test_poisoned_rag_span_maps_to_raw_text() -> None:
    result = analyse_rag(load_rag_scenarios()["poisoned"], CATALOG)
    top = result.top
    for span in top.verdict.flagged_spans:
        assert span.field == "raw_text"
        assert 0 <= span.start < span.end <= len(top.raw_text)


# --------------------------------------------------------------- tool response
def test_clean_tool_response_is_quiet_and_read_allowed() -> None:
    result = analyse_tool_response(load_tool_scenarios()["clean"], CATALOG)
    assert not result.flagged
    assert result.policy_decision.outcome is Outcome.ALLOW


def test_poisoned_tool_response_flags_the_named_json_path() -> None:
    result = analyse_tool_response(load_tool_scenarios()["poisoned"], CATALOG)
    assert result.flagged
    top = result.top
    assert top.provenance == "$.results[1].content"
    assert result.policy_decision.outcome is Outcome.BLOCK


# ------------------------------------------------------------------- manifest
def test_benign_manifest_is_clean_and_undrifted() -> None:
    result = analyse_manifest(load_manifest_scenarios()["benign"], catalog=CATALOG)
    assert not result.flagged
    assert result.manifest_note == ""


def test_poisoned_manifest_is_flagged() -> None:
    result = analyse_manifest(load_manifest_scenarios()["poisoned"], catalog=CATALOG)
    assert result.flagged
    assert result.top.provenance.startswith("$.")


def test_changed_hash_manifest_reports_drift() -> None:
    scenarios = load_manifest_scenarios()
    result = analyse_manifest(
        scenarios["changed_hash"], pinned_tool=scenarios["benign"].tool, catalog=CATALOG
    )
    # The rewrite reads harmless, but a silent change to an approved tool is the
    # signal: drift must be reported regardless of the new description's content.
    assert "drift" in result.manifest_note


def test_demo_result_serialises() -> None:
    result = analyse_rag(load_rag_scenarios()["poisoned"], CATALOG)
    payload = result.to_dict()
    assert payload["flagged"] is True
    assert payload["policy"]["outcome"] == "block"


def test_nothing_in_demo_executes() -> None:
    """A DemoResult carries a decision, never a way to act on it."""

    result = analyse_tool_response(load_tool_scenarios()["poisoned"], CATALOG)
    decision = result.policy_decision
    for name in dir(decision):
        if name.startswith("_"):
            continue
        assert not callable(getattr(decision, name)) or name in {"summary", "to_dict"}
