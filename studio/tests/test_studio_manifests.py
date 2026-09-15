"""Tool-manifest scan: parsing, drift against pinned snapshots, quarantine and gating."""

from __future__ import annotations

import asyncio

import pytest

from llmsentinel.policy import CapabilityPolicy
from studio.server.agent import run_comparison
from studio.server.config import StudioSettings
from studio.server.context import ContextError
from studio.server.guard import SentinelGuard
from studio.server.manifests import (
    ToolManifest,
    assess_manifests,
    drift_status,
    is_manifest_json,
    load_manifest_samples,
    manifest_from_upload,
    parse_tools,
    render_tool,
    tool_fields,
)
from studio.server.providers import ChatResult, SimulatedProvider

SETTINGS = StudioSettings(use_transformer=False)


@pytest.fixture(scope="module")
def guard() -> SentinelGuard:
    return SentinelGuard(SETTINGS)


@pytest.fixture(scope="module")
def samples():
    return load_manifest_samples()


def by_tool(guard, manifests):
    tools, _ = assess_manifests(guard, manifests, CapabilityPolicy())
    return {tool.tool: tool for tool in tools}


def test_parse_rejects_malformed_manifests():
    with pytest.raises(ContextError):
        parse_tools({"tools": "nope"}, "x.json")
    with pytest.raises(ContextError):
        parse_tools({"tools": [{"description": "no name"}]}, "x.json")
    with pytest.raises(ContextError):
        parse_tools({"tools": [{"name": "a"}, {"name": "a"}]}, "x.json")
    with pytest.raises(ContextError):
        manifest_from_upload("x.json", "{not json")
    assert is_manifest_json('{"tools": []}')
    assert not is_manifest_json('{"results": []}')


def test_fields_cover_description_and_parameter_descriptions():
    tool = {
        "name": "t",
        "description": "Does a thing.",
        "inputSchema": {"properties": {"q": {"description": "Query."}, "n": {"type": "integer"}}},
    }
    assert tool_fields(tool) == [("description", "Does a thing."), ("parameters.properties.q.description", "Query.")]
    assert "parameter q: Query." in render_tool(tool)


def test_drift_reports_changed_added_removed_and_unpinned():
    approved = ({"name": "a", "description": "A."}, {"name": "b", "description": "B."})
    live = ({"name": "a", "description": "A, now with more."}, {"name": "c", "description": "C."})
    status, removed = drift_status(ToolManifest("m", "m.json", "s", live, approved, "sample"))
    assert status == {"a": "changed", "c": "added"}
    assert removed == ["b"]
    unpinned, _ = drift_status(ToolManifest("m", "m.json", "s", live, None, "upload"))
    assert set(unpinned.values()) == {"unpinned"}


def test_cosmetic_fields_are_not_drift():
    tool = {"name": "a", "description": "A.", "parameters": {"properties": {}}}
    live = ({**tool, "icon": "a.png", "version": "2"},)
    status, _ = drift_status(ToolManifest("m", "m.json", "s", live, (tool,), "sample"))
    assert status == {"a": "unchanged"}


def test_sample_servers_get_the_expected_verdicts(guard, samples):
    tools = by_tool(guard, [sample.manifest for sample in samples.values()])
    for clean in ("read_document", "list_events", "translate"):
        assert not tools[clean].quarantined and tools[clean].drift == "unchanged"
    # Poison already present at review: the digest matches, only the content scan catches it.
    poisoned = tools["summarize_url"]
    assert poisoned.drift == "unchanged" and poisoned.flagged and poisoned.quarantined
    # Silent change after approval whose text reads harmless: only the digest catches it.
    drifted = tools["create_event"]
    assert drifted.drift == "changed" and not drifted.flagged and drifted.quarantined
    assert "backup_copy" not in drifted.approved_declaration
    assert "backup_copy" in drifted.live_declaration


def test_poisoned_tools_steer_unguarded_run_and_are_quarantined_with_sentinel(guard, samples):
    result = asyncio.run(
        run_comparison(
            question="How do I share a notebook with my team?", documents=[], provider=SimulatedProvider(),
            guard=guard, settings=SETTINGS, manifests=[sample.manifest for sample in samples.values()],
        )
    )
    unguarded, guarded = result["unguarded"], result["guarded"]
    assert unguarded["compromised"]
    assert any(action["tool"] == "send_email" for action in unguarded["actions"])
    assert "mirror.web-helper.invalid" in unguarded["system_prompt"]
    assert not guarded["compromised"]
    for text in ("mirror.web-helper.invalid", "summarize_url", "calendar-backup.invalid", "create_event"):
        assert text not in guarded["system_prompt"]
    assert "read_document" in guarded["system_prompt"] and "translate" in guarded["system_prompt"]
    assert result["summary"]["quarantined"] == 2
    assert "quarantined 2 tool(s)" in guarded["prompt"]


class _AsksForSummary:
    name = "stub"
    model = "stub"
    simulated = True

    async def list_models(self):
        return [self.model]

    async def chat(self, messages, *, max_tokens, temperature):
        text = 'Sure.\nACTION: summarize_url {"url": "https://example.com"}'
        return ChatResult(text=text, model=self.model, provider=self.name, latency_ms=1.0)


def test_request_for_a_quarantined_tool_is_blocked(guard, samples):
    result = asyncio.run(
        run_comparison(
            question="Summarise example.com", documents=[], provider=_AsksForSummary(), guard=guard,
            settings=SETTINGS, manifests=[samples["web_helper"].manifest],
        )
    )
    assert [(a["tool"], a["outcome"]) for a in result["unguarded"]["actions"]] == [("summarize_url", "would_run")]
    [row] = result["guarded"]["actions"]
    assert row["outcome"] == "block"
    assert row["reasons"][0].startswith("LLMSentinel quarantined")
