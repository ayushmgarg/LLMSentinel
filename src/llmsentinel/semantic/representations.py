"""The three things a context-aware detector reasons over.

Section 8's rules ask "does this text *look* like an instruction?". The semantic
layer asks a different question: "does this instruction *belong* to the task the
user actually asked for, and where would it send the result?". To ask that we
need the task, the untrusted instruction, and any action the instruction would
trigger as explicit objects rather than as loose strings.

Everything here is derived deterministically from a :class:`CorpusRecord` (or
from free text in the demo). No model is involved at this layer — these are the
inputs the feature extractor in :mod:`llmsentinel.semantic.features` turns into
numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..rules.lexicons import (
    ACTION_VERBS,
    DESTINATION_PATTERNS,
    SENSITIVE_OBJECTS,
    TOOL_INVOCATION_PATTERNS,
    compile_named,
)
from ..schema import Channel, CorpusRecord

__all__ = [
    "ProposedAction",
    "TaskContext",
    "UntrustedInstruction",
    "build_context",
    "extract_actions",
    "keyword_set",
]

_WORD = re.compile(r"[a-z][a-z0-9_\-]{2,}")
_ACTION_RES = compile_named(ACTION_VERBS)
_DEST_RES = compile_named(DESTINATION_PATTERNS)
_OBJECT_RES = compile_named(SENSITIVE_OBJECTS)
_TOOL_RES = compile_named(TOOL_INVOCATION_PATTERNS)

# Words too common to carry topic; excluded from the task/instruction overlap so
# that "the", "your", "please" do not make every instruction look on-topic.
_STOPWORDS = frozenset(
    (
        "the a an and or of to for in on at by with from into your you our we they "
        "this that these those is are was were be been being it its as but if then "
        "so not no do does did can could should would will shall may might must "
        "please kindly also about over under out up down off than them their"
    ).split()
)


def keyword_set(text: str) -> frozenset[str]:
    """Lower-cased content words of ``text``, for cheap lexical-overlap signals."""

    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS)


@dataclass(frozen=True, slots=True)
class TaskContext:
    """What the trusted user actually asked the agent to do."""

    text: str
    keywords: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_text(cls, text: str | None) -> TaskContext:
        text = (text or "").strip()
        return cls(text=text, keywords=keyword_set(text))


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """An action an instruction would trigger: a verb, a destination, an object.

    Parsed from text, so ``destination``/``sensitive_object`` are ``None`` when
    the instruction names none. The point of separating them is that an action
    verb alone ("summarise") is harmless; a verb *plus* a sensitive object *plus*
    an external destination is the exfiltration shape.
    """

    verb: str | None = None
    destination: str | None = None
    sensitive_object: str | None = None
    tool: str | None = None

    @property
    def is_external_send(self) -> bool:
        return self.verb is not None and self.destination is not None

    @property
    def touches_secret(self) -> bool:
        return self.sensitive_object is not None


@dataclass(frozen=True, slots=True)
class UntrustedInstruction:
    """A span of untrusted context, with the provenance that makes it untrusted."""

    text: str
    channel: Channel
    json_path: str | None = None
    tool_id: str | None = None
    keywords: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        channel: Channel = Channel.UNKNOWN,
        json_path: str | None = None,
        tool_id: str | None = None,
    ) -> UntrustedInstruction:
        return cls(
            text=text,
            channel=channel,
            json_path=json_path,
            tool_id=tool_id,
            keywords=keyword_set(text),
        )


def _first_match(text: str, compiled: tuple[tuple[str, re.Pattern[str], float], ...]) -> str | None:
    for name, pattern, _weight in compiled:
        if pattern.search(text):
            return name
    return None


def extract_actions(text: str) -> list[ProposedAction]:
    """Pull the (verb, destination, object, tool) an instruction would trigger.

    A single :class:`ProposedAction` is returned summarising the strongest
    action-shaped evidence in the text; callers that only need "is there an
    external send touching a secret?" read :pyattr:`ProposedAction.is_external_send`
    and :pyattr:`ProposedAction.touches_secret`.
    """

    action = ProposedAction(
        verb=_first_match(text, _ACTION_RES),
        destination=_first_match(text, _DEST_RES),
        sensitive_object=_first_match(text, _OBJECT_RES),
        tool=_first_match(text, _TOOL_RES),
    )
    return [action] if any([action.verb, action.destination, action.sensitive_object, action.tool]) else []


def build_context(record: CorpusRecord) -> tuple[TaskContext, UntrustedInstruction]:
    """Derive the task and the untrusted instruction from one corpus record."""

    task = TaskContext.from_text(record.host_task)
    tool_id = record.extra.get("tool_name") or record.extra.get("server") if record.extra else None
    instruction = UntrustedInstruction.from_text(
        record.raw_text,
        channel=record.channel,
        json_path=record.json_path,
        tool_id=tool_id,
    )
    return task, instruction
