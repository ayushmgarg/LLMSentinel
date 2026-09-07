"""Hard-negative suppression: is this text *directing* the assistant, or *about* it?

The largest source of false positives in this task is text that contains attack
language legitimately: a security blog quoting ``Ignore all previous
instructions``, an API reference showing how to send an API key, a policy telling
employees what they must do.

The definition used throughout the project (see :class:`llmsentinel.schema.Label`)
is that an injection is *assistant-directed control content that conflicts with
the host task*.  This module implements the "assistant-directed" half by
computing a multiplicative suppression factor for a matched span.

Threat model for this module
----------------------------
Suppression is applied to attacker-controlled text, so an attacker can *choose*
its inputs.  An earlier version suppressed on formatting alone, which let the
same payload drop from 0.87 to 0.35 by wrapping it in quotation marks and to
0.22 inside a code fence -- a free evasion, and worst of all for coding agents,
where fenced text is the norm.

Three properties close that hole:

**Corroboration, in both directions.**  Neither signal is trusted alone, because
each is free for an attacker to write.  Quotation marks or a code fence suppress
only mildly on their own; so does a discussion marker on its own -- prefixing
"For example," to a payload dropped its score by a third until this was fixed.
Deep suppression requires *both*: a discussion signal (attribution, example
marker, research or defensive framing, reported speech) **and** the payload
being set apart as quoted or fenced material.  An attacker can produce that
combination, but only by presenting the payload as somebody else's quoted text,
which is also the form least likely to be followed by the model it targets.

**Dominance.**  A quote that quotes the whole document cites nothing.  When
quoted or fenced regions cover most of the input, formatting-based suppression
is switched off entirely.

**Floors.**  Un-corroborated suppression cannot go below :data:`_WEAK_FLOOR`, so
a formatted payload stays clearly above the operating threshold.  Corroborated
suppression may go as deep as :data:`_MIN_FACTOR`, which is what keeps security
write-ups out of the positive class.

Suppression only ever lowers a score, so a broken suppressor can cost recall but
can never manufacture a detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .lexicons import CITATION_MARKERS, compile_named

__all__ = ["ContextIndex", "Suppression"]

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]{1,200}`")
_INDENTED_CODE_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\n)(?: {4}|\t)[^\n]{4,}", re.MULTILINE)
_QUOTE_RE: Final[re.Pattern[str]] = re.compile(
    r"\"[^\"\n]{8,400}\"|“[^”\n]{8,400}”|'[^'\n]{16,400}'|«[^»\n]{8,400}»"
)
_BLOCKQUOTE_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\n)>[^\n]*", re.MULTILINE)

_CITATION_PATTERNS = compile_named(CITATION_MARKERS)

#: How far back a citation marker still frames the span, in characters.
_CITATION_WINDOW: Final[int] = 220

#: Fraction of the input that quoted/fenced regions may cover before
#: formatting-based suppression is treated as meaningless and switched off.
_DOMINANCE_LIMIT: Final[float] = 0.6

#: Formatting-only factors.  Mild by design: they express "this might be a
#: quotation", not "this is a quotation of something being discussed".
_UNCORROBORATED_QUOTE: Final[float] = 0.80
_UNCORROBORATED_CODE: Final[float] = 0.65

#: Formatting factors once a discussion signal corroborates the framing.
_CORROBORATED_QUOTE: Final[float] = 0.40
_CORROBORATED_CODE: Final[float] = 0.25
_CORROBORATED_INLINE_CODE: Final[float] = 0.50

#: Factor for a discussion marker with nothing set apart as quoted or fenced.
#: Kept mild: writing "For example," in front of a payload is free.
_LONE_MARKER_FACTOR: Final[float] = 0.85

#: Floor when nothing corroborates the formatting: a payload that merely wears
#: quotes or a code fence stays well above any usable operating threshold.
_WEAK_FLOOR: Final[float] = 0.55

#: Absolute floor. Even a genuine security article keeps a residual score, so a
#: real injection hidden inside one is not silenced completely.
_MIN_FACTOR: Final[float] = 0.12


@dataclass(frozen=True, slots=True)
class Suppression:
    """Result of context analysis for one span."""

    factor: float
    reasons: tuple[str, ...]
    #: True when a discussion/citation signal justified deep suppression.
    corroborated: bool = False
    #: Factor before the floor was applied, kept for the audit trail.
    raw_factor: float = 1.0

    @property
    def applied(self) -> bool:
        return self.factor < 0.999

    @property
    def floored(self) -> bool:
        return self.factor > self.raw_factor + 1e-9

    def describe(self) -> str:
        if not self.applied:
            return ""
        detail = "; ".join(self.reasons)
        note = f"context suppression x{self.factor:.2f} ({detail})"
        if self.floored:
            note += "; floor applied: formatting alone is not evidence of quotation"
        return note


class ContextIndex:
    """Pre-computed context regions for one normalised text.

    Built once per unit and queried per rule hit: the regex scans are the
    expensive part and every rule needs the same answers.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self._code = _merge(_spans(_FENCE_RE, text) + _spans(_INDENTED_CODE_RE, text))
        self._inline_code = _merge(_spans(_INLINE_CODE_RE, text))
        self._quotes = _merge(_spans(_QUOTE_RE, text) + _spans(_BLOCKQUOTE_RE, text))
        self._citations: list[tuple[int, int, str, float]] = []
        for name, pattern, weight in _CITATION_PATTERNS:
            for match in pattern.finditer(text):
                self._citations.append((match.start(), match.end(), name, weight))
        self._citations.sort()

        length = max(len(text), 1)
        covered = _covered_length(_merge(self._code + self._inline_code + self._quotes))
        self.formatting_coverage = covered / length
        #: When formatting covers most of the input there is no "outer" document
        #: doing the quoting, so the formatting carries no information.
        self.formatting_is_meaningful = self.formatting_coverage < _DOMINANCE_LIMIT

    # ------------------------------------------------------------------ query
    def suppression(self, start: int, end: int) -> Suppression:
        """Combine every applicable context factor for span ``[start, end)``."""

        citation = self._nearest_citation(start, end)
        in_block_code = _contained(self._code, start, end)
        in_inline_code = _contained(self._inline_code, start, end)
        in_quote = _contained(self._quotes, start, end)

        # Deep suppression requires *two independent* signals: a discussion
        # marker AND the payload being set apart as quoted or fenced material.
        # A marker on its own is as cheap for an attacker as a quotation mark --
        # prefixing "For example," costs nothing and used to halve the score --
        # so a lone marker is treated as weak evidence and floored like
        # formatting is.
        set_apart = self.formatting_is_meaningful and (in_block_code or in_inline_code or in_quote)
        corroborated = citation is not None and set_apart

        factor = 1.0
        reasons: list[str] = []

        if citation is not None:
            name, weight = citation
            factor *= weight if corroborated else _LONE_MARKER_FACTOR
            reasons.append(
                f"framed as {name.replace('_', ' ')}"
                if corroborated
                else f"weak framing: {name.replace('_', ' ')} with nothing set apart"
            )

        if not self.formatting_is_meaningful and (in_block_code or in_inline_code or in_quote):
            reasons.append(
                f"formatting ignored: quoted/fenced regions cover "
                f"{self.formatting_coverage:.0%} of the input"
            )
        else:
            if in_block_code:
                factor *= _CORROBORATED_CODE if corroborated else _UNCORROBORATED_CODE
                reasons.append("inside a code block")
            elif in_inline_code:
                factor *= _CORROBORATED_INLINE_CODE if corroborated else 0.85
                reasons.append("inside inline code")
            if in_quote:
                factor *= _CORROBORATED_QUOTE if corroborated else _UNCORROBORATED_QUOTE
                reasons.append("inside a quotation")

        raw = factor
        floor = _MIN_FACTOR if corroborated else _WEAK_FLOOR
        factor = max(factor, floor)
        return Suppression(
            factor=factor,
            reasons=tuple(reasons),
            corroborated=corroborated,
            raw_factor=raw,
        )

    def _nearest_citation(self, start: int, end: int) -> tuple[str, float] | None:
        best: tuple[str, float] | None = None
        for c_start, c_end, name, weight in self._citations:
            if c_start > end:
                break
            # A marker counts when it precedes the span closely, or overlaps it.
            if c_end <= start and start - c_end > _CITATION_WINDOW:
                continue
            if best is None or weight < best[1]:
                best = (name, weight)
        return best

    def in_code(self, start: int, end: int) -> bool:
        return _contained(self._code, start, end) or _contained(self._inline_code, start, end)

    def in_quote(self, start: int, end: int) -> bool:
        return _contained(self._quotes, start, end)


# ----------------------------------------------------------------- internals
def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [match.span() for match in pattern.finditer(text)]


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _covered_length(spans: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in spans)


def _contained(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    """True when the span's midpoint falls inside one of the regions."""

    midpoint = (start + end) // 2
    for region_start, region_end in spans:
        if region_start > midpoint:
            return False
        if region_start <= midpoint < region_end:
            return True
    return False
