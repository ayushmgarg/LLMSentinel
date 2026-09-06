"""HTML entity decoding and hidden-markup evidence.

Retrieved web pages are the main indirect-injection channel, and the payload is
usually placed where a human reader will not see it: an HTML comment, a
``display:none`` block, an ``alt`` attribute, a white-on-white ``<span>``.  The
text still reaches the model.

This module therefore does two things: it decodes entities (so ``&#105;gnore``
becomes ``ignore`` for the rules), and it *reports* concealment without deleting
it, because the hidden text is exactly what has to be scored and highlighted.
"""

from __future__ import annotations

import html
import re
from typing import Final

from ..schema import Span
from .evidence import Evidence, EvidenceKind
from .offsets import OffsetMap

__all__ = ["decode_entities", "detect_hidden_markup"]

_ENTITY_RE: Final[re.Pattern[str]] = re.compile(
    r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,31});"
)

_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"<!--(.*?)-->", re.DOTALL)

_INVISIBLE_STYLE_RE: Final[re.Pattern[str]] = re.compile(
    r"""<[^>]*\bstyle\s*=\s*(?P<q>["'])(?P<style>[^"']*)(?P=q)[^>]*>""",
    re.IGNORECASE,
)

_HIDDEN_ATTR_RE: Final[re.Pattern[str]] = re.compile(
    r"<[^>]*\b(?:hidden|aria-hidden\s*=\s*[\"']true[\"'])[^>]*>", re.IGNORECASE
)

_META_RE: Final[re.Pattern[str]] = re.compile(
    r"<meta[^>]*\bcontent\s*=\s*([\"'])(?P<content>.*?)\1[^>]*>", re.IGNORECASE | re.DOTALL
)

_ALT_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:alt|title|aria-label)\s*=\s*([\"'])(?P<value>[^\"']{20,})\1", re.IGNORECASE
)

_INVISIBLE_STYLE_HINTS: Final[tuple[str, ...]] = (
    "display:none",
    "visibility:hidden",
    "font-size:0",
    "opacity:0",
    "color:#fff",
    "color:white",
    "color:rgb(255,255,255)",
    "text-indent:-9999",
    "position:absolute;left:-9999",
    "clip:rect(0,0,0,0)",
    "height:0",
    "width:0",
)


def decode_entities(text: str) -> tuple[str, OffsetMap, list[Evidence]]:
    """Decode HTML entities once, keeping an offset map onto the input.

    Decoding is single-pass on purpose: repeated decoding of ``&amp;#105;``
    would rewrite text that a browser also shows literally, which changes the
    meaning of the document rather than revealing it.
    """

    out: list[str] = []
    indices: list[int] = []
    decoded: list[tuple[int, str, str]] = []
    cursor = 0

    for match in _ENTITY_RE.finditer(text):
        literal = match.group(0)
        replacement = html.unescape(literal)
        if replacement == literal:
            continue
        out.append(text[cursor : match.start()])
        indices.extend(range(cursor, match.start()))
        out.append(replacement)
        indices.extend([match.start()] * len(replacement))
        decoded.append((match.start(), literal, replacement))
        cursor = match.end()

    out.append(text[cursor:])
    indices.extend(range(cursor, len(text)))

    evidence: list[Evidence] = []
    if decoded:
        sample = ", ".join(f"{lit}->{rep!r}" for _, lit, rep in decoded[:5])
        evidence.append(
            Evidence(
                kind=EvidenceKind.HTML_ENTITY,
                detail=f"{len(decoded)} HTML entity/entities decoded ({sample})",
                span=Span(decoded[0][0], decoded[0][0] + len(decoded[0][1]), field="raw_text"),
                payload={"count": len(decoded)},
            )
        )
    return "".join(out), OffsetMap.from_pairs(indices, len(text)), evidence


def detect_hidden_markup(text: str) -> list[Evidence]:
    """Report markup constructs that hide text from a human reader.

    Nothing is removed.  Concealed text is still scored by the rules and the
    model; this function only records *why* a span deserves extra weight.
    """

    evidence: list[Evidence] = []

    for match in _COMMENT_RE.finditer(text):
        body = match.group(1).strip()
        if len(body) < 12:
            continue
        evidence.append(
            Evidence(
                kind=EvidenceKind.HIDDEN_MARKUP,
                detail=f"HTML comment containing {len(body)} characters of text",
                span=Span(match.start(), match.end(), field="raw_text"),
                payload={"construct": "html_comment", "inner_text": body[:400]},
            )
        )

    for match in _INVISIBLE_STYLE_RE.finditer(text):
        style = re.sub(r"\s+", "", match.group("style")).lower()
        hit = next((hint for hint in _INVISIBLE_STYLE_HINTS if hint in style), None)
        if hit is None:
            continue
        evidence.append(
            Evidence(
                kind=EvidenceKind.INVISIBLE_STYLE,
                detail=f"element styled to be invisible ({hit})",
                span=Span(match.start(), match.end(), field="raw_text"),
                payload={"construct": "inline_style", "style": match.group("style")[:200]},
            )
        )

    for match in _HIDDEN_ATTR_RE.finditer(text):
        evidence.append(
            Evidence(
                kind=EvidenceKind.INVISIBLE_STYLE,
                detail="element carries a hidden/aria-hidden attribute",
                span=Span(match.start(), match.end(), field="raw_text"),
                payload={"construct": "hidden_attribute"},
            )
        )

    for pattern, construct in ((_META_RE, "meta_content"), (_ALT_TITLE_RE, "attribute_text")):
        group = "content" if construct == "meta_content" else "value"
        for match in pattern.finditer(text):
            body = match.group(group).strip()
            if len(body) < 20:
                continue
            evidence.append(
                Evidence(
                    kind=EvidenceKind.HIDDEN_MARKUP,
                    detail=f"non-rendered {construct.replace('_', ' ')} of {len(body)} characters",
                    span=Span(match.start(), match.end(), field="raw_text"),
                    payload={"construct": construct, "inner_text": body[:400]},
                )
            )

    evidence.sort(key=lambda item: (item.span.start if item.span else 0))
    return evidence
