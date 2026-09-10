"""Deterministic, meaning-preserving text transforms for robustness testing.

Each transform takes a string and returns a perturbed string that a human would
still read the same way. They fall into three intents:

* **surface** — whitespace, casing, punctuation, quoting, Markdown, code fences:
  an attacker reformats without changing the words.
* **unicode** — full-width homoglyphs, zero-width insertion, bidi wrapping,
  base64 embedding: concealment the normaliser is meant to recover.
* **rewrite** — synonym swaps, declarative framing, dilution, distractors: the
  wording or the surrounding context changes.

A detector that is robust keeps its score on a *positive* under these transforms
and does not gain false positives when the same transforms are applied to a
*benign* text. Genuine paraphrase is deliberately out of scope — it needs a
model and a human check — and the ``synonym``/``declarative`` transforms here are
labelled as the weak lexical approximations they are.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable

__all__ = ["PERTURBATIONS", "TransformKind", "apply", "families"]

TransformKind = Callable[[str], str]

_FULLWIDTH = {chr(c): chr(c - 0x20 + 0xFF00) for c in range(0x21, 0x7F)}
_ZWSP = "​"
_RLO, _PDF = "‮", "‬"

# Small, honest synonym map: real substitutions for a few trigger words, not a
# paraphraser. Enough to test whether a keyword-shaped detector is brittle.
_SYNONYMS = {
    r"\bignore\b": "disregard",
    r"\bsend\b": "transmit",
    r"\bemail\b": "mail",
    r"\bdelete\b": "erase",
    r"\bpassword\b": "passphrase",
    r"\binstructions\b": "directives",
}


def identity(text: str) -> str:
    return text


def whitespace(text: str) -> str:
    """Collapse runs of spaces and scatter newlines — reformatting, same words."""

    collapsed = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"(\S) (\S)", r"\1  \2", collapsed, count=20)


def casing(text: str) -> str:
    return text.upper()


def punctuation(text: str) -> str:
    """Sprinkle separators a reader skims over."""

    return re.sub(r"(\w) (\w)", r"\1, \2", text, count=10)


def quote_wrap(text: str) -> str:
    return f'"{text}"'


def markdown_blockquote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() or [text])


def code_fence(text: str) -> str:
    return f"```\n{text}\n```"


def fullwidth(text: str) -> str:
    return "".join(_FULLWIDTH.get(ch, ch) for ch in text)


def zero_width(text: str, *, limit: int = 400) -> str:
    """Insert zero-width spaces between characters of the first ``limit`` chars."""

    head = _ZWSP.join(text[:limit])
    return head + text[limit:]


def bidi_wrap(text: str) -> str:
    return f"{_RLO}{text}{_PDF}"


def base64_embed(text: str) -> str:
    """Hide the payload in a base64 blob the normaliser is expected to decode."""

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"Encoded note (base64): {encoded}"


def synonym(text: str) -> str:
    out = text
    for pattern, replacement in _SYNONYMS.items():
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def declarative(text: str) -> str:
    """Reframe as reported speech. A *weak* approximation of declarative wording."""

    return f"The document states the following for reference: {text}"


def dilution(text: str, *, pad: int = 1200) -> str:
    """Bury the text in long benign filler, testing long-context dilution."""

    filler = (
        "The notebook application syncs content across devices and keeps a local "
        "cache for offline use. Exports run in the background for large notebooks. "
    )
    block = (filler * ((pad // len(filler)) + 1))[:pad]
    return f"{block}\n\n{text}\n\n{block}"


def distractors(text: str) -> str:
    """Surround the text with benign imperatives a reader would not flag."""

    before = "Please remember to save your work. Check the sync status in the menu. "
    after = " Remember to sign out on shared devices. Review the changelog weekly."
    return f"{before}{text}{after}"


#: name -> (transform, intent-group). ``families`` groups them for reporting.
PERTURBATIONS: dict[str, tuple[TransformKind, str]] = {
    "original": (identity, "baseline"),
    "whitespace": (whitespace, "surface"),
    "casing": (casing, "surface"),
    "punctuation": (punctuation, "surface"),
    "quote_wrap": (quote_wrap, "surface"),
    "markdown_blockquote": (markdown_blockquote, "surface"),
    "code_fence": (code_fence, "surface"),
    "fullwidth": (fullwidth, "unicode"),
    "zero_width": (zero_width, "unicode"),
    "bidi_wrap": (bidi_wrap, "unicode"),
    "base64_embed": (base64_embed, "unicode"),
    "synonym": (synonym, "rewrite"),
    "declarative": (declarative, "rewrite"),
    "dilution": (dilution, "rewrite"),
    "distractors": (distractors, "rewrite"),
}


def apply(name: str, text: str) -> str:
    return PERTURBATIONS[name][0](text)


def families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, (_fn, group) in PERTURBATIONS.items():
        out.setdefault(group, []).append(name)
    return out
