"""Offset-preserving sentence segmentation.

Detection happens at sentence granularity: a 4000-word wiki page containing one
malicious line must be flagged *at that line*, not as an average over the page.
The segmenter therefore has to return exact character offsets, which rules out
libraries that hand back detached strings.

The implementation is deliberately dependency-free.  spaCy is a better sentence
splitter for prose, but it is a heavy optional dependency, it is not offset
stable across versions, and injected payloads are usually terse imperative
lines where a rule-based splitter is at least as good.  ``use_spacy=True`` is
available for the error analysis in Week 4.
"""

from __future__ import annotations

import re
from typing import Final

from .units import Sentence

__all__ = ["segment_sentences"]

#: Abbreviations after which a period does not end a sentence.
_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    ["mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie", "cf", "al", "fig", "figs", "no", "vol", "pp", "ed", "eds", "inc", "ltd", "co", "corp", "dept", "univ", "approx", "est", "max", "min", "sec", "min", "hr", "resp", "cca", "ca", "e.g", "i.e", "u.s", "u.k", "a.m", "p.m", "ph.d", "m.sc", "b.sc"]
)

_BOUNDARY_RE: Final[re.Pattern[str]] = re.compile(r'([.!?…]+)(["\'”’)\]]*)(\s+|$)')
#: ``...instructions.Ignore all previous...`` -- no space, because the attacker
#: removed it or a zero-width character was stripped between the two sentences.
_GLUED_BOUNDARY_RE: Final[re.Pattern[str]] = re.compile(r'([.!?…])(["\'”’)\]]*)(?=[A-Z][a-z])')
_HARD_BREAK_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*\n|\r\n\s*\r\n")
_LIST_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*(?:[-*•‣▪]|\d{1,2}[.)])\s+")
_TRAILING_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"([A-Za-z][A-Za-z.]*)$")

#: Sentences longer than this are split on newlines to keep spans highlightable.
_MAX_SENTENCE_CHARS: Final[int] = 600


def segment_sentences(text: str, *, use_spacy: bool = False) -> list[Sentence]:
    """Split ``text`` into sentences carrying offsets into ``text``.

    Returns an empty list for blank input.  Offsets are exact: for every
    returned sentence, ``text[s.start:s.end] == s.text``.
    """

    if not text.strip():
        return []
    if use_spacy:
        spacy_result = _segment_with_spacy(text)
        if spacy_result is not None:
            return spacy_result

    cuts = _boundary_positions(text)
    spans = _spans_from_cuts(text, cuts)
    spans = _split_overlong(text, spans)

    sentences: list[Sentence] = []
    for index, (start, end) in enumerate(spans):
        trimmed_start, trimmed_end = _trim(text, start, end)
        if trimmed_end <= trimmed_start:
            continue
        sentences.append(
            Sentence(
                index=len(sentences),
                text=text[trimmed_start:trimmed_end],
                start=trimmed_start,
                end=trimmed_end,
            )
        )
        del index
    return sentences


def _boundary_positions(text: str) -> list[int]:
    cuts: set[int] = set()

    for match in _HARD_BREAK_RE.finditer(text):
        cuts.add(match.start())
    for match in _LIST_ITEM_RE.finditer(text):
        cuts.add(match.start())

    for match in _BOUNDARY_RE.finditer(text):
        punctuation = match.group(1)
        if punctuation == "." and _is_abbreviation(text, match.start(1)):
            continue
        if punctuation == "." and _is_decimal(text, match.start(1)):
            continue
        cuts.add(match.end(2))

    for match in _GLUED_BOUNDARY_RE.finditer(text):
        if _is_abbreviation(text, match.start(1)) or _is_decimal(text, match.start(1)):
            continue
        cuts.add(match.end(2))

    return sorted(cuts)


def _is_abbreviation(text: str, dot_index: int) -> bool:
    token_match = _TRAILING_TOKEN_RE.search(text[:dot_index])
    if not token_match:
        return False
    token = token_match.group(1).lower().rstrip(".")
    if token in _ABBREVIATIONS:
        return True
    # Single initial such as "J." in "J. Smith".
    return len(token) == 1 and token.isalpha()


def _is_decimal(text: str, dot_index: int) -> bool:
    before = text[dot_index - 1] if dot_index > 0 else ""
    after = text[dot_index + 1] if dot_index + 1 < len(text) else ""
    return before.isdigit() and after.isdigit()


def _spans_from_cuts(text: str, cuts: list[int]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    previous = 0
    for cut in cuts:
        if cut <= previous:
            continue
        spans.append((previous, cut))
        previous = cut
    if previous < len(text):
        spans.append((previous, len(text)))
    return spans


def _split_overlong(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in spans:
        if end - start <= _MAX_SENTENCE_CHARS:
            result.append((start, end))
            continue
        cursor = start
        while end - cursor > _MAX_SENTENCE_CHARS:
            window_end = cursor + _MAX_SENTENCE_CHARS
            newline = text.rfind("\n", cursor + 1, window_end)
            space = text.rfind(" ", cursor + 1, window_end)
            cut = newline if newline > cursor else (space if space > cursor else window_end)
            result.append((cursor, cut))
            cursor = cut
        if cursor < end:
            result.append((cursor, end))
    return result


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _segment_with_spacy(text: str) -> list[Sentence] | None:  # pragma: no cover - optional path
    try:
        import spacy  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        nlp = _load_spacy_pipeline(spacy)
    except OSError:
        return None
    doc = nlp(text)
    sentences: list[Sentence] = []
    for sent in doc.sents:
        stripped = sent.text.strip()
        if not stripped:
            continue
        start = sent.start_char + (len(sent.text) - len(sent.text.lstrip()))
        sentences.append(
            Sentence(index=len(sentences), text=stripped, start=start, end=start + len(stripped))
        )
    return sentences


_SPACY_PIPELINE = None


def _load_spacy_pipeline(spacy_module):  # pragma: no cover - optional path
    global _SPACY_PIPELINE
    if _SPACY_PIPELINE is None:
        try:
            _SPACY_PIPELINE = spacy_module.load("en_core_web_sm", exclude=["ner", "lemmatizer"])
        except OSError:
            blank = spacy_module.blank("en")
            blank.add_pipe("sentencizer")
            _SPACY_PIPELINE = blank
    return _SPACY_PIPELINE
