"""LLMSentinel visual demo — a local Streamlit page.

Framework: **Streamlit**. Chosen because it renders a full interactive page from
one Python file with no build step, no JS, and no server credentials, which is
exactly what "a simple local web interface" in the plan asks for and what a
credential-free offline demo needs.

The page is a *view*: every decision is made in ``llmsentinel.demo.pipeline`` and
``llmsentinel.policy``. Nothing here scores, decides, or executes — it renders a
:class:`~llmsentinel.demo.pipeline.DemoResult`. Run it with:

    streamlit run src/llmsentinel/demo/app.py

or via the console entry point once installed:

    llmsentinel-demo
"""

from __future__ import annotations

import html
import json
import time
from typing import Any

import streamlit as st

from llmsentinel.demo import (
    analyse_manifest,
    analyse_rag,
    analyse_rag_text,
    analyse_tool_response,
    load_manifest_scenarios,
    load_rag_scenarios,
    load_tool_scenarios,
    proposed_actions,
)
from llmsentinel.demo.pipeline import (
    DemoResult,
    guard_off_action,
    guard_on_action,
    rules_thresholds,
)
from llmsentinel.normalize import Normalizer
from llmsentinel.rules import RuleEngine
from llmsentinel.schema import Channel, Span
from llmsentinel.verdict import build_verdict

_BAND_COLOUR = {"low": "#1a7f37", "elevated": "#bf8700", "high": "#cf222e"}


# --------------------------------------------------------------------- helpers
def _band_badge(band: str) -> str:
    colour = _BAND_COLOUR.get(band, "#57606a")
    return (
        f"<span style='background:{colour};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.8em'>{band.upper()}</span>"
    )


def _highlight(text: str, spans: list[Span]) -> str:
    """Render raw text with flagged character spans marked, offsets intact."""

    intervals = sorted(
        ((s.start, s.end) for s in spans if s.field == "raw_text" and s.end > s.start),
        key=lambda p: p[0],
    )
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out, cursor = [], 0
    for start, end in merged:
        out.append(html.escape(text[cursor:start]))
        out.append(
            "<mark style='background:#ffd6d6;padding:0 2px'>"
            + html.escape(text[start:end])
            + "</mark>"
        )
        cursor = end
    out.append(html.escape(text[cursor:]))
    return "<div style='white-space:pre-wrap;font-family:monospace;font-size:0.85em'>" + "".join(out) + "</div>"


def _render_finding(finding: Any, show_json_path: bool) -> None:
    v = finding.verdict
    label = finding.provenance
    if finding.retrieval_score is not None:
        label += f"  ·  retrieval {finding.retrieval_score:.2f}"
    st.markdown(f"**{label}**  —  risk {v.risk:.3f}  {_band_badge(v.band)}", unsafe_allow_html=True)
    if show_json_path and v.json_path:
        st.caption(f"JSON path: `{v.json_path}`")
    st.markdown(_highlight(finding.raw_text, v.flagged_spans), unsafe_allow_html=True)
    normalized = getattr(finding, "normalized_text", "") or ""
    if normalized and normalized != finding.raw_text:
        with st.expander("normalised text (what the detector scored)"):
            st.markdown(
                "<div style='white-space:pre-wrap;font-family:monospace;font-size:0.85em'>"
                + html.escape(normalized)
                + "</div>",
                unsafe_allow_html=True,
            )
    if v.rule_trace:
        with st.expander(f"why — {len(v.rule_trace)} rule signal(s)"):
            for reason in v.rule_trace:
                st.markdown(f"- {reason}")
    if v.normalisation_evidence:
        kinds = sorted({e.kind for e in v.normalisation_evidence})
        st.caption("normalisation evidence: " + ", ".join(kinds))


def _render_policy(result: DemoResult) -> None:
    st.subheader("Proposed downstream action & policy")
    if result.proposed_action is None:
        st.info("No downstream action proposed for this scenario.")
        return
    action = result.proposed_action
    decision = result.policy_decision
    col_off, col_on = st.columns(2)
    with col_off:
        st.markdown("**Guard OFF**")
        st.error(guard_off_action(action))
    with col_on:
        st.markdown("**Guard ON**")
        verb = decision.outcome.value.upper() if decision else "—"
        (st.success if decision and decision.outcome.permits_action else st.warning)(
            f"{verb} — {guard_on_action(decision)}"
        )
    if decision is not None:
        with st.expander("policy reasoning (deterministic)"):
            for reason in decision.reasons:
                st.markdown(f"- {reason}")
            st.caption(f"policy version {decision.policy_version}")


def _render_result(result: DemoResult, *, show_json_path: bool) -> None:
    st.subheader("Detection result")
    st.markdown(
        f"Highest risk across {len(result.findings)} unit(s): "
        f"**{result.max_risk:.3f}**  {_band_badge(result.top.verdict.band if result.top else 'low')}",
        unsafe_allow_html=True,
    )
    if result.manifest_note:
        (st.warning if "drift" in result.manifest_note else st.info)(result.manifest_note)
    for finding in sorted(result.findings, key=lambda f: f.risk, reverse=True):
        _render_finding(finding, show_json_path)
        st.divider()
    _render_policy(result)
    with st.expander("expected behaviour (guard off vs guard on)"):
        if result.expected_guard_off:
            st.markdown(f"**Guard off:** {result.expected_guard_off}")
        if result.expected_guard_on:
            st.markdown(f"**Guard on:** {result.expected_guard_on}")


def _disclaimer() -> None:
    with st.sidebar:
        st.divider()
        st.caption(
            "**Research prototype.** Detection is defence in depth, not a "
            "guarantee. It complements least privilege, human approval and "
            "server-side authorisation; it does not replace them. Nothing here "
            "is executed — the policy returns a decision, never an action. "
            "Runs fully offline; no credentials, no network."
        )
        st.caption(
            "**This demo scores with the rules-only detector**, so it starts with "
            "no checkpoint and its risk numbers are **not** the headline "
            "transformer/hybrid results — those are in docs/EXPERIMENTS.md. The "
            "rule trace is what makes the reasoning visible here."
        )


# ------------------------------------------------------------------------ page
def main() -> None:
    st.set_page_config(page_title="LLMSentinel demo", page_icon="🛡️", layout="wide")
    st.title("🛡️ LLMSentinel — indirect prompt-injection guard")
    st.caption(
        "Inspect untrusted RAG documents and MCP-style tool data; see the flagged "
        "spans, the reasons, and the deterministic capability-policy decision."
    )
    if not rules_thresholds():
        st.warning(
            "No dev thresholds found (`artifacts/results/results_dev.json`). Risk "
            "bands will all read LOW until you run `llmsentinel evaluate`."
        )

    source = st.sidebar.radio(
        "Source", ["RAG document", "Tool response (JSON)", "Tool manifest"]
    )
    catalog = proposed_actions()
    _disclaimer()

    started = time.perf_counter()
    result: DemoResult | None = None

    if source == "RAG document":
        scenarios = load_rag_scenarios()
        choice = st.sidebar.radio("Sample", ["clean", "poisoned"])
        pasted = st.sidebar.text_area("…or paste your own document text", height=140)
        scenario = scenarios[choice]
        st.markdown(f"### {scenario.name}")
        st.markdown(f"**User query (host task):** {scenario.query}")
        if pasted.strip():
            st.caption("using pasted document text (no retrieval)")
            st.markdown(_highlight(pasted, []))
        else:
            st.caption(f"provenance: local demo corpus · {len(scenario.documents)} documents indexed")
        if st.button("Run analysis", type="primary"):
            result = (
                analyse_rag_text(pasted, query=scenario.query, catalog=catalog)
                if pasted.strip()
                else analyse_rag(scenario, catalog)
            )

    elif source == "Tool response (JSON)":
        scenarios = load_tool_scenarios()
        choice = st.sidebar.radio("Sample", ["clean", "poisoned"])
        pasted = st.sidebar.text_area("…or paste your own JSON", height=140)
        scenario = scenarios[choice]
        st.markdown(f"### {scenario.name}")
        document = scenario.document
        if pasted.strip():
            try:
                document = json.loads(pasted)
                st.caption("using pasted JSON")
            except json.JSONDecodeError as exc:
                st.error(f"pasted text is not valid JSON: {exc}")
        st.json(document)
        if st.button("Run analysis", type="primary"):
            if pasted.strip() and document is not scenario.document:
                result = _analyse_pasted_json(document, catalog)
            else:
                result = analyse_tool_response(scenario, catalog)

    else:  # Tool manifest
        scenarios = load_manifest_scenarios()
        choice = st.sidebar.radio("Sample", ["benign", "poisoned", "changed_hash"])
        scenario = scenarios[choice]
        st.markdown(f"### {scenario.name}")
        if scenario.description:
            st.caption(scenario.description)
        st.json(scenario.tool)
        if st.button("Run analysis", type="primary"):
            pinned = scenarios["benign"].tool if scenario.pinned_from else None
            result = analyse_manifest(scenario, pinned_tool=pinned, catalog=catalog)

    if result is not None:
        _render_result(result, show_json_path=(source != "RAG document"))
        st.caption(f"analysed in {(time.perf_counter() - started) * 1000:.0f} ms")


def _analyse_pasted_json(document: Any, catalog: dict[str, Any]) -> DemoResult:
    """Analyse arbitrary pasted JSON as a tool response (paste-input path)."""

    engine = RuleEngine()
    normalizer: Normalizer = engine.normalizer
    from llmsentinel.demo.pipeline import UnitFinding

    findings = []
    for unit in normalizer.normalize_json(document, channel=Channel.TOOL_RESPONSE):
        verdict = build_verdict(unit, engine.analyse(unit), thresholds=rules_thresholds())
        findings.append(
            UnitFinding(
                provenance=unit.json_path or "$",
                raw_text=unit.raw_text,
                normalized_text=unit.normalized_text,
                verdict=verdict,
            )
        )
    return DemoResult(
        source_kind="tool_response",
        title="Tool response — pasted",
        findings=findings,
        proposed_action=None,
        policy_decision=None,
        expected_guard_on="Pasted input: no fixed expectation.",
    )


if __name__ == "__main__":
    main()
else:  # pragma: no cover - Streamlit imports the module and calls main itself
    main()
