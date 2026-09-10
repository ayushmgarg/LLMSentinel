"""Capability policy: one test per action category, plus the safety invariants.

The invariants matter more than the individual rows. A policy that is merely
*correct today* is worth little; what the project claims is that it is
deterministic, that it cannot execute anything, and that every failure mode
resolves towards more restriction.
"""

from __future__ import annotations

import ast
import inspect

import pytest
import yaml

from llmsentinel.policy import (
    ActionCategory,
    CapabilityPolicy,
    Outcome,
    PolicyDecision,
    ProposedAction,
)
from llmsentinel.policy import actions as actions_module
from llmsentinel.policy import engine as engine_module
from llmsentinel.schema import Channel
from llmsentinel.verdict import RiskBand, Verdict

POLICY = CapabilityPolicy()

BANDS = (RiskBand.LOW, RiskBand.ELEVATED, RiskBand.HIGH)


def decide(tool: str, band: str, **kwargs) -> PolicyDecision:
    return POLICY.decide(ProposedAction(tool_name=tool), risk_band=band, risk=0.5, **kwargs)


# ------------------------------------------------------- one per action class
def test_read_only_is_allowed_in_clean_context() -> None:
    decision = decide("get_report", RiskBand.LOW)
    assert decision.category is ActionCategory.READ_ONLY
    assert decision.outcome is Outcome.ALLOW
    assert decision.outcome.permits_action


def test_read_only_is_isolated_when_the_context_is_risky() -> None:
    for band in (RiskBand.ELEVATED, RiskBand.HIGH):
        decision = decide("get_report", band)
        assert decision.outcome is Outcome.ISOLATE
        # Isolation still lets the action run; it removes the flagged context.
        assert decision.outcome.permits_action


def test_sensitive_read_always_needs_a_human_or_is_blocked() -> None:
    outcomes = {decide("search_notes", band).outcome for band in BANDS}
    assert outcomes == {Outcome.CONFIRM, Outcome.BLOCK}
    assert all(outcome.requires_human for outcome in outcomes)


def test_external_send_is_confirmed_at_worst_and_blocked_when_risky() -> None:
    assert decide("send_email", RiskBand.LOW).outcome is Outcome.CONFIRM
    assert decide("send_email", RiskBand.ELEVATED).outcome is Outcome.BLOCK
    assert decide("send_email", RiskBand.HIGH).outcome is Outcome.BLOCK


def test_write_never_proceeds_unattended() -> None:
    for band in BANDS:
        assert decide("create_ticket", band).outcome.requires_human


def test_destructive_is_blocked_at_every_risk_level() -> None:
    for band in BANDS:
        decision = decide("delete_file", band)
        assert decision.category is ActionCategory.DESTRUCTIVE
        assert decision.outcome is Outcome.BLOCK


def test_destructive_is_blocked_even_at_zero_risk() -> None:
    """The score selects a column; it cannot overrule the row."""

    decision = POLICY.decide(
        ProposedAction(tool_name="transfer_funds"), risk_band=RiskBand.LOW, risk=0.0
    )
    assert decision.outcome is Outcome.BLOCK


def test_privilege_escalation_is_blocked_at_every_risk_level() -> None:
    for band in BANDS:
        decision = decide("grant_admin", band)
        assert decision.category is ActionCategory.PRIVILEGE_ESCALATION
        assert decision.outcome is Outcome.BLOCK


# ------------------------------------------------------------- fail-safe rules
def test_unknown_tool_takes_the_restrictive_fallback() -> None:
    decision = decide("some_tool_nobody_reviewed", RiskBand.LOW)
    assert decision.tool_was_unknown
    assert decision.category is ActionCategory.SENSITIVE_READ
    assert decision.outcome is Outcome.CONFIRM
    assert "fallback applied" in " ".join(decision.reasons)


def test_missing_risk_context_is_treated_as_high_risk() -> None:
    decision = POLICY.decide(ProposedAction(tool_name="get_report"))
    assert decision.risk_band == RiskBand.HIGH


def test_degraded_detector_escalates_one_step() -> None:
    clean = decide("get_report", RiskBand.LOW)
    degraded = decide("get_report", RiskBand.LOW, degraded=True)
    assert clean.outcome is Outcome.ALLOW
    assert degraded.outcome is Outcome.ISOLATE
    assert degraded.escalated
    assert "degraded" in " ".join(degraded.reasons)


def test_escalation_never_becomes_more_permissive() -> None:
    order = POLICY.config.escalation_order
    for tool in ("get_report", "search_notes", "send_email", "create_ticket", "delete_file"):
        for band in BANDS:
            plain = decide(tool, band)
            escalated = decide(tool, band, degraded=True)
            assert order.index(escalated.outcome) >= order.index(plain.outcome)


def test_unknown_risk_band_is_rejected_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown risk band"):
        decide("get_report", "medium-ish")


# ------------------------------------------------------------------ invariants
def test_decisions_are_deterministic() -> None:
    first = decide("send_email", RiskBand.ELEVATED)
    second = decide("send_email", RiskBand.ELEVATED)
    assert first.to_dict() == second.to_dict()


def test_policy_cannot_execute_anything() -> None:
    """The decision object is data: no attribute of it is callable.

    This is the structural half of "the system never executes an action". If a
    future change adds a handler or a callback to the decision, this test fails
    before that change can reach the demo.
    """

    decision = decide("delete_file", RiskBand.HIGH)
    for name in dir(decision):
        if name.startswith("_"):
            continue
        value = getattr(decision, name)
        assert not callable(value) or name in {
            "summary",
            "to_dict",
        }, f"{name} is callable on a PolicyDecision"


def test_policy_package_imports_nothing_that_can_act() -> None:
    """No module in the policy package may import a way to act.

    Checked over the parsed AST rather than the source text, so prose that
    merely *mentions* subprocess does not trip it and an actual import cannot
    hide inside a string.
    """

    forbidden = {
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "shutil",
        "smtplib",
        "ctypes",
    }
    dangerous_calls = {"eval", "exec", "compile", "__import__"}

    for module in (actions_module, engine_module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden, f"{module.__name__} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden, f"{module.__name__} imports from {node.module}"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in dangerous_calls, (
                    f"{module.__name__} calls {node.func.id}()"
                )


def test_every_action_class_has_a_row_for_every_band() -> None:
    for category in ActionCategory:
        row = POLICY.config.decisions[category]
        assert set(BANDS) <= set(row)


def test_a_policy_file_missing_an_action_class_is_rejected(tmp_path) -> None:
    """A silent default is exactly what the table exists to prevent."""

    raw = yaml.safe_load((POLICY.path).read_text(encoding="utf-8"))
    raw["decisions"].pop("destructive")
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no decision row"):
        CapabilityPolicy(path)


def test_a_policy_file_missing_a_band_is_rejected(tmp_path) -> None:
    raw = yaml.safe_load((POLICY.path).read_text(encoding="utf-8"))
    raw["decisions"]["external_send"].pop("high")
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no outcome for risk band"):
        CapabilityPolicy(path)


# ------------------------------------------------------ integration with verdict
def test_decision_reads_the_band_and_degraded_flag_from_a_verdict() -> None:
    verdict = Verdict(
        unit_id="u-1",
        channel=Channel.TOOL_RESPONSE,
        risk=0.97,
        band=RiskBand.HIGH,
        degraded=True,
    )
    decision = POLICY.decide(ProposedAction(tool_name="search_notes"), verdict=verdict)
    assert decision.risk_band == RiskBand.HIGH
    assert decision.risk == pytest.approx(0.97)
    assert decision.detector_degraded
    assert decision.outcome is Outcome.BLOCK


def test_caller_supplied_category_overrides_the_lookup() -> None:
    action = ProposedAction(tool_name="unlisted", category=ActionCategory.DESTRUCTIVE)
    decision = POLICY.decide(action, risk_band=RiskBand.LOW, risk=0.0)
    assert not decision.tool_was_unknown
    assert decision.outcome is Outcome.BLOCK


def test_decision_carries_an_audit_trail() -> None:
    payload = decide("send_email", RiskBand.HIGH).to_dict()
    assert payload["outcome"] == "block"
    assert payload["category"] == "external_send"
    assert payload["policy_version"] >= 1
    assert len(payload["reasons"]) >= 3
