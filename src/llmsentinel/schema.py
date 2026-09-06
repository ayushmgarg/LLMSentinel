"""Unified corpus schema.

Every example from every source dataset is converted into a single
:class:`CorpusRecord` and stored as one JSON object per line (JSONL).  The
schema is frozen: loaders may not invent fields, and downstream code may not
depend on anything outside this module.

Field conventions
-----------------
* Required fields are always present and never ``null``.
* Optional *scalar* fields (``host_task``, ``json_path``, ``split`` ...) are
  ``null`` when the source does not provide them.
* Optional *categorical* fields use their ``unknown`` enum member rather than
  ``null`` so that grouping and counting never silently drop records.
* Lists default to ``[]``, never ``null``.
* ``extra`` carries loader-specific provenance that has no schema field.  It is
  never read by models -- it exists so that a record can be traced back to its
  origin during manual inspection.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .constants import CORPUS_SCHEMA_VERSION, UNKNOWN

__all__ = [
    "AttackType",
    "Channel",
    "CorpusRecord",
    "Label",
    "SchemaError",
    "Span",
    "Split",
    "count_by",
    "iter_jsonl",
    "make_record_id",
    "read_jsonl",
    "write_jsonl",
]


class SchemaError(ValueError):
    """Raised when a record violates the frozen corpus schema."""


class _StrEnum(str, Enum):
    """String enum whose members serialise as plain strings."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def coerce(cls, value: Any) -> _StrEnum:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError as exc:
                raise SchemaError(
                    f"{cls.__name__}: {value!r} is not one of "
                    f"{[m.value for m in cls]}"
                ) from exc
        raise SchemaError(f"{cls.__name__}: expected str, got {type(value).__name__}")


class Channel(_StrEnum):
    """Where the untrusted text reached the agent from.

    The channel is *provenance*, not content: the same sentence is scored
    differently depending on whether it arrived in a retrieved document, in a
    tool result, or in a tool's own advertised metadata.
    """

    RAG_DOCUMENT = "rag_document"
    TOOL_RESPONSE = "tool_response"
    TOOL_METADATA = "tool_metadata"
    UNKNOWN = "unknown"


class Label(int, Enum):
    """Binary target.

    ``INJECTION`` means the text contains assistant-directed control content
    that conflicts with the host task.  Merely *discussing* prompt injection is
    ``BENIGN`` -- see ``docs/annotation_guideline.md``.
    """

    BENIGN = 0
    INJECTION = 1

    def __int__(self) -> int:  # pragma: no cover - trivial
        return int(self.value)

    @classmethod
    def coerce(cls, value: Any) -> Label:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            return cls(int(value))
        if isinstance(value, int):
            if value in (0, 1):
                return cls(value)
            raise SchemaError(f"label must be 0 or 1, got {value}")
        if isinstance(value, str):
            key = value.strip().lower()
            if key in ("0", "benign", "clean", "negative"):
                return cls.BENIGN
            if key in ("1", "injection", "attack", "positive", "malicious"):
                return cls.INJECTION
        raise SchemaError(f"cannot interpret {value!r} as a label")


class AttackType(_StrEnum):
    """Coarse family of the injected instruction, used for per-type recall.

    Benign records use :attr:`NONE`.  Positive records whose source dataset does
    not expose a usable taxonomy use :attr:`UNKNOWN` so that they are still
    counted, but excluded from per-type claims.
    """

    NONE = "none"
    #: "ignore previous instructions", role reassignment, fake system messages
    META_INSTRUCTION = "meta_instruction"
    #: send / post / email data to an attacker-controlled destination
    EXFILTRATION = "exfiltration"
    #: cause a state-changing or destructive tool call
    ACTION_HIJACK = "action_hijack"
    #: zero-width characters, homoglyphs, base64/hex payloads, hidden markup
    OBFUSCATION = "obfuscation"
    #: steer the answer content (ads, phishing links, misinformation)
    CONTENT_MANIPULATION = "content_manipulation"
    #: poisoned tool name / description / parameter schema
    METADATA_POISONING = "metadata_poisoning"
    UNKNOWN = "unknown"


class Split(_StrEnum):
    TRAIN = "train"
    DEV = "dev"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class Span:
    """Half-open character interval ``[start, end)`` into a specific text.

    ``field`` records *which* string the offsets index, because a record carries
    both a raw and a normalised text whose offsets generally differ.
    """

    start: int
    end: int
    field: str = "raw_text"
    note: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < 0:
            raise SchemaError(f"negative span offsets: {self}")
        if self.end < self.start:
            raise SchemaError(f"span end before start: {self}")

    def __len__(self) -> int:
        return self.end - self.start

    def slice(self, text: str) -> str:
        return text[self.start : self.end]

    def overlaps(self, other: Span) -> bool:
        if self.field != other.field:
            return False
        return self.start < other.end and other.start < self.end

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "field": self.field, "note": self.note}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Span:
        return cls(
            start=int(payload["start"]),
            end=int(payload["end"]),
            field=str(payload.get("field", "raw_text")),
            note=payload.get("note"),
        )


def make_record_id(source_dataset: str, local_key: str) -> str:
    """Build a stable, collision-resistant record id.

    The id is a pure function of the source dataset and a key that is stable
    inside that dataset, so rebuilding the corpus from the same inputs yields
    the same ids and previously logged experiments stay addressable.
    """

    digest = hashlib.sha1(f"{source_dataset}::{local_key}".encode()).hexdigest()[:16]
    return f"{source_dataset}-{digest}"


@dataclass(slots=True)
class CorpusRecord:
    """One labelled unit of untrusted text with full provenance."""

    # --- identity -----------------------------------------------------------
    record_id: str
    source_dataset: str
    source_document_id: str
    source_license: str

    # --- content ------------------------------------------------------------
    raw_text: str
    label: Label
    channel: Channel

    # --- normalisation ------------------------------------------------------
    #: Filled by ``llmsentinel.normalize``; ``None`` until the record is
    #: normalised.  ``normalisation_version`` records which implementation
    #: produced it so stale caches are detectable.
    normalized_text: str | None = None
    normalisation_version: str | None = None

    # --- attack description -------------------------------------------------
    attack_type: AttackType = AttackType.NONE
    injected_spans: list[Span] = field(default_factory=list)

    # --- context ------------------------------------------------------------
    host_task: str | None = None
    json_path: str | None = None

    # --- corpus bookkeeping -------------------------------------------------
    #: Grouping key for leakage-free splitting: every record that shares a
    #: payload template or a host document must share this key.
    group_id: str = UNKNOWN
    #: Benign records that are *designed* to look like attacks (security
    #: articles, documentation, policies, legitimate imperatives).
    is_hard_negative: bool = False
    split: Split | None = None
    schema_version: str = CORPUS_SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ init
    def __post_init__(self) -> None:
        self.label = Label.coerce(self.label)
        self.channel = Channel.coerce(self.channel)
        self.attack_type = AttackType.coerce(self.attack_type)
        if self.split is not None:
            self.split = Split.coerce(self.split)
        self.injected_spans = [
            s if isinstance(s, Span) else Span.from_dict(s) for s in self.injected_spans
        ]
        self.validate()

    # ------------------------------------------------------------ validation
    def validate(self) -> None:
        """Enforce the invariants the rest of the pipeline relies on."""

        for name in ("record_id", "source_dataset", "source_document_id", "source_license"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SchemaError(f"{self.record_id!r}: field {name!r} must be a non-empty string")

        if not isinstance(self.raw_text, str) or not self.raw_text.strip():
            raise SchemaError(f"{self.record_id!r}: raw_text must be non-empty")

        if self.label is Label.BENIGN:
            if self.attack_type is not AttackType.NONE:
                raise SchemaError(
                    f"{self.record_id!r}: benign record must have attack_type 'none', "
                    f"got {self.attack_type}"
                )
            if self.injected_spans:
                raise SchemaError(f"{self.record_id!r}: benign record must not carry spans")
        else:
            if self.attack_type is AttackType.NONE:
                raise SchemaError(
                    f"{self.record_id!r}: injection record needs a real attack_type "
                    f"(use 'unknown' when the source does not say)"
                )
            if self.is_hard_negative:
                raise SchemaError(f"{self.record_id!r}: hard negatives must be benign")

        for span in self.injected_spans:
            text = self.text_for_field(span.field)
            if text is None:
                raise SchemaError(f"{self.record_id!r}: span references unset field {span.field!r}")
            if span.end > len(text):
                raise SchemaError(
                    f"{self.record_id!r}: span {span} exceeds {span.field} length {len(text)}"
                )

        if self.channel is Channel.TOOL_METADATA and self.json_path is None:
            raise SchemaError(f"{self.record_id!r}: tool_metadata records require a json_path")

        if self.normalized_text is not None and self.normalisation_version is None:
            raise SchemaError(f"{self.record_id!r}: normalized_text set without a version")

    # -------------------------------------------------------------- helpers
    def text_for_field(self, name: str) -> str | None:
        if name == "raw_text":
            return self.raw_text
        if name == "normalized_text":
            return self.normalized_text
        return None

    @property
    def text(self) -> str:
        """Preferred text for modelling: normalised when available."""

        return self.normalized_text if self.normalized_text is not None else self.raw_text

    @property
    def y(self) -> int:
        return int(self.label.value)

    def with_split(self, split: Split | str) -> CorpusRecord:
        self.split = Split.coerce(split)
        return self

    # ------------------------------------------------------------------- I/O
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["label"] = int(self.label.value)
        payload["channel"] = self.channel.value
        payload["attack_type"] = self.attack_type.value
        payload["split"] = self.split.value if self.split is not None else None
        payload["injected_spans"] = [s.to_dict() for s in self.injected_spans]
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusRecord:
        unknown = set(payload) - _FIELD_NAMES
        if unknown:
            raise SchemaError(f"unknown schema fields: {sorted(unknown)}")
        kwargs = {k: v for k, v in payload.items() if k in _FIELD_NAMES}
        kwargs.setdefault("schema_version", CORPUS_SCHEMA_VERSION)
        if kwargs.get("schema_version") != CORPUS_SCHEMA_VERSION:
            raise SchemaError(
                f"record {payload.get('record_id')!r} was written with schema "
                f"{kwargs.get('schema_version')!r}; this build expects "
                f"{CORPUS_SCHEMA_VERSION!r}. Rebuild the corpus."
            )
        return cls(**kwargs)

    @classmethod
    def from_json(cls, line: str) -> CorpusRecord:
        return cls.from_dict(json.loads(line))


_FIELD_NAMES = set(CorpusRecord.__dataclass_fields__)


# --------------------------------------------------------------------- JSONL
def write_jsonl(records: Iterable[CorpusRecord], path: str | Path) -> int:
    """Write records to ``path`` (parents created).  Returns the count."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.to_json())
            handle.write("\n")
            written += 1
    return written


def iter_jsonl(path: str | Path) -> Iterator[CorpusRecord]:
    """Stream records from a JSONL file, reporting the offending line number."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield CorpusRecord.from_json(line)
            except (SchemaError, json.JSONDecodeError) as exc:
                raise SchemaError(f"{path}:{lineno}: {exc}") from exc


def read_jsonl(path: str | Path) -> list[CorpusRecord]:
    return list(iter_jsonl(path))


def count_by(records: Sequence[CorpusRecord], *keys: str) -> dict[tuple[Any, ...], int]:
    """Count records grouped by attribute names, for corpus cards and sanity checks."""

    counts: dict[tuple[Any, ...], int] = {}
    for record in records:
        key = tuple(_display(getattr(record, k)) for k in keys)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: tuple(map(str, kv[0]))))


def _display(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value
