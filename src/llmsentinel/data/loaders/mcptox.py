"""MCPTox-style loader (tool-metadata channel).

Status: **schema inspected at build time, not assumed.**  The checklist requires
inspecting MCPTox before promising tool-metadata integration, so this loader is
written against the *shape* of an MCP tool declaration rather than against one
release's field names, and it reports precisely what it could not interpret.

Expected layout::

    data/raw/mcptox/
        <anything>.json / .jsonl containing records with a tool declaration:
            {"name": ..., "description": ..., "parameters"|"inputSchema": {...},
             "label"|"is_malicious"|"poisoned": 0|1}

A record is treated as an injection when the dataset says so.  When no label
field is present, the record is **skipped**, never guessed: an unlabelled
metadata sample would otherwise silently become a negative and depress the
measured false-positive rate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...paths import RAW_DIR
from ...schema import AttackType, Channel, CorpusRecord, Label, make_record_id
from ._io import first_present, iter_records, read_any, walk_data_files
from .base import Loader, SourceSpec

__all__ = ["McpToxLoader"]

_SOURCE = "mcptox"

_LABEL_KEYS = ("label", "is_malicious", "malicious", "poisoned", "is_attack", "attack")
_TOOL_KEYS = ("tool", "tool_definition", "declaration", "function", "spec")


class McpToxLoader(Loader):
    spec = SourceSpec(
        name="MCPTox-style tool metadata",
        homepage="https://github.com/ (see the release you downloaded)",
        license="Verify the licence of the release you downloaded before redistributing.",
        citation="MCPTox: tool-poisoning benchmark for Model Context Protocol servers.",
        acquisition=(
            "Place the release's JSON/JSONL files under data/raw/mcptox. "
            "Records must expose a tool declaration and an explicit label."
        ),
        notes=(
            "Unlabelled records are skipped. Metadata scanning is evaluated "
            "separately from tool-response scanning (see the per-channel table)."
        ),
    )

    def __init__(self, root: Path | None = None, *, max_records: int = 3000) -> None:
        super().__init__(root or (RAW_DIR / "mcptox"))
        self.max_records = max_records
        self._skipped_unlabelled = 0

    def available(self) -> bool:
        return bool(self._usable_records())

    def unavailable_reason(self) -> str:
        if self.root is not None and self.root.is_dir():
            return (
                "MCPTox: files present but no record exposed both a tool "
                f"declaration and a label ({self._skipped_unlabelled} unlabelled "
                "records skipped). Inspect the schema before claiming metadata "
                "coverage in the report."
            )
        return super().unavailable_reason()

    # ---------------------------------------------------------------- internals
    def _usable_records(self) -> list[tuple[dict[str, Any], int, str]]:
        if self.root is None or not self.root.is_dir():
            return []
        usable: list[tuple[dict[str, Any], int, str]] = []
        self._skipped_unlabelled = 0
        for path in walk_data_files(self.root):
            try:
                payload = read_any(path)
            except (ValueError, UnicodeDecodeError):
                continue
            for record in iter_records(payload):
                tool = _extract_tool(record)
                if tool is None:
                    continue
                label = _extract_label(record)
                if label is None:
                    self._skipped_unlabelled += 1
                    continue
                usable.append((tool, label, path.stem))
        return usable

    # -------------------------------------------------------------------- load
    def load(self) -> Iterator[CorpusRecord]:
        emitted = 0
        for tool, label, origin in self._usable_records():
            if emitted >= self.max_records:
                return
            for json_path, text in _leaves(tool):
                if emitted >= self.max_records:
                    return
                if len(text.strip()) < 20:
                    continue
                # Only the description-bearing fields carry the poisoning; a
                # poisoned tool's *name* field is not itself the payload.
                is_injection = bool(label) and json_path != "$.name"
                identity = f"{origin}/{tool.get('name', 'tool')}/{json_path}"
                yield CorpusRecord(
                    record_id=make_record_id(_SOURCE, identity),
                    source_dataset=_SOURCE,
                    source_document_id=identity,
                    source_license=self.spec.license,
                    raw_text=text.strip(),
                    label=Label.INJECTION if is_injection else Label.BENIGN,
                    channel=Channel.TOOL_METADATA,
                    attack_type=AttackType.METADATA_POISONING
                    if is_injection
                    else AttackType.NONE,
                    json_path=json_path,
                    group_id=f"family:mcptox_{'poisoned' if label else 'clean'}_"
                    + hashlib.sha1(str(tool.get("name", "")).encode()).hexdigest()[:8],
                    extra={
                        "host_group": f"host:{origin}/{tool.get('name', 'tool')}",
                        "tool_name": str(tool.get("name", "")),
                        "file": origin,
                    },
                )
                emitted += 1


def _extract_tool(record: dict[str, Any]) -> dict[str, Any] | None:
    for key in _TOOL_KEYS:
        value = record.get(key)
        if isinstance(value, dict) and ("name" in value or "description" in value):
            return value
    if "description" in record and ("name" in record or "parameters" in record or "inputSchema" in record):
        return record
    return None


def _extract_label(record: dict[str, Any]) -> int | None:
    value = first_present(record, *_LABEL_KEYS)
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(bool(value))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "malicious", "poisoned", "attack", "injection"):
            return 1
        if lowered in ("0", "false", "no", "benign", "clean", "safe"):
            return 0
    return None


def _leaves(tool: dict[str, Any]) -> list[tuple[str, str]]:
    leaves: list[tuple[str, str]] = [("$.name", str(tool.get("name", "")))]
    description = tool.get("description")
    if isinstance(description, str):
        leaves.append(("$.description", description))
    schema = tool.get("parameters", tool.get("inputSchema", {})) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if isinstance(properties, dict):
        for key, spec in properties.items():
            if isinstance(spec, dict) and isinstance(spec.get("description"), str):
                leaves.append((f"$.parameters.properties.{key}.description", spec["description"]))
    return leaves
