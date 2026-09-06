"""Normalisation evidence.

Normalisation is not only clean-up: *the act of cleaning is itself a signal*.
A document that needed zero-width characters stripped, HTML comments unwrapped
or base64 decoded is more suspicious than one that survived normalisation
untouched.  Each cleaning step therefore records an :class:`Evidence` item with
a span into the raw text, and the obfuscation rule consumes those items instead
of re-scanning the text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ..schema import Span

__all__ = ["Evidence", "EvidenceKind"]


class EvidenceKind:
    """Frozen vocabulary of normalisation findings."""

    NFKC_CHANGE: Final[str] = "nfkc_change"
    ZERO_WIDTH: Final[str] = "zero_width"
    BIDI_CONTROL: Final[str] = "bidi_control"
    CONTROL_CHAR: Final[str] = "control_char"
    MIXED_SCRIPT: Final[str] = "mixed_script"
    HOMOGLYPH: Final[str] = "homoglyph"
    TAG_CHARS: Final[str] = "unicode_tag_chars"
    HTML_ENTITY: Final[str] = "html_entity"
    HIDDEN_MARKUP: Final[str] = "hidden_markup"
    INVISIBLE_STYLE: Final[str] = "invisible_style"
    BASE64_DECODED: Final[str] = "base64_decoded"
    HEX_DECODED: Final[str] = "hex_decoded"
    URL_ENCODED: Final[str] = "url_encoded"
    LEETSPEAK: Final[str] = "leetspeak"

    #: Kinds that indicate deliberate concealment rather than ordinary markup.
    STRONG: Final[frozenset[str]] = frozenset(
        {
            ZERO_WIDTH,
            BIDI_CONTROL,
            TAG_CHARS,
            HOMOGLYPH,
            INVISIBLE_STYLE,
            BASE64_DECODED,
            HEX_DECODED,
        }
    )

    #: Kinds that are common in ordinary web/technical content on their own.
    WEAK: Final[frozenset[str]] = frozenset(
        {NFKC_CHANGE, HTML_ENTITY, HIDDEN_MARKUP, CONTROL_CHAR, MIXED_SCRIPT, URL_ENCODED, LEETSPEAK}
    )


@dataclass(frozen=True, slots=True)
class Evidence:
    """One normalisation finding, anchored in the raw text where possible."""

    kind: str
    detail: str
    span: Span | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_strong(self) -> bool:
        return self.kind in EvidenceKind.STRONG

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "span": self.span.to_dict() if self.span else None,
            "payload": self.payload,
        }

    def __str__(self) -> str:  # pragma: no cover - display helper
        where = f" at [{self.span.start}:{self.span.end}]" if self.span else ""
        return f"{self.kind}{where}: {self.detail}"
