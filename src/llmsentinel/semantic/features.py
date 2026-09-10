"""Semantic and source-aware features.

Two feature groups, both interpretable and both reported by name:

*Semantic* features ask whether an instruction belongs to the host task and
where it would send the result. The signal that separates a real attack from a
benign off-topic instruction is **not** "is this off-topic" on its own — plenty
of benign text is off-topic — it is off-topic *and* carrying an action with a
destination, a secret, a tool, or an authority claim that the task never asked
for. The extractor exposes those as separate features so a model (or a reader)
can require the corroboration rather than firing on topicality alone.

*Source-aware* features encode provenance: channel, JSON-path class, a coarse
document type, and whether a tool identity is attached. They let the detector
learn that the same sentence is riskier in a tool manifest than in prose, and
they are what the cross-source transfer study in ``scripts/provenance_transfer.py``
switches on and off.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..rules.lexicons import ASSISTANT_ADDRESS_PATTERNS, compile_named
from ..schema import Channel, CorpusRecord
from .representations import (
    TaskContext,
    UntrustedInstruction,
    build_context,
    extract_actions,
)
from .similarity import Embedder, cosine, default_embedder

__all__ = ["SEMANTIC_FEATURE_NAMES", "SemanticFeatureExtractor", "SemanticFeatures"]

_ASSISTANT_RES = compile_named(ASSISTANT_ADDRESS_PATTERNS)
_DEST_LITERAL = re.compile(
    r"https?://[^\s<>\")\]]{4,}"
    r"|[\w.+\-]{1,64}@[\w\-]{1,63}(?:\.[\w\-]{2,63})+"
    r"|\b(?:www\.)?[a-z0-9][a-z0-9\-]{1,61}\.(?:com|net|org|io|xyz|ru|cn|top|tk|info|invalid|dev)\b",
    re.IGNORECASE,
)

SEMANTIC_FEATURE_NAMES: tuple[str, ...] = (
    # semantic / task-conflict
    "task_similarity",
    "off_topic",
    "lexical_overlap",
    "directive_strength",
    "has_destination",
    "has_sensitive_object",
    "has_tool_call",
    "external_send_on_secret",
    "destination_not_in_task",
    "authority_shift",
    # source-aware / provenance
    "ch_rag_document",
    "ch_tool_response",
    "ch_tool_metadata",
    "jp_present",
    "jp_metadata_field",
    "dt_markdown",
    "dt_code",
    "has_tool_identity",
)

_SOURCE_FEATURE_NAMES = frozenset(SEMANTIC_FEATURE_NAMES[10:])
_METADATA_FIELDS = ("description", "name", "schema", "parameters", "title", "summary")


@dataclass(frozen=True, slots=True)
class SemanticFeatures:
    """One record's named feature values, plus the convenience flags a reader
    or a rule might want without re-deriving them."""

    values: dict[str, float]

    @property
    def conflict_flag(self) -> bool:
        """Set only when an instruction carries concrete corroboration that it
        acts *outside* the host task: a secret-bearing external send, an external
        destination the task never named, a tool invocation, or an authority
        reassignment.

        This is the honesty property the tests pin: topicality alone never sets
        it, so a benign off-topic imperative (no destination, secret, tool, or
        authority claim) is not flagged no matter how unrelated it is.
        """

        v = self.values
        return bool(
            v["external_send_on_secret"]
            or v["destination_not_in_task"]
            or v["authority_shift"]
            or v["has_tool_call"]
        )


class SemanticFeatureExtractor:
    """Turns records (or free text) into the fixed semantic feature layout."""

    def __init__(self, embedder: Embedder | None = None, *, use_source_features: bool = True) -> None:
        self.embedder = embedder or default_embedder()
        self.use_source_features = use_source_features

    # ------------------------------------------------------------------ names
    @property
    def feature_names(self) -> tuple[str, ...]:
        if self.use_source_features:
            return SEMANTIC_FEATURE_NAMES
        return tuple(n for n in SEMANTIC_FEATURE_NAMES if n not in _SOURCE_FEATURE_NAMES)

    # ------------------------------------------------------------- extraction
    def one(self, task: TaskContext, instr: UntrustedInstruction) -> SemanticFeatures:
        sim = self._similarity(instr.text, task.text)
        overlap = _jaccard(instr.keywords, task.keywords)
        actions = extract_actions(instr.text)
        action = actions[0] if actions else None

        has_dest = float(bool(action and action.destination))
        has_obj = float(bool(action and action.sensitive_object))
        has_tool = float(bool(action and action.tool))
        external_secret = float(bool(action and action.is_external_send and action.touches_secret))
        directive = float(bool(action and (action.verb or action.tool)))
        authority = float(any(p.search(instr.text) for _n, p, _w in _ASSISTANT_RES))
        dest_not_in_task = float(directive > 0 and self._destination_absent(instr.text, task.text))

        values: dict[str, float] = {
            "task_similarity": sim,
            "off_topic": float(max(0.0, 1.0 - sim)),
            "lexical_overlap": overlap,
            "directive_strength": directive,
            "has_destination": has_dest,
            "has_sensitive_object": has_obj,
            "has_tool_call": has_tool,
            "external_send_on_secret": external_secret,
            "destination_not_in_task": dest_not_in_task,
            "authority_shift": authority,
        }
        if self.use_source_features:
            values.update(self._source_features(instr))
        return SemanticFeatures(values=values)

    def matrix(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        rows = [self.one(*build_context(record)) for record in records]
        names = self.feature_names
        return np.asarray([[f.values[n] for n in names] for f in rows], dtype=float)

    # ------------------------------------------------------------- internals
    def _similarity(self, instruction: str, task: str) -> float:
        if not task.strip() or not instruction.strip():
            return 0.0
        vectors = self.embedder.encode([instruction, task])
        return max(0.0, cosine(vectors[0], vectors[1]))

    @staticmethod
    def _destination_absent(instruction: str, task: str) -> bool:
        """True when the instruction names an external destination the task does
        not. This is the 'same words, new destination' signal: it fires even when
        the attack reuses the task's vocabulary, because it looks at the target."""

        literals = {m.group(0).lower() for m in _DEST_LITERAL.finditer(instruction)}
        if not literals:
            return False
        task_lower = task.lower()
        return any(literal not in task_lower for literal in literals)

    @staticmethod
    def _source_features(instr: UntrustedInstruction) -> dict[str, float]:
        path = instr.json_path or ""
        is_metadata_field = any(field in path.lower() for field in _METADATA_FIELDS)
        text = instr.text
        return {
            "ch_rag_document": float(instr.channel is Channel.RAG_DOCUMENT),
            "ch_tool_response": float(instr.channel is Channel.TOOL_RESPONSE),
            "ch_tool_metadata": float(instr.channel is Channel.TOOL_METADATA),
            "jp_present": float(bool(instr.json_path)),
            "jp_metadata_field": float(is_metadata_field),
            "dt_markdown": float("](" in text or bool(re.search(r"^#{1,6}\s", text, re.M))),
            "dt_code": float("```" in text or bool(re.search(r"[{};]\s*$", text, re.M))),
            "has_tool_identity": float(bool(instr.tool_id)),
        }


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
