"""Tool manifests from connected MCP servers: parsing, scanning and drift.

An agent reads every connected server's tool names, descriptions and parameter
descriptions *before* it sees any user request, usually straight into its system
prompt. Tool metadata is therefore untrusted input, the same as a retrieved page.

Two independent checks, both built on the core package:

* **content** -- every description field is scored by the same ``SentinelGuard``
  used for documents, on the ``tool_metadata`` channel. Fields are scored without
  the user's question, so a tool's verdict does not change from question to question;
* **drift** -- each tool's security-relevant declaration (name, description,
  parameter schema) is hashed with ``llmsentinel.rules.manifest_hash`` and compared
  with the digest pinned from the snapshot approved at review (``diff_manifest``).
  A changed or new tool is reported however harmless its new text reads.

A tool is **quarantined** when a field is flagged or its declaration drifted: it is
left out of the guarded run's tool list and any request for it is blocked. Tools
are quarantined by name, so a clean tool that shares a name with a quarantined one
(tool shadowing) is withheld too. Nothing is ever executed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from llmsentinel.policy import CapabilityPolicy, ProposedAction
from llmsentinel.rules import ManifestPin, diff_manifest, manifest_hash
from llmsentinel.verdict import RiskBand

from .config import MAX_FILE_BYTES, MAX_TOOLS, SAMPLES_DIR
from .context import Chunk, ContextError
from .guard import ChunkAssessment, SentinelGuard, max_band

__all__ = [
    "ManifestSample",
    "ToolAssessment",
    "ToolManifest",
    "assess_manifests",
    "drift_status",
    "is_manifest_json",
    "load_manifest_samples",
    "manifest_from_upload",
    "parse_tools",
    "render_tool",
    "tool_fields",
]


@dataclass(frozen=True, slots=True)
class ToolManifest:
    manifest_id: str
    name: str  # file name
    server: str
    tools: tuple[dict[str, Any], ...]
    #: The snapshot approved at review; ``None`` when the server was never pinned.
    approved: tuple[dict[str, Any], ...] | None
    origin: str  # "sample" | "upload"


@dataclass(frozen=True, slots=True)
class ManifestSample:
    manifest: ToolManifest
    label: str
    attack: str
    note: str


def parse_tools(data: Any, name: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        raise ContextError(f'{name}: a tool manifest needs a top-level "tools" list.')
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tool in enumerate(data["tools"]):
        tool_name = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ContextError(f'{name}: tools[{index}] needs a string "name".')
        if tool_name in seen:
            raise ContextError(f"{name}: tool {tool_name!r} is declared twice.")
        seen.add(tool_name)
        tools.append(tool)
    if not tools:
        raise ContextError(f"{name}: the manifest lists no tools.")
    if len(tools) > MAX_TOOLS:
        raise ContextError(f"{name}: more than {MAX_TOOLS} tools.")
    return str(data.get("server") or Path(name).stem), tuple(tools)


def is_manifest_json(content: str) -> bool:
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and isinstance(data.get("tools"), list)


def manifest_from_upload(name: str, content: str) -> ToolManifest:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ContextError(f"{name}: larger than {MAX_FILE_BYTES // 1_000_000} MB.")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ContextError(f"{name}: not valid JSON.") from exc
    server, tools = parse_tools(data, name)
    digest = hashlib.sha1(f"{name}\n{content}".encode()).hexdigest()[:10]
    return ToolManifest(f"manifest-{digest}", Path(name).name, server, tools, None, "upload")


def load_manifest_samples(samples_dir: Path = SAMPLES_DIR) -> dict[str, ManifestSample]:
    pack = yaml.safe_load((samples_dir / "manifest.yaml").read_text(encoding="utf-8"))
    out: dict[str, ManifestSample] = {}
    for item in pack.get("manifests", []) or []:
        path = samples_dir / item["file"]
        server, tools = parse_tools(json.loads(path.read_text(encoding="utf-8")), path.name)
        approved = None
        if item.get("approved"):
            approved_path = samples_dir / item["approved"]
            _, approved = parse_tools(json.loads(approved_path.read_text(encoding="utf-8")), approved_path.name)
        manifest_id = str(item["id"])
        out[manifest_id] = ManifestSample(
            manifest=ToolManifest(manifest_id, path.name, server, tools, approved, "sample"),
            label=str(item.get("label", "unknown")),
            attack=str(item.get("attack", "none")),
            note=str(item.get("note", "")).strip(),
        )
    return out


def _schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("parameters", tool.get("inputSchema", {})) or {}
    return schema if isinstance(schema, dict) else {}


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    properties = _schema(tool).get("properties", {})
    return properties if isinstance(properties, dict) else {}


def tool_fields(tool: dict[str, Any]) -> list[tuple[str, str]]:
    """``(path within the tool, text)`` for every field the model reads as prose."""

    fields = [("description", str(tool.get("description") or ""))]
    for key, spec in _properties(tool).items():
        if isinstance(spec, dict) and str(spec.get("description") or "").strip():
            fields.append((f"parameters.properties.{key}.description", str(spec["description"])))
    return [(path, text) for path, text in fields if text.strip()]


def render_tool(tool: dict[str, Any]) -> str:
    """How a tool appears in the system prompt: its description and parameters."""

    lines = [f"- {tool.get('name')}: {' '.join(str(tool.get('description') or '').split())}"]
    for key, spec in _properties(tool).items():
        description = spec.get("description") if isinstance(spec, dict) else ""
        if description:
            lines.append(f"    parameter {key}: {' '.join(str(description).split())}")
    return "\n".join(lines)


def drift_status(manifest: ToolManifest) -> tuple[dict[str, str], list[str]]:
    """Per-tool ``unchanged | changed | added | unpinned``, plus tools removed since approval."""

    if manifest.approved is None:
        return {str(t["name"]): "unpinned" for t in manifest.tools}, []
    pins = [ManifestPin.from_tool(tool) for tool in manifest.approved]
    diff = diff_manifest(list(manifest.tools), pins)
    status = dict.fromkeys(diff.unchanged, "unchanged")
    status.update(dict.fromkeys(diff.changed, "changed"))
    status.update(dict.fromkeys(diff.added, "added"))
    return status, list(diff.removed)


def _declaration(tool: dict[str, Any]) -> str:
    relevant = {"name": tool.get("name", ""), "description": tool.get("description", ""), "parameters": _schema(tool)}
    return json.dumps(relevant, indent=2, ensure_ascii=False)


@dataclass(slots=True)
class ToolAssessment:
    manifest_id: str
    source: str
    server: str
    tool: str
    category: str
    unknown_tool: bool
    drift: str
    live_digest: str
    approved_digest: str | None
    flagged: bool
    risk: float
    band: str
    quarantined: bool
    reasons: list[str] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    live_declaration: str = ""
    approved_declaration: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_manifests(
    guard: SentinelGuard, manifests: Sequence[ToolManifest], policy: CapabilityPolicy
) -> tuple[list[ToolAssessment], list[dict[str, Any]]]:
    owners: list[tuple[int, int]] = []
    chunks: list[Chunk] = []
    for mi, manifest in enumerate(manifests):
        for ti, tool in enumerate(manifest.tools):
            for fi, (path, text) in enumerate(tool_fields(tool)):
                chunks.append(
                    Chunk(f"{manifest.manifest_id}#{ti}.{fi}", manifest.manifest_id, manifest.name,
                          "tool_metadata", f"$.tools[{ti}].{path}", text, fi)
                )
                owners.append((mi, ti))
    scored = guard.assess([(chunk, 1.0) for chunk in chunks], "", isolate=False) if chunks else []
    per_tool: dict[tuple[int, int], list[ChunkAssessment]] = {}
    for owner, assessment in zip(owners, scored, strict=True):
        per_tool.setdefault(owner, []).append(assessment)

    results: list[ToolAssessment] = []
    servers: list[dict[str, Any]] = []
    for mi, manifest in enumerate(manifests):
        status, removed = drift_status(manifest)
        approved = {str(tool["name"]): tool for tool in manifest.approved or ()}
        for ti, tool in enumerate(manifest.tools):
            name = str(tool["name"])
            fields = per_tool.get((mi, ti), [])
            flagged = any(a.flagged for a in fields)
            drift = status[name]
            category, unknown = policy.categorise(ProposedAction(tool_name=name))

            reasons = [
                f"{a.json_path}: flagged by {a.decided_by} (risk {a.risk:.3f})" for a in fields if a.flagged
            ]
            if drift == "changed":
                reasons.append("declaration changed after approval: live digest differs from the pinned digest")
            elif drift == "added":
                reasons.append("tool is not in this server's approved snapshot")
            quarantined = flagged or drift in ("changed", "added")
            if not quarantined:
                reasons.append("description fields scanned clean")
                reasons.append(
                    "digest matches the approved snapshot" if drift == "unchanged"
                    else "no approved snapshot for this server: content scan only"
                )

            pinned_tool = approved.get(name)
            results.append(
                ToolAssessment(
                    manifest_id=manifest.manifest_id,
                    source=manifest.name,
                    server=manifest.server,
                    tool=name,
                    category=category.value,
                    unknown_tool=unknown,
                    drift=drift,
                    live_digest=manifest_hash(tool)[:16],
                    approved_digest=manifest_hash(pinned_tool)[:16] if pinned_tool else None,
                    flagged=flagged,
                    risk=max((a.risk for a in fields), default=0.0),
                    band=max_band(RiskBand.LOW, *(a.band for a in fields)),
                    quarantined=quarantined,
                    reasons=reasons,
                    fields=[
                        {
                            "path": a.json_path, "text": a.text, "risk": a.risk, "band": a.band,
                            "flagged": a.flagged, "decided_by": a.decided_by, "rule_risk": a.rule_risk,
                            "model_risk": a.model_risk, "spans": a.spans, "reasons": a.reasons,
                        }
                        for a in fields
                    ],
                    live_declaration=_declaration(tool),
                    approved_declaration=_declaration(pinned_tool) if pinned_tool and drift == "changed" else None,
                )
            )
        servers.append(
            {
                "manifest_id": manifest.manifest_id,
                "server": manifest.server,
                "source": manifest.name,
                "pinned": manifest.approved is not None,
                "tools": len(manifest.tools),
                "removed": removed,
            }
        )
    return results, servers
