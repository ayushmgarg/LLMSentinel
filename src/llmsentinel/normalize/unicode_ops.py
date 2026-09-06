"""Unicode-level normalisation with offset tracking and concealment evidence.

Three separate concerns live here, in the order the pipeline applies them:

1. :func:`strip_invisibles` -- delete characters that render as nothing but
   change what a model or a human reader sees (zero-width joiners, bidi
   overrides, Unicode tag characters, stray control codes).
2. :func:`nfkc_normalise` -- Unicode NFKC applied per grapheme cluster so that
   compatibility forms collapse without destroying the offset map.
3. :func:`detect_script_confusion` -- report Cyrillic/Greek look-alikes embedded
   in otherwise Latin words (the classic ``раypal`` trick).  This step reports
   only; it never rewrites, because a false "correction" would corrupt evidence.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from ..schema import Span
from .evidence import Evidence, EvidenceKind
from .offsets import OffsetMap

__all__ = [
    "ZERO_WIDTH_CHARS",
    "detect_script_confusion",
    "nfkc_normalise",
    "strip_invisibles",
]

#: Characters with no visible width that survive copy/paste and tokenisation.
ZERO_WIDTH_CHARS: Final[frozenset[str]] = frozenset(
    {
        "​",  # zero width space
        "‌",  # zero width non-joiner
        "‍",  # zero width joiner
        "⁠",  # word joiner
        "﻿",  # zero width no-break space / BOM
        "᠎",  # mongolian vowel separator
        "­",  # soft hyphen
    }
)

#: Bidirectional formatting characters used to hide or reorder visible text.
BIDI_CHARS: Final[frozenset[str]] = frozenset(
    {
        "‪",
        "‫",
        "‬",
        "‭",
        "‮",  # right-to-left override
        "⁦",
        "⁧",
        "⁨",
        "⁩",
    }
)

#: Unicode tag block: an entire ASCII alphabet that renders invisibly.
_TAG_BLOCK: Final[range] = range(0xE0000, 0xE0080)

#: Control characters that are never legitimate in retrieved prose.
_ALLOWED_CONTROLS: Final[frozenset[str]] = frozenset({"\n", "\r", "\t"})

_SCRIPT_RANGES: Final[tuple[tuple[str, int, int], ...]] = (
    ("Cyrillic", 0x0400, 0x04FF),
    ("Greek", 0x0370, 0x03FF),
    ("Armenian", 0x0530, 0x058F),
    ("Cherokee", 0x13A0, 0x13FF),
)

#: Non-Latin characters that are visually indistinguishable from ASCII letters.
HOMOGLYPHS: Final[dict[str, str]] = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "і": "i",
    "ј": "j",
    "һ": "h",
    "ԁ": "d",
    "ԛ": "q",
    "ѕ": "s",
    "ο": "o",
    "α": "a",
    "ρ": "p",
    "ν": "v",
    "Α": "A",
    "Β": "B",
    "Е": "E",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
}


def _script_of(char: str) -> str:
    code = ord(char)
    for name, low, high in _SCRIPT_RANGES:
        if low <= code <= high:
            return name
    if char.isascii() and char.isalpha():
        return "Latin"
    return "Other"


def strip_invisibles(text: str) -> tuple[str, OffsetMap, list[Evidence]]:
    """Remove invisible and control characters, reporting each removal.

    Returns the cleaned text, an offset map back into ``text``, and one
    evidence item per *contiguous run* of removed characters so the demo can
    highlight "there was a hidden block here" instead of dozens of empty spans.
    """

    kept: list[str] = []
    indices: list[int] = []
    removals: list[tuple[int, int, str, str]] = []  # start, end, kind, sample
    run_start: int | None = None
    run_kind: str | None = None
    run_chars: list[str] = []

    def close_run(end: int) -> None:
        nonlocal run_start, run_kind, run_chars
        if run_start is not None and run_kind is not None:
            removals.append((run_start, end, run_kind, "".join(run_chars)))
        run_start, run_kind, run_chars = None, None, []

    for index, char in enumerate(text):
        kind: str | None = None
        if char in ZERO_WIDTH_CHARS:
            kind = EvidenceKind.ZERO_WIDTH
        elif char in BIDI_CHARS:
            kind = EvidenceKind.BIDI_CONTROL
        elif ord(char) in _TAG_BLOCK:
            kind = EvidenceKind.TAG_CHARS
        elif unicodedata.category(char) in ("Cc", "Cf") and char not in _ALLOWED_CONTROLS:
            kind = EvidenceKind.CONTROL_CHAR

        if kind is None:
            close_run(index)
            kept.append(char)
            indices.append(index)
            continue

        if run_kind != kind:
            close_run(index)
            run_start, run_kind, run_chars = index, kind, []
        run_chars.append(char)

    close_run(len(text))

    evidence = [
        Evidence(
            kind=kind,
            detail=_describe_removal(kind, sample),
            span=Span(start, end, field="raw_text"),
            payload={
                "count": end - start,
                "codepoints": [f"U+{ord(c):04X}" for c in sample[:16]],
            },
        )
        for start, end, kind, sample in removals
    ]
    return "".join(kept), OffsetMap.from_pairs(indices, len(text)), evidence


def _describe_removal(kind: str, sample: str) -> str:
    count = len(sample)
    if kind == EvidenceKind.ZERO_WIDTH:
        return f"{count} zero-width character(s) removed"
    if kind == EvidenceKind.BIDI_CONTROL:
        return f"{count} bidirectional control character(s) removed"
    if kind == EvidenceKind.TAG_CHARS:
        decoded = "".join(chr(ord(c) - 0xE0000) for c in sample if 0xE0020 <= ord(c) <= 0xE007E)
        suffix = f" decoding to {decoded!r}" if decoded else ""
        return f"{count} invisible Unicode tag character(s) removed{suffix}"
    return f"{count} control character(s) removed"


def _grapheme_clusters(text: str) -> list[tuple[int, str]]:
    """Split into (start_index, cluster) where a cluster is a base + its marks."""

    clusters: list[tuple[int, str]] = []
    start = 0
    buffer: list[str] = []
    for index, char in enumerate(text):
        if buffer and unicodedata.combining(char) == 0:
            clusters.append((start, "".join(buffer)))
            buffer, start = [], index
        buffer.append(char)
    if buffer:
        clusters.append((start, "".join(buffer)))
    return clusters


def nfkc_normalise(text: str) -> tuple[str, OffsetMap, list[Evidence]]:
    """Apply NFKC per grapheme cluster, keeping an exact offset map.

    Whole-string ``unicodedata.normalize`` would be marginally more faithful,
    but it can merge or split characters across cluster boundaries, which makes
    offsets unrecoverable.  Per-cluster normalisation composes marks correctly,
    collapses compatibility forms (fullwidth, ligatures, circled letters) and
    keeps every output character attributable to one input position.
    """

    out: list[str] = []
    indices: list[int] = []
    changed: list[tuple[int, str, str]] = []

    for start, cluster in _grapheme_clusters(text):
        normalised = unicodedata.normalize("NFKC", cluster)
        if normalised != cluster:
            changed.append((start, cluster, normalised))
        for char in normalised:
            out.append(char)
            indices.append(start)

    evidence: list[Evidence] = []
    if changed:
        sample = ", ".join(f"{orig!r}->{norm!r}" for _, orig, norm in changed[:5])
        evidence.append(
            Evidence(
                kind=EvidenceKind.NFKC_CHANGE,
                detail=f"{len(changed)} character(s) changed by NFKC ({sample})",
                span=Span(changed[0][0], changed[0][0] + len(changed[0][1]), field="raw_text"),
                payload={"count": len(changed)},
            )
        )
    return "".join(out), OffsetMap.from_pairs(indices, len(text)), evidence


def detect_script_confusion(text: str) -> list[Evidence]:
    """Report words that mix Latin with look-alike characters from other scripts.

    A word is flagged only when it contains *both* ASCII letters and non-Latin
    letters, which excludes genuinely multilingual documents (a fully Cyrillic
    word is not a homoglyph attack) while catching ``раypal`` style splicing.
    """

    evidence: list[Evidence] = []
    for start, word in _iter_words(text):
        scripts = {_script_of(c) for c in word if c.isalpha()}
        foreign = scripts - {"Latin", "Other"}
        if not foreign or "Latin" not in scripts:
            continue
        confusables = [c for c in word if c in HOMOGLYPHS]
        kind = EvidenceKind.HOMOGLYPH if confusables else EvidenceKind.MIXED_SCRIPT
        detail = (
            f"word {word!r} mixes Latin with {'/'.join(sorted(foreign))}"
            + (f"; look-alike characters: {''.join(confusables)}" if confusables else "")
        )
        evidence.append(
            Evidence(
                kind=kind,
                detail=detail,
                span=Span(start, start + len(word), field="raw_text"),
                payload={
                    "word": word,
                    "scripts": sorted(scripts),
                    "skeleton": "".join(HOMOGLYPHS.get(c, c) for c in word),
                },
            )
        )
    return evidence


def _iter_words(text: str) -> list[tuple[int, str]]:
    words: list[tuple[int, str]] = []
    start: int | None = None
    for index, char in enumerate(text):
        if char.isalpha():
            if start is None:
                start = index
        elif start is not None:
            words.append((start, text[start:index]))
            start = None
    if start is not None:
        words.append((start, text[start:]))
    return words
