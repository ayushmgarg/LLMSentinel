"""The normalisation pipeline: raw untrusted input to scoreable units.

Order matters and is fixed:

1. strip invisible / control characters (they break every later regex),
2. decode HTML entities once (``&#105;gnore`` -> ``ignore``),
3. NFKC per grapheme cluster (fullwidth and ligature forms collapse),
4. collapse redundant whitespace (``i g n o r e`` padding, tab soup),
5. detect concealment that must *not* be rewritten (hidden markup, homoglyphs),
6. decode embedded payloads into child units.

Steps 1-4 rewrite text and contribute to a single composed
:class:`~llmsentinel.normalize.offsets.OffsetMap`, so any span found downstream
projects back onto the exact raw characters.  Steps 5-6 only add evidence and
derived units.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Final

from ..constants import NORMALISATION_VERSION
from ..schema import Channel, CorpusRecord, Span
from .encoding import decode_embedded_payloads
from .evidence import Evidence
from .json_leaves import JsonLeaf, extract_string_leaves, parse_json_safely
from .markup import decode_entities, detect_hidden_markup
from .offsets import OffsetMap
from .segment import segment_sentences
from .unicode_ops import detect_script_confusion, nfkc_normalise, strip_invisibles
from .units import DerivedSegment, NormalizedUnit, Sentence

__all__ = ["NormalizationConfig", "Normalizer"]

_SPACE_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[ \t\f\v ]{2,}")


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    """Knobs that change normalisation output.

    Any change here must bump :data:`llmsentinel.constants.NORMALISATION_VERSION`
    because cached ``normalized_text`` values would otherwise be stale.
    """

    decode_encodings: bool = True
    detect_homoglyphs: bool = True
    detect_markup: bool = True
    collapse_whitespace: bool = True
    use_spacy: bool = False
    #: Minimum string length for a JSON leaf to become its own unit.
    min_leaf_chars: int = 12
    #: Object keys become units too (used for tool-metadata scanning).
    include_json_keys: bool = False


class Normalizer:
    """Turns raw input of any supported channel into :class:`NormalizedUnit` objects."""

    version = NORMALISATION_VERSION

    def __init__(self, config: NormalizationConfig | None = None) -> None:
        self.config = config or NormalizationConfig()

    # ------------------------------------------------------------------ text
    def normalize_text(
        self,
        text: str,
        *,
        channel: Channel | str = Channel.RAG_DOCUMENT,
        json_path: str | None = None,
        unit_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        _allow_derived: bool = True,
    ) -> NormalizedUnit:
        """Normalise a single string and collect its evidence."""

        channel = Channel.coerce(channel)
        working = text
        composed = OffsetMap.identity(len(text))
        evidence: list[Evidence] = []

        cleaned, step_map, step_evidence = strip_invisibles(working)
        evidence.extend(step_evidence)  # spans already index the raw text
        working, composed = cleaned, step_map

        cleaned, step_map, step_evidence = decode_entities(working)
        evidence.extend(_remap(step_evidence, composed))
        working, composed = cleaned, step_map.compose(composed)

        cleaned, step_map, step_evidence = nfkc_normalise(working)
        evidence.extend(_remap(step_evidence, composed))
        working, composed = cleaned, step_map.compose(composed)

        if self.config.collapse_whitespace:
            cleaned, step_map = _collapse_whitespace(working)
            working, composed = cleaned, step_map.compose(composed)

        if self.config.detect_markup:
            evidence.extend(detect_hidden_markup(text))
        if self.config.detect_homoglyphs:
            evidence.extend(detect_script_confusion(text))

        derived_segments: list[DerivedSegment] = []
        if self.config.decode_encodings:
            segments, step_evidence = decode_embedded_payloads(working)
            derived_segments = [_remap_segment(seg, composed) for seg in segments]
            evidence.extend(_remap(step_evidence, composed))

        unit = NormalizedUnit(
            unit_id=unit_id or _unit_id(text, json_path),
            raw_text=text,
            normalized_text=working,
            offset_map=composed,
            channel=channel,
            json_path=json_path,
            evidence=_dedupe(evidence),
            derived=derived_segments,
            normalisation_version=self.version,
            metadata=dict(metadata or {}),
        )
        if not _allow_derived:
            unit.derived = []
        return unit

    def derived_units(self, unit: NormalizedUnit) -> list[NormalizedUnit]:
        """Normalise every decoded payload of ``unit`` into its own child unit.

        Children never spawn grandchildren: one level of decoding is enough for
        the attacks in scope and it makes the cost of a hostile input bounded.
        """

        children: list[NormalizedUnit] = []
        for index, segment in enumerate(unit.derived):
            child = self.normalize_text(
                segment.text,
                channel=unit.channel,
                json_path=(
                    f"{unit.json_path}~{segment.kind}" if unit.json_path else f"~{segment.kind}"
                ),
                unit_id=f"{unit.unit_id}#d{index}",
                metadata={"derived_kind": segment.kind},
                _allow_derived=False,
            )
            child.parent_unit_id = unit.unit_id
            child.parent_span = segment.source_span
            children.append(child)
        return children

    # ------------------------------------------------------------------ JSON
    def normalize_json(
        self,
        document: Any,
        *,
        channel: Channel | str = Channel.TOOL_RESPONSE,
        include_keys: bool | None = None,
        root: str = "$",
    ) -> list[NormalizedUnit]:
        """Normalise every string leaf of a parsed JSON document."""

        leaves = extract_string_leaves(
            document,
            root=root,
            include_keys=self.config.include_json_keys if include_keys is None else include_keys,
            min_chars=self.config.min_leaf_chars,
        )
        return [self._unit_from_leaf(leaf, channel) for leaf in leaves]

    def normalize_json_text(
        self,
        raw: str,
        *,
        channel: Channel | str = Channel.TOOL_RESPONSE,
        include_keys: bool | None = None,
    ) -> tuple[list[NormalizedUnit], str | None]:
        """Parse ``raw`` as JSON and normalise its leaves.

        Falls back to treating the input as plain text when it does not parse,
        and returns the parser error so the caller can show it.
        """

        document, error = parse_json_safely(raw)
        if error is not None:
            return [self.normalize_text(raw, channel=channel)], error
        return self.normalize_json(document, channel=channel, include_keys=include_keys), None

    def _unit_from_leaf(self, leaf: JsonLeaf, channel: Channel | str) -> NormalizedUnit:
        unit = self.normalize_text(
            leaf.value,
            channel=channel,
            json_path=leaf.path,
            metadata={
                "from_embedded_json": leaf.from_embedded_json,
                "json_depth": leaf.depth,
            },
        )
        return unit

    # --------------------------------------------------------------- records
    def normalize_record(self, record: CorpusRecord) -> CorpusRecord:
        """Fill ``normalized_text`` / ``normalisation_version`` in place."""

        unit = self.normalize_text(
            record.raw_text,
            channel=record.channel,
            json_path=record.json_path,
            unit_id=record.record_id,
            # The host task is what the record's directive should be consistent
            # with; TaskConflictRule reads it from the unit's metadata.
            metadata={"host_task": record.host_task} if record.host_task else None,
        )
        record.normalized_text = unit.normalized_text
        record.normalisation_version = unit.normalisation_version
        return record

    # ------------------------------------------------------------- sentences
    def sentences(self, unit: NormalizedUnit) -> list[Sentence]:
        return segment_sentences(unit.normalized_text, use_spacy=self.config.use_spacy)


# ----------------------------------------------------------------- internals
def _unit_id(text: str, json_path: str | None) -> str:
    digest = hashlib.sha1(f"{json_path or ''}::{text}".encode()).hexdigest()[:12]
    return f"u-{digest}"


def _remap(evidence: list[Evidence], composed: OffsetMap) -> list[Evidence]:
    """Project evidence spans produced on intermediate text back onto raw text."""

    remapped: list[Evidence] = []
    for item in evidence:
        if item.span is None:
            remapped.append(item)
            continue
        start, end = composed.map_span(item.span.start, item.span.end)
        remapped.append(
            Evidence(
                kind=item.kind,
                detail=item.detail,
                span=Span(start, end, field="raw_text", note=item.span.note),
                payload=item.payload,
            )
        )
    return remapped


def _remap_segment(segment: DerivedSegment, composed: OffsetMap) -> DerivedSegment:
    start, end = composed.map_span(segment.source_span.start, segment.source_span.end)
    return DerivedSegment(
        kind=segment.kind,
        text=segment.text,
        source_span=Span(start, end, field="raw_text", note=segment.source_span.note),
        detail=segment.detail,
    )


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, int, int, str]] = set()
    unique: list[Evidence] = []
    for item in evidence:
        key = (
            item.kind,
            item.span.start if item.span else -1,
            item.span.end if item.span else -1,
            item.detail,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda item: (item.span.start if item.span else 0, item.kind))
    return unique


def _collapse_whitespace(text: str) -> tuple[str, OffsetMap]:
    """Collapse runs of horizontal whitespace to one space, keeping offsets.

    Newlines are preserved: they carry structure that the sentence segmenter and
    the hidden-markup evidence both rely on.
    """

    out: list[str] = []
    indices: list[int] = []
    cursor = 0
    for match in _SPACE_RUN_RE.finditer(text):
        out.append(text[cursor : match.start()])
        indices.extend(range(cursor, match.start()))
        out.append(" ")
        indices.append(match.start())
        cursor = match.end()
    out.append(text[cursor:])
    indices.extend(range(cursor, len(text)))
    return "".join(out), OffsetMap.from_pairs(indices, len(text))
