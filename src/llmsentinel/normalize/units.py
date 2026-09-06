"""The unit of analysis: one provenance-tagged string ready for scoring.

A RAG document produces a single unit.  A tool response produces one unit per
string leaf, each carrying its JSON path.  A decoded base64 blob produces a
*derived* unit whose parent pointer records where it came from, so a verdict can
always answer "which bytes of the original input caused this?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import NORMALISATION_VERSION
from ..schema import Channel, Span
from .evidence import Evidence
from .offsets import OffsetMap

__all__ = ["DerivedSegment", "NormalizedUnit", "Sentence"]


@dataclass(frozen=True, slots=True)
class Sentence:
    """A candidate sentence with offsets into the normalised text of its unit."""

    index: int
    text: str
    start: int
    end: int

    def span(self, field_name: str = "normalized_text") -> Span:
        return Span(self.start, self.end, field=field_name)


@dataclass(frozen=True, slots=True)
class DerivedSegment:
    """Text recovered from an encoded region of a parent unit."""

    kind: str
    text: str
    #: Span of the *encoded* region inside the parent unit's raw text.
    source_span: Span
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "source_span": self.source_span.to_dict(),
            "detail": self.detail,
        }


@dataclass(slots=True)
class NormalizedUnit:
    """One analysable string plus everything learned while cleaning it."""

    unit_id: str
    raw_text: str
    normalized_text: str
    offset_map: OffsetMap
    channel: Channel = Channel.UNKNOWN
    #: JSON path such as ``$.results[0].content`` for tool responses.
    json_path: str | None = None
    #: Set when this unit was recovered from an encoded region of another unit.
    parent_unit_id: str | None = None
    parent_span: Span | None = None
    evidence: list[Evidence] = field(default_factory=list)
    derived: list[DerivedSegment] = field(default_factory=list)
    normalisation_version: str = NORMALISATION_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ views
    @property
    def is_derived(self) -> bool:
        return self.parent_unit_id is not None

    @property
    def provenance(self) -> str:
        """Short human-readable origin, shown in the demo and in verdicts."""

        base = self.json_path or self.channel.value
        if self.parent_unit_id and self.parent_span:
            return f"{base} <- decoded [{self.parent_span.start}:{self.parent_span.end}]"
        return base

    def to_raw_span(self, start: int, end: int, note: str | None = None) -> Span:
        """Project a span found on the normalised text back onto the raw text."""

        raw_start, raw_end = self.offset_map.map_span(start, end)
        return Span(raw_start, raw_end, field="raw_text", note=note)

    def evidence_kinds(self) -> set[str]:
        return {item.kind for item in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "channel": self.channel.value,
            "json_path": self.json_path,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "parent_unit_id": self.parent_unit_id,
            "parent_span": self.parent_span.to_dict() if self.parent_span else None,
            "evidence": [item.to_dict() for item in self.evidence],
            "derived": [item.to_dict() for item in self.derived],
            "normalisation_version": self.normalisation_version,
            "metadata": self.metadata,
        }
