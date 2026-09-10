"""Loader for the hand-written contrastive cases in ``data/semantic/``.

These fixtures exist to probe the semantic layer's honesty, not to report
benchmark performance: they are small, curated, and separate from the corpus.
Each case pairs a host task with an untrusted text and a label, so a detector
can be checked on the disagreements that lexical matching gets wrong — an attack
that reuses the task's words (should fire) versus a benign instruction that is
merely off-topic (should not).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..paths import DATA_DIR
from ..schema import Channel, CorpusRecord, Label, make_record_id

__all__ = [
    "CONTRASTIVE_PATH",
    "MULTICHUNK_PATH",
    "ContrastiveCase",
    "MultiChunkCase",
    "load_contrastive_cases",
    "load_multichunk_cases",
]

CONTRASTIVE_PATH = DATA_DIR / "semantic" / "contrastive_cases.yaml"
MULTICHUNK_PATH = DATA_DIR / "semantic" / "multichunk_cases.yaml"


@dataclass(frozen=True, slots=True)
class ContrastiveCase:
    """One host-task / untrusted-text / label triple with its rationale."""

    case_id: str
    category: str
    host_task: str
    text: str
    label: Label
    channel: Channel
    note: str
    json_path: str | None = None

    def as_record(self) -> CorpusRecord:
        """A corpus record usable by any scorer. Injection cases get a generic
        attack type so the schema's benign/positive invariants hold."""

        from ..schema import AttackType

        # tool_metadata records must carry a JSON path; default to the field a
        # manifest injection usually hides in.
        json_path = self.json_path
        if json_path is None and self.channel is Channel.TOOL_METADATA:
            json_path = "$.description"

        return CorpusRecord(
            record_id=make_record_id("semantic", self.case_id),
            source_dataset="semantic",
            source_document_id=self.case_id,
            source_license="CC0-1.0",
            raw_text=self.text,
            label=self.label,
            channel=self.channel,
            attack_type=AttackType.UNKNOWN if self.label is Label.INJECTION else AttackType.NONE,
            host_task=self.host_task,
            json_path=json_path,
            extra={"category": self.category, "note": self.note},
        )


@dataclass(frozen=True, slots=True)
class MultiChunkCase:
    """An ordered retrieval bundle and whether it should assemble into an attack."""

    case_id: str
    host_task: str
    chunks: tuple[tuple[str, str], ...]  # (source, text) in retrieval order
    expect_assembly: bool
    note: str


def load_contrastive_cases(path: str | Path | None = None) -> list[ContrastiveCase]:
    source = Path(path) if path else CONTRASTIVE_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return list(_parse(payload))


def load_multichunk_cases(path: str | Path | None = None) -> list[MultiChunkCase]:
    source = Path(path) if path else MULTICHUNK_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    cases = []
    for raw in payload.get("bundles", []):
        cases.append(
            MultiChunkCase(
                case_id=str(raw["id"]),
                host_task=str(raw["host_task"]),
                chunks=tuple((str(c["source"]), str(c["text"]).strip()) for c in raw["chunks"]),
                expect_assembly=bool(raw["expect_assembly"]),
                note=str(raw.get("note", "")),
            )
        )
    return cases


def _parse(payload: dict) -> Iterator[ContrastiveCase]:
    for raw in payload.get("cases", []):
        yield ContrastiveCase(
            case_id=str(raw["id"]),
            category=str(raw["category"]),
            host_task=str(raw["host_task"]),
            text=str(raw["text"]).strip(),
            label=Label.coerce(raw["label"]),
            channel=Channel.coerce(raw.get("channel", "rag_document")),
            note=str(raw.get("note", "")),
            json_path=raw.get("json_path"),
        )
