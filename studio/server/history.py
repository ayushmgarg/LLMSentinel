"""Record a Studio comparison in the analyst history (checklist section 17).

The Studio has its own guard (it strips and withholds passages), so its outputs are
translated into the same :class:`~llmsentinel.analyst.ScanRecord` rows the SDK, the
CLI and the proxy write. Three kinds are recorded:

* ``content``  -- every retrieved passage, with its score, spans, rule trace and the
  isolation action the guard took;
* ``manifest`` -- every tool from a connected server, with its content verdict and drift;
* ``action``   -- every tool call the model requested in the *guarded* run, with the
  capability policy's decision. The unguarded run's calls are a counterfactual shown
  for comparison, not decisions anyone made, so they are not recorded.

Recording is best-effort: a history problem is reported with the result and never
breaks the comparison itself.
"""

from __future__ import annotations

import uuid
from typing import Any

from llmsentinel import __version__
from llmsentinel.analyst import ScanRecord, ScanStore, families_from_trace, review_reasons_for

from .guard import ChunkAssessment, SentinelGuard
from .manifests import ToolAssessment

__all__ = ["record_comparison"]

_PERMITTING = ("allow", "isolate")


def _versions(guard: SentinelGuard, batch: str) -> dict[str, Any]:
    return {
        "llmsentinel": __version__,
        "surface": "studio",
        #: One id per comparison, so everything recorded together can be found together
        #: (approving a server pins exactly the tools seen in its latest comparison).
        "batch": batch,
        "detector": guard.detector,
        "rules": sorted(rule.rule_id for rule in guard.engine.rules),
        "thresholds_source": str(guard.settings.results_path.name),
    }


def _content(item: ChunkAssessment, guard: SentinelGuard, question: str, batch: str) -> ScanRecord:
    model_used = item.model_risk is not None
    thresholds = guard.model_thresholds if model_used else guard.rule_thresholds
    return ScanRecord(
        kind="content",
        source=item.source,
        channel=item.channel,
        json_path=item.json_path,
        host_task=question,
        text=item.text,
        risk=item.risk,
        band=item.band,
        rule_score=item.rule_risk,
        model_score=item.model_risk,
        detector=guard.detector,
        decided_by=f"{item.decided_by}; isolation: {item.action}",
        thresholds=thresholds,
        flagged=item.flagged,
        rule_trace=list(item.reasons),
        spans=list(item.spans),
        evidence=list(item.evidence),
        families=families_from_trace(item.reasons, flagged=item.flagged),
        review_reasons=review_reasons_for(
            risk=item.risk,
            band=item.band,
            thresholds=thresholds,
            flagged=item.flagged,
            explained=bool(item.spans or item.reasons),
            rule_score=item.rule_risk,
            model_score=item.model_risk,
        ),
        versions=_versions(guard, batch),
    )


def _manifest(tool: ToolAssessment, guard: SentinelGuard, batch: str) -> ScanRecord:
    trace = [reason for field in tool.fields for reason in field.get("reasons", [])]
    reasons = []
    if tool.drift in ("changed", "added"):
        reasons.append(f"declaration {tool.drift} since approval: confirm the change was intended")
    if tool.flagged and not trace:
        reasons.append("tool metadata flagged with no rule reason to check the call against")
    return ScanRecord(
        kind="manifest",
        source=tool.source,
        server=tool.server,
        tool=tool.tool,
        channel="tool_metadata",
        text=tool.live_declaration,
        risk=tool.risk,
        band=tool.band,
        detector=guard.detector,
        decided_by="quarantined" if tool.quarantined else "trusted",
        flagged=tool.quarantined,
        rule_trace=trace[:12],
        families=families_from_trace(trace, flagged=tool.flagged),
        drift=tool.drift,
        action_class=tool.category,
        review_reasons=reasons,
        versions=_versions(guard, batch),
    )


def _action(row: dict[str, Any], guard: SentinelGuard, source: str | None, batch: str) -> ScanRecord:
    return ScanRecord(
        kind="action",
        source=source,
        tool=row["tool"],
        detector=guard.detector,
        flagged=row["outcome"] not in _PERMITTING,
        action_tool=row["tool"],
        action_class=row["category"],
        decision=row["outcome"],
        decision_reasons=[str(reason) for reason in row.get("reasons", [])],
        versions=_versions(guard, batch),
    )


def record_comparison(
    store: ScanStore,
    *,
    guard: SentinelGuard,
    question: str,
    assessments: list[ChunkAssessment],
    tools: list[ToolAssessment],
    guarded: dict[str, Any],
) -> dict[str, Any]:
    """Write one comparison to the history and return what was recorded."""

    batch = uuid.uuid4().hex
    try:
        records = [_content(item, guard, question, batch) for item in assessments]
        records += [_manifest(tool, guard, batch) for tool in tools]
        if guarded.get("ok"):
            records += [_action(row, guard, "studio guarded run", batch) for row in guarded.get("actions", [])]
        saved = store.add_many(records)
    except Exception as exc:  # recording must never break a comparison
        return {"recorded": 0, "error": f"history not recorded ({exc.__class__.__name__}: {exc})"}
    return {
        "recorded": len(saved),
        "batch": batch,
        "queued": sum(bool(record.review_reasons) for record in saved),
        "scan_ids": [record.scan_id for record in saved],
    }
