"""The demo's end-to-end analysis: untrusted input -> verdict -> policy decision.

One function per source kind (RAG document, tool response, tool manifest), each
returning a :class:`DemoResult` that carries everything the UI and the headless
runner display: provenance, the flagged spans (as raw-text offsets), the risk
score and band, the rule/normalisation evidence, the proposed downstream action,
and the deterministic policy outcome.

The detector here is **rules-only**. The demo must start from a clean checkout
with no 300 MB checkpoint and no network, so it uses the interpretable rule
engine; the risk bands come from the rules-only thresholds selected on dev
(`artifacts/results/results_dev.json`). The transformer and hybrid remain the
systems evaluated in the report; the demo's job is to make the guard's reasoning
visible, and the rule trace is what makes it visible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..normalize import Normalizer
from ..paths import RESULTS_DIR
from ..policy import CapabilityPolicy, Outcome, PolicyDecision, ProposedAction
from ..rules import RuleEngine, diff_manifest, manifest_hash, scan_tool_declaration
from ..rules.metadata import ManifestPin
from ..schema import Channel
from ..verdict import RiskBand, Verdict, build_verdict

__all__ = ["DemoResult", "UnitFinding", "analyse_manifest", "analyse_rag", "analyse_tool_response"]


@dataclass(slots=True)
class UnitFinding:
    """One analysed unit (a retrieved chunk, or a JSON leaf) and its verdict."""

    provenance: str
    raw_text: str
    normalized_text: str
    verdict: Verdict
    retrieval_score: float | None = None

    @property
    def risk(self) -> float:
        return self.verdict.risk

    def flagged_excerpts(self) -> list[str]:
        return [
            " ".join(span.slice(self.raw_text).split())
            for span in self.verdict.flagged_spans
        ]


@dataclass(slots=True)
class DemoResult:
    """The full outcome of analysing one scenario, guard-on."""

    source_kind: str  # rag_document | tool_response | tool_metadata
    title: str
    findings: list[UnitFinding]
    proposed_action: ProposedAction | None
    policy_decision: PolicyDecision | None
    expected_guard_off: str = ""
    expected_guard_on: str = ""
    manifest_note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def top(self) -> UnitFinding | None:
        return max(self.findings, key=lambda f: f.risk, default=None)

    @property
    def max_risk(self) -> float:
        return self.top.risk if self.top else 0.0

    @property
    def flagged(self) -> bool:
        return any(f.verdict.band != RiskBand.LOW for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "title": self.title,
            "max_risk": round(self.max_risk, 4),
            "flagged": self.flagged,
            "manifest_note": self.manifest_note,
            "findings": [
                {
                    "provenance": f.provenance,
                    "risk": round(f.risk, 4),
                    "band": f.verdict.band,
                    "retrieval_score": f.retrieval_score,
                    "flagged_spans": f.flagged_excerpts(),
                    "rule_trace": f.verdict.rule_trace[:4],
                    "evidence": [e.kind for e in f.verdict.normalisation_evidence],
                }
                for f in self.findings
            ],
            "proposed_action": self.proposed_action.to_dict() if self.proposed_action else None,
            "policy": self.policy_decision.to_dict() if self.policy_decision else None,
            "expected_guard_off": self.expected_guard_off,
            "expected_guard_on": self.expected_guard_on,
        }


# --------------------------------------------------------------- shared engine
@lru_cache(maxsize=1)
def _engine() -> RuleEngine:
    return RuleEngine()


@lru_cache(maxsize=1)
def _policy() -> CapabilityPolicy:
    return CapabilityPolicy()


@lru_cache(maxsize=1)
def rules_thresholds() -> dict[str, float]:
    """Rules-only operating points selected on dev, for risk banding.

    Falls back to empty (everything bands LOW) when the results file is absent,
    so the demo still runs on a fresh checkout before ``evaluate`` has been run.
    """

    path = RESULTS_DIR / "results_dev.json"
    if not path.is_file():
        return {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        if entry.get("name") == "rules-only":
            return {k: float(v) for k, v in entry["dev"]["thresholds"].items()}
    return {}


def _decide(
    result_findings: list[UnitFinding], action: ProposedAction | None
) -> PolicyDecision | None:
    if action is None:
        return None
    top = max(result_findings, key=lambda f: f.risk, default=None)
    verdict = top.verdict if top else None
    return _policy().decide(action, verdict=verdict)


def _proposed(action_name: str | None, catalog: dict[str, dict[str, str]]) -> ProposedAction | None:
    if not action_name:
        return None
    spec = catalog.get(action_name, {})
    from ..policy import ActionCategory

    category = spec.get("category")
    return ProposedAction(
        tool_name=action_name,
        category=ActionCategory.coerce(category) if category else None,
        description=spec.get("description", ""),
    )


# --------------------------------------------------------------------- RAG
def analyse_rag(scenario: Any, catalog: dict[str, dict[str, str]] | None = None) -> DemoResult:
    """Retrieve for the query, score each chunk, gate the proposed action."""

    engine = _engine()
    normalizer: Normalizer = engine.normalizer
    thresholds = rules_thresholds()
    chunks = scenario.retriever().retrieve(scenario.query, k=3)

    findings: list[UnitFinding] = []
    for chunk in chunks:
        unit = normalizer.normalize_text(
            chunk.text, channel=Channel.RAG_DOCUMENT, metadata={"host_task": scenario.query}
        )
        verdict = build_verdict(unit, engine.analyse(unit), thresholds=thresholds)
        findings.append(
            UnitFinding(
                provenance=f"retrieved: {chunk.doc_id}",
                raw_text=chunk.text,
                normalized_text=unit.normalized_text,
                verdict=verdict,
                retrieval_score=chunk.score,
            )
        )

    action = _proposed(scenario.proposed_action, catalog or {})
    decision = _decide(findings, action)
    return DemoResult(
        source_kind="rag_document",
        title=scenario.name,
        findings=findings,
        proposed_action=action,
        policy_decision=decision,
        expected_guard_off=scenario.expected_guard_off,
        expected_guard_on=scenario.expected_guard_on,
    )


# --------------------------------------------------------------- tool response
def analyse_tool_response(
    scenario: Any, catalog: dict[str, dict[str, str]] | None = None
) -> DemoResult:
    """Score every string leaf of the tool response, gate the proposed action."""

    engine = _engine()
    normalizer: Normalizer = engine.normalizer
    thresholds = rules_thresholds()
    units = normalizer.normalize_json(scenario.document, channel=Channel.TOOL_RESPONSE)

    findings: list[UnitFinding] = []
    for unit in units:
        verdict = build_verdict(unit, engine.analyse(unit), thresholds=thresholds)
        findings.append(
            UnitFinding(
                provenance=unit.json_path or "$",
                raw_text=unit.raw_text,
                normalized_text=unit.normalized_text,
                verdict=verdict,
            )
        )

    action = _proposed(scenario.proposed_action, catalog or {})
    decision = _decide(findings, action)
    return DemoResult(
        source_kind="tool_response",
        title=scenario.name,
        findings=findings,
        proposed_action=action,
        policy_decision=decision,
        expected_guard_on=scenario.expected,
    )


# ------------------------------------------------------------------- manifest
def analyse_manifest(
    scenario: Any,
    pinned_tool: dict[str, Any] | None = None,
    catalog: dict[str, dict[str, str]] | None = None,
) -> DemoResult:
    """Scan a tool declaration for poisoned metadata and manifest drift."""

    engine = _engine()
    normalizer: Normalizer = engine.normalizer
    thresholds = rules_thresholds()

    findings: list[UnitFinding] = []
    for path, value in _manifest_fields(scenario.tool):
        unit = normalizer.normalize_text(value, channel=Channel.TOOL_METADATA, json_path=path)
        verdict = build_verdict(unit, engine.analyse(unit), thresholds=thresholds)
        findings.append(
            UnitFinding(
                provenance=path,
                raw_text=value,
                normalized_text=unit.normalized_text,
                verdict=verdict,
            )
        )

    # Manifest-drift check: compare against the pinned (approved) tool if given.
    note = ""
    if pinned_tool is not None:
        pin = ManifestPin.from_tool(pinned_tool)
        diff = diff_manifest([scenario.tool], [pin])
        note = diff.summary()
        if not diff.is_clean:
            note += (
                f" — approved digest {pin.digest[:12]}…, "
                f"live digest {manifest_hash(scenario.tool)[:12]}…"
            )

    # A poisoned or drifted manifest raises the effective risk for the policy
    # even when the rewritten description reads as harmless on its own.
    field_findings = scan_tool_declaration(scenario.tool)
    return DemoResult(
        source_kind="tool_metadata",
        title=scenario.name,
        findings=findings,
        proposed_action=None,
        policy_decision=None,
        manifest_note=note,
        extra={"field_findings": field_findings},
    )


def _manifest_fields(tool: dict[str, Any]) -> list[tuple[str, str]]:
    fields = [("$.description", str(tool.get("description", "")))]
    schema = tool.get("parameters", {}) or {}
    for key, spec in (schema.get("properties", {}) or {}).items():
        text = str((spec or {}).get("description", "")).strip()
        if text:
            fields.append((f"$.parameters.properties.{key}.description", text))
    return [(p, v) for p, v in fields if v.strip()]


def guard_off_action(action: ProposedAction | None) -> str:
    """What a guard-*off* agent would do with the proposed action: just run it."""

    if action is None:
        return "no downstream action proposed"
    return f"call {action.tool_name}({action.category.value if action.category else '?'}) — executed unchecked"


def guard_on_action(decision: PolicyDecision | None) -> str:
    if decision is None:
        return "no downstream action proposed"
    verb = {
        Outcome.ALLOW: "allowed",
        Outcome.ISOLATE: "allowed after isolating the flagged context",
        Outcome.CONFIRM: "held for human confirmation",
        Outcome.BLOCK: "blocked",
    }[decision.outcome]
    return f"{decision.action.tool_name}: {verb}"


def load_thresholds_source() -> Path:
    return RESULTS_DIR / "results_dev.json"
