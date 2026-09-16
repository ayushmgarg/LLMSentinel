"""Headless run of the full demo — the recorded fallback and a smoke test.

Runs every demo scenario end to end and prints the guard-off vs guard-on story
for each: what an unguarded agent would do, what the guard flags, and the
deterministic policy decision. It needs no browser, no credentials and no
network, so it doubles as the "recorded fallback" the plan asks for and as a
scriptable check that the demo still works after a change.

    python scripts/demo_run.py
"""

from __future__ import annotations

import sys

from llmsentinel.demo import (
    analyse_manifest,
    analyse_rag,
    analyse_tool_response,
    load_manifest_scenarios,
    load_rag_scenarios,
    load_tool_scenarios,
    proposed_actions,
)
from llmsentinel.demo.pipeline import guard_off_action, guard_on_action


def _safe(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _show_result(result) -> None:
    top = result.top
    print(f"  max risk: {result.max_risk:.3f}   flagged: {result.flagged}")
    if result.manifest_note:
        print(f"  manifest: {_safe(result.manifest_note)}")
    if top and top.verdict.flagged_spans:
        print(f"  worst unit: {top.provenance}  (band {top.verdict.band})")
        print(f"    flagged span: {_safe(top.flagged_excerpts()[0][:110])}")
        for reason in top.verdict.rule_trace[:2]:
            print(f"    reason: {_safe(reason[:110])}")
        if top.verdict.normalisation_evidence:
            kinds = ", ".join(sorted({e.kind for e in top.verdict.normalisation_evidence}))
            print(f"    normalisation evidence: {kinds}")
    if result.proposed_action is not None:
        print(f"  guard OFF: {guard_off_action(result.proposed_action)}")
        print(f"  guard ON : {guard_on_action(result.policy_decision)}")


def main() -> int:
    catalog = proposed_actions()
    failures: list[str] = []

    _rule("SAFE RAG DEMONSTRATION")
    rag = load_rag_scenarios()
    for key in ("clean", "poisoned"):
        result = analyse_rag(rag[key], catalog)
        print(f"\n[{result.title}]  query: {rag[key].query!r}")
        _show_result(result)
        # Assertions that define a correct demo run.
        if key == "clean" and result.flagged:
            failures.append("clean RAG should not flag")
        if key == "poisoned":
            if not result.flagged:
                failures.append("poisoned RAG should flag")
            if result.policy_decision is None or result.policy_decision.outcome.value != "block":
                failures.append("poisoned RAG send_email should be blocked")

    _rule("SAFE MCP-STYLE TOOL RESPONSE DEMONSTRATION")
    tools = load_tool_scenarios()
    for key in ("clean", "poisoned"):
        result = analyse_tool_response(tools[key], catalog)
        print(f"\n[{result.title}]")
        _show_result(result)
        if key == "clean" and result.flagged:
            failures.append("clean tool response should not flag")
        if key == "poisoned":
            if not result.flagged:
                failures.append("poisoned tool response should flag")
            top = result.top
            if not top or "results[1]" not in top.provenance:
                failures.append("poisoned leaf should be at $.results[1].content")
            if result.policy_decision is None or result.policy_decision.outcome.value != "block":
                failures.append("poisoned tool response send_email should be blocked")

    _rule("SAFE MCP MANIFEST DEMONSTRATION")
    mans = load_manifest_scenarios()
    approved = mans["benign"].tool
    for key in ("benign", "poisoned", "changed_hash"):
        pinned = approved if mans[key].pinned_from else None
        result = analyse_manifest(mans[key], pinned_tool=pinned, catalog=catalog)
        print(f"\n[{result.title}]")
        _show_result(result)
        if key == "benign" and (result.flagged or result.manifest_note):
            failures.append("benign manifest should be clean with no drift")
        if key == "poisoned" and not result.flagged:
            failures.append("poisoned manifest should flag")
        if key == "changed_hash" and "drift" not in result.manifest_note:
            failures.append("changed-hash manifest should report drift")

    _rule("RESULT")
    if failures:
        print("DEMO CHECK FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all demo scenarios behaved as expected "
          "(clean quiet; poisoned flagged + gated; manifest drift caught)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
