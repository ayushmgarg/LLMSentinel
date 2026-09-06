"""Conservative recovery of text hidden behind an encoding.

Attackers wrap instructions in base64, hex or percent-encoding so that keyword
filters miss them.  Decoding aggressively is worse than not decoding at all: a
git SHA, a JWT fragment, a UUID or a minified asset name will "decode" into
mojibake and generate false positives forever.

Every decoder here therefore has to clear three gates before its output is kept:

1. **Shape** -- the candidate must match a strict pattern and a minimum length.
2. **Validity** -- strict decoding must succeed and the bytes must be UTF-8.
3. **Textness** -- the decoded string must look like natural language: mostly
   printable, containing letters, and containing whitespace or common
   punctuation once it is longer than a single word.

Anything that fails is left untouched and produces no evidence.
"""

from __future__ import annotations

import base64
import binascii
import re
import string
from typing import Final
from urllib.parse import unquote

from ..schema import Span
from .evidence import Evidence, EvidenceKind
from .units import DerivedSegment

__all__ = ["decode_embedded_payloads", "looks_like_text"]

_BASE64_RE: Final[re.Pattern[str]] = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}")
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"(?<![0-9A-Fa-fx])(?:[0-9A-Fa-f]{2}){16,}(?![0-9A-Fa-f])")
_ESCAPED_HEX_RE: Final[re.Pattern[str]] = re.compile(r"(?:\\x[0-9A-Fa-f]{2}){8,}")
_PERCENT_RE: Final[re.Pattern[str]] = re.compile(r"(?:%[0-9A-Fa-f]{2}){6,}")

#: Prefixes that make a base64-looking run something else entirely.
_BASE64_CONTEXT_EXCLUSIONS: Final[tuple[str, ...]] = (
    "sha256-",
    "sha384-",
    "sha512-",
    "integrity=",
    "data:image",
    "eyJ",  # JWT header; decoding it yields JSON, not an instruction
)

_PRINTABLE: Final[frozenset[str]] = frozenset(string.printable)


def looks_like_text(value: str, *, min_length: int = 8) -> bool:
    """Heuristic gate: does this decoded string plausibly carry a message?"""

    if len(value) < min_length:
        return False
    printable_ratio = sum(char in _PRINTABLE for char in value) / len(value)
    if printable_ratio < 0.92:
        return False
    letters = sum(char.isalpha() for char in value)
    if letters / len(value) < 0.45:
        return False
    # A long unbroken token is far more likely to be a hash than a sentence.
    has_separator = any(char in " \t\n,.;:!?" for char in value)
    return len(value) <= 24 or has_separator


def _try_base64(candidate: str) -> str | None:
    stripped = candidate.rstrip("=")
    if len(stripped) < 24:
        return None
    # Require the alphabet diversity of real base64 output; alphabetic-only runs
    # of this length are usually ordinary words or identifiers.
    has_upper = any(c.isupper() for c in stripped)
    has_lower = any(c.islower() for c in stripped)
    has_digit_or_symbol = any(c.isdigit() or c in "+/" for c in stripped)
    if not (has_upper and has_lower and has_digit_or_symbol):
        return None
    padded = candidate + "=" * (-len(candidate) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if looks_like_text(decoded) else None


def _try_hex(candidate: str) -> str | None:
    try:
        raw = bytes.fromhex(candidate)
    except ValueError:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if looks_like_text(decoded) else None


def _try_escaped_hex(candidate: str) -> str | None:
    try:
        raw = bytes(int(part, 16) for part in candidate.split("\\x") if part)
    except ValueError:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if looks_like_text(decoded, min_length=6) else None


def _try_percent(candidate: str) -> str | None:
    decoded = unquote(candidate, errors="strict")
    if decoded == candidate:
        return None
    return decoded if looks_like_text(decoded, min_length=6) else None


def decode_embedded_payloads(text: str) -> tuple[list[DerivedSegment], list[Evidence]]:
    """Find and decode encoded regions of ``text``.

    Offsets in the returned segments and evidence index ``text`` directly, so
    the caller is responsible for mapping them back to raw text if ``text`` has
    already been transformed.
    """

    segments: list[DerivedSegment] = []
    evidence: list[Evidence] = []
    claimed: list[tuple[int, int]] = []

    def overlaps_claimed(start: int, end: int) -> bool:
        return any(start < c_end and c_start < end for c_start, c_end in claimed)

    plan = (
        (_BASE64_RE, _try_base64, EvidenceKind.BASE64_DECODED, "base64"),
        (_ESCAPED_HEX_RE, _try_escaped_hex, EvidenceKind.HEX_DECODED, "escaped_hex"),
        (_HEX_RE, _try_hex, EvidenceKind.HEX_DECODED, "hex"),
        (_PERCENT_RE, _try_percent, EvidenceKind.URL_ENCODED, "percent"),
    )

    for pattern, decoder, kind, name in plan:
        for match in pattern.finditer(text):
            start, end = match.span()
            if overlaps_claimed(start, end):
                continue
            prefix = text[max(0, start - 16) : start].lower()
            if name == "base64" and any(x in prefix for x in _BASE64_CONTEXT_EXCLUSIONS):
                continue
            if name == "base64" and match.group(0).startswith("eyJ"):
                continue
            decoded = decoder(match.group(0))
            if decoded is None:
                continue
            claimed.append((start, end))
            span = Span(start, end, field="raw_text", note=f"{name}_source")
            segments.append(
                DerivedSegment(
                    kind=name,
                    text=decoded,
                    source_span=span,
                    detail=f"{end - start} characters of {name} decoded to {len(decoded)} characters",
                )
            )
            evidence.append(
                Evidence(
                    kind=kind,
                    detail=f"{name} region decoded to: {_preview(decoded)}",
                    span=span,
                    payload={"encoding": name, "decoded_preview": decoded[:200]},
                )
            )

    segments.sort(key=lambda seg: seg.source_span.start)
    evidence.sort(key=lambda item: item.span.start if item.span else 0)
    return segments, evidence


def _preview(value: str, limit: int = 80) -> str:
    single_line = " ".join(value.split())
    return single_line if len(single_line) <= limit else single_line[: limit - 1] + "…"
