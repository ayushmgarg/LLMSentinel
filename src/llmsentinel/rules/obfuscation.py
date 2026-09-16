"""Obfuscation rule: score the *evidence produced while normalising*.

This rule does not re-scan text.  Normalisation already recorded every
zero-width run it deleted, every entity it decoded, every hidden element it
found and every payload it decoded, with spans into the raw text.  Re-detecting
those would risk the two implementations disagreeing, which is exactly the sort
of inconsistency that makes a demo indefensible.

Scoring principle: concealment is only interesting when something was concealed.
A page with one soft hyphen is not an attack.  Zero-width characters *inside a
sentence that also carries an instruction* are.  The rule therefore combines the
strength of the evidence with whether the concealed or decoded content is itself
instruction-like, which it measures with the meta-instruction patterns.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from ..normalize.evidence import Evidence, EvidenceKind
from ..normalize.units import NormalizedUnit, Sentence
from .base import Rule, RuleFamily, RuleHit
from .lexicons import (
    ASSISTANT_ADDRESS_PATTERNS,
    META_INSTRUCTION_PATTERNS,
    SECRECY_PATTERNS,
    compile_named,
)

__all__ = ["ObfuscationRule"]

_INSTRUCTION_LIKE = compile_named(
    META_INSTRUCTION_PATTERNS + SECRECY_PATTERNS + ASSISTANT_ADDRESS_PATTERNS
)

#: Base score per evidence kind, before the instruction-content multiplier.
_BASE_SCORES: Final[dict[str, float]] = {
    EvidenceKind.ZERO_WIDTH: 0.45,
    EvidenceKind.BIDI_CONTROL: 0.60,
    EvidenceKind.TAG_CHARS: 0.85,
    EvidenceKind.CONTROL_CHAR: 0.25,
    EvidenceKind.HOMOGLYPH: 0.55,
    EvidenceKind.MIXED_SCRIPT: 0.20,
    EvidenceKind.INVISIBLE_STYLE: 0.55,
    EvidenceKind.HIDDEN_MARKUP: 0.30,
    EvidenceKind.HTML_ENTITY: 0.12,
    EvidenceKind.NFKC_CHANGE: 0.10,
    EvidenceKind.BASE64_DECODED: 0.55,
    EvidenceKind.HEX_DECODED: 0.55,
    EvidenceKind.URL_ENCODED: 0.35,
}

#: Multiplier applied when the concealed/decoded text is itself instruction-like.
_INSTRUCTION_BOOST: Final[float] = 1.8
#: Multiplier applied when it is plainly not.
_NO_INSTRUCTION_DAMPING: Final[float] = 0.45

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\w+")


class ObfuscationRule(Rule):
    rule_id = "obfuscation.v1"
    family = RuleFamily.OBFUSCATION
    feature_names = (
        "rule.obf.max",
        "rule.obf.strong_count",
        "rule.obf.weak_count",
        "rule.obf.decoded_instruction",
    )

    def apply(self, unit: NormalizedUnit, sentences: Sequence[Sentence]) -> list[RuleHit]:
        if not unit.evidence:
            return []

        hits: list[RuleHit] = []
        strong = 0
        weak = 0
        decoded_instruction = 0.0

        for item in unit.evidence:
            base = _BASE_SCORES.get(item.kind)
            if base is None:
                continue
            if item.is_strong:
                strong += 1
            else:
                weak += 1

            concealed = _concealed_text(item, unit)
            instruction_score = _instruction_likeness(concealed) if concealed else 0.0
            if instruction_score > 0 and item.kind in (
                EvidenceKind.BASE64_DECODED,
                EvidenceKind.HEX_DECODED,
                EvidenceKind.URL_ENCODED,
                EvidenceKind.HIDDEN_MARKUP,
                EvidenceKind.INVISIBLE_STYLE,
            ):
                decoded_instruction = max(decoded_instruction, instruction_score)

            multiplier = (
                1.0 + (_INSTRUCTION_BOOST - 1.0) * instruction_score
                if instruction_score > 0
                else (_NO_INSTRUCTION_DAMPING if concealed else 1.0)
            )
            score = round(min(base * multiplier, 1.0), 4)
            if score < 0.1:
                continue

            start, end = _span_in_normalised(item, unit)
            hits.append(
                self._hit(
                    score=score,
                    start=start,
                    end=end,
                    explanation=self._explain(item, instruction_score),
                    text=unit.normalized_text,
                    features={f"rule.obf.{item.kind}": score},
                    note=item.kind,
                )
            )

        if hits:
            counts = {
                "rule.obf.strong_count": float(strong),
                "rule.obf.weak_count": float(weak),
                "rule.obf.decoded_instruction": round(decoded_instruction, 4),
            }
            hits = [
                RuleHit(
                    rule_id=hit.rule_id,
                    family=hit.family,
                    score=hit.score,
                    span=hit.span,
                    explanation=hit.explanation,
                    features={**hit.features, **counts},
                    matched_text=hit.matched_text,
                )
                for hit in hits
            ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:6]

    @staticmethod
    def _explain(item: Evidence, instruction_score: float) -> str:
        suffix = ""
        if instruction_score >= 0.5:
            suffix = " and the concealed text reads as an instruction"
        elif instruction_score > 0:
            suffix = " and the concealed text partially matches instruction patterns"
        return f"{item.detail}{suffix}"


def _concealed_text(item: Evidence, unit: NormalizedUnit) -> str:
    """The text that the obfuscation was hiding, when we recovered it."""

    for key in ("decoded_preview", "inner_text"):
        value = item.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if item.span is not None:
        # Zero-width padding hides the words *next to* it rather than carrying
        # content itself, so the surrounding text is what was concealed.  The
        # window is taken from the **normalised** text: in the raw text the
        # padding is still interleaved through the words, so no instruction
        # pattern can match it and the concealment would be scored as if it hid
        # nothing.
        start, end = _span_in_normalised(item, unit)
        window_start = max(0, start - 160)
        window_end = min(len(unit.normalized_text), end + 160)
        return unit.normalized_text[window_start:window_end]
    return ""


def _instruction_likeness(text: str) -> float:
    """Fraction-style score in [0, 1] for how much ``text`` reads as a directive."""

    if not text.strip():
        return 0.0
    best = 0.0
    for _name, pattern, weight in _INSTRUCTION_LIKE:
        if pattern.search(text):
            best = max(best, weight)
    if best == 0.0:
        return 0.0
    # Short, dense directives are more convincing than one hit in a long page.
    words = len(_WORD_RE.findall(text)) or 1
    density = min(1.0, 40.0 / words)
    return round(min(1.0, best * (0.6 + 0.4 * density)), 4)


def _span_in_normalised(item: Evidence, unit: NormalizedUnit) -> tuple[int, int]:
    """Best-effort projection of a raw-text evidence span onto normalised text.

    Evidence spans index the raw text, but hits must index normalised text so
    the demo can highlight both views consistently.  The projection walks the
    offset map, and falls back to the whole unit when the region was deleted
    entirely (which is exactly what happens for zero-width runs).
    """

    if item.span is None:
        return 0, min(len(unit.normalized_text), 200)
    target_start, target_end = item.span.start, item.span.end
    source = unit.offset_map.source_index
    positions = [i for i, src in enumerate(source) if target_start <= src < target_end]
    if positions:
        return positions[0], positions[-1] + 1
    # Deleted region: anchor to the nearest surviving character.
    following = [i for i, src in enumerate(source) if src >= target_end]
    anchor = following[0] if following else len(unit.normalized_text)
    start = max(0, anchor - 60)
    end = min(len(unit.normalized_text), anchor + 60)
    return start, end
