"""Task-conflict rule: does this directive belong to the document carrying it?

The project's label definition is that an injection is assistant-directed
control content **that conflicts with the host task**.  Every other rule in this
package scores only the first half -- the phrasing.  That is why a setup guide
saying "you must run the migration job first", or a prompt-engineering page that
addresses an AI reader, can look suspicious: nothing else in the pipeline asks
whether a directive belongs where it sits.

What this rule measures
-----------------------
An inserted payload changes the *register* of the document it lands in.  A
reference page about glaciers is descriptive prose throughout; one imperative
sentence telling the reader's agent to email credentials is a register outlier.
A deployment guide, by contrast, is imperative from top to bottom, so an
imperative there is native and carries no evidence at all.

So the rule computes the document's directive ratio -- what fraction of its
sentences give instructions -- and scores a directive only when it stands out
against a mostly descriptive document.  A first attempt used lexical overlap
between the sentence and its context; it was dropped because real documents have
very little sentence-to-sentence vocabulary overlap, so it fired on legitimate
imperatives and stayed silent on off-topic payloads.  Overlap survives only as a
*damper*: a directive that reuses the host task's own vocabulary is serving that
task, so its score is reduced.

Guards
------
* At least :data:`_MIN_SENTENCES` sentences, or there is no register to measure.
* Documents that are already instructional (directive ratio above
  :data:`_NATIVE_RATIO`) get no score: how-to content is not an anomaly.
* The score is capped at :data:`_MAX_SCORE`. Register is corroborating evidence,
  never a detection on its own.

``host_task`` is read from ``unit.metadata``; the corpus stores it per record and
:meth:`llmsentinel.rules.engine.RuleEngine.analyse_text` accepts it directly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from ..normalize.units import NormalizedUnit, Sentence
from .base import Rule, RuleFamily, RuleHit
from .context import ContextIndex
from .lexicons import (
    ASSISTANT_ADDRESS_PATTERNS,
    META_INSTRUCTION_PATTERNS,
    SECRECY_PATTERNS,
    TOOL_INVOCATION_PATTERNS,
    compile_named,
)

__all__ = ["TaskConflictRule", "directive_strength", "topical_overlap"]

_EXPLICIT_DIRECTIVE_PATTERNS = compile_named(
    META_INSTRUCTION_PATTERNS
    + SECRECY_PATTERNS
    + ASSISTANT_ADDRESS_PATTERNS
    + TOOL_INVOCATION_PATTERNS
)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")

#: Second-person obligation, the most common way to address a reader.
_SECOND_PERSON_RE: Final[re.Pattern[str]] = re.compile(
    r"\byou\s+(?:must|should|shall|need\s+to|have\s+to|can|may|will|are\s+(?:asked|required|expected))\b",
    re.IGNORECASE,
)

#: Verbs that start an imperative sentence.  A lexicon is used rather than a POS
#: tagger to keep the rule dependency-free and offset-stable; it only has to
#: cover sentence-initial position, which is a small and stable set.
#: Erring towards *more* verbs is the safe direction: a larger lexicon raises
#: the measured directive ratio, which makes the rule fire less often.
_IMPERATIVE_VERBS: Final[frozenset[str]] = frozenset(
    ["add", "allow", "apply", "approve", "ask", "attach", "avoid", "bind", "block", "build", "call", "check", "choose", "clean", "clear", "click", "commit", "compare", "complete", "configure", "confirm", "connect", "contact", "continue", "convert", "copy", "create", "define", "delete", "deny", "deploy", "describe", "disable", "disconnect", "disregard", "document", "download", "do", "don't", "edit", "email", "enable", "enter", "ensure", "execute", "explain", "export", "fetch", "fill", "filter", "finish", "fix", "follow", "forget", "format", "forward", "generate", "get", "give", "go", "grant", "group", "handle", "ignore", "import", "include", "insert", "inspect", "install", "invoke", "join", "keep", "launch", "leave", "limit", "link", "list", "load", "log", "look", "mail", "make", "measure", "merge", "migrate", "mock", "monitor", "mount", "move", "name", "note", "open", "parse", "paste", "perform", "pick", "place", "plan", "post", "prepare", "print", "provide", "publish", "pull", "push", "put", "read", "record", "refresh", "register", "release", "remove", "rename", "repeat", "replace", "reply", "report", "request", "reset", "resolve", "respond", "restart", "restore", "retry", "return", "reveal", "review", "revoke", "roll", "rollback", "rotate", "run", "save", "schedule", "select", "send", "set", "share", "show", "sign", "sort", "split", "start", "stop", "store", "submit", "summarise", "summarize", "switch", "tag", "tell", "test", "transfer", "try", "turn", "unmount", "update", "upgrade", "upload", "use", "validate", "verify", "visit", "wait", "watch", "write"]
)

_LEADING_ADVERB_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:please|now|first|then|next|finally|immediately|always|never|before\s+\w+,?)\s+",
    re.IGNORECASE,
)

#: Function words carry no topic.  Deliberately short: a long stop list starts
#: removing domain vocabulary and the overlap estimate degrades.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    ["the", "and", "for", "are", "but", "not", "you", "your", "yours", "our", "ours", "their", "theirs", "this", "that", "these", "those", "with", "without", "from", "into", "onto", "than", "then", "when", "where", "which", "while", "who", "whom", "whose", "what", "have", "has", "had", "having", "was", "were", "been", "being", "will", "would", "shall", "should", "can", "could", "may", "might", "must", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "only", "own", "same", "too", "very", "just", "about", "above", "after", "again", "against", "because", "before", "below", "between", "during", "further", "here", "once", "out", "over", "under", "until", "upon", "via", "per", "due", "within", "across", "among", "also", "however", "therefore", "they", "them", "its", "it", "is", "be", "as", "at", "by", "of", "on", "in", "to", "or", "an", "if", "do", "does", "did", "done", "use", "used", "using", "make", "makes", "made", "get", "gets", "got", "set", "sets", "one", "two", "three", "new", "old", "first", "last", "next"]
)

#: Directive ratio at or below which a directive is a clear register outlier.
_OUTLIER_RATIO: Final[float] = 0.20
#: Directive ratio at or above which the document is instructional by nature.
_NATIVE_RATIO: Final[float] = 0.50

#: Minimum sentences before a register can be estimated at all.
_MIN_SENTENCES: Final[int] = 3
#: Minimum content words in a sentence for it to be considered.
_MIN_SENTENCE_WORDS: Final[int] = 4

#: Applied when the directive reuses the host task's vocabulary.
_ON_TASK_DAMPING: Final[float] = 0.45

#: Maximum contribution of this rule.
_MAX_SCORE: Final[float] = 0.55


def _content_words(text: str) -> set[str]:
    return {
        word.lower()
        for word in _WORD_RE.findall(text)
        if word.lower() not in _STOPWORDS and len(word) > 2
    }


def topical_overlap(sentence: str, context: str) -> float:
    """Containment of the sentence's vocabulary in its context, in ``[0, 1]``.

    Containment rather than Jaccard: the context is normally much larger than
    the sentence, and Jaccard would penalise an on-topic sentence simply because
    the document says more.
    """

    sentence_words = _content_words(sentence)
    context_words = _content_words(context)
    if not sentence_words or not context_words:
        return 0.0
    return len(sentence_words & context_words) / len(sentence_words)


def directive_strength(sentence: str) -> float:
    """How strongly a sentence instructs its reader, in ``[0, 1]``.

    Explicit control language scores highest, an addressed obligation next, and
    a bare imperative lowest -- an imperative is ordinary in documentation, so on
    its own it should barely move the score.
    """

    text = sentence.strip()
    if not text:
        return 0.0

    for _name, pattern, weight in _EXPLICIT_DIRECTIVE_PATTERNS:
        if pattern.search(text):
            return max(0.9, weight)

    if _SECOND_PERSON_RE.search(text):
        return 0.6

    stripped = _LEADING_ADVERB_RE.sub("", text).lstrip("-*•‣ \t")
    first = _WORD_RE.match(stripped)
    if first and first.group(0).lower() in _IMPERATIVE_VERBS:
        return 0.5
    return 0.0


class TaskConflictRule(Rule):
    """Scores directives that break the register of the document carrying them."""

    rule_id = "task_conflict.v1"
    family = RuleFamily.TASK_CONFLICT
    feature_names = (
        "rule.task.max",
        "rule.task.directive_ratio",
        "rule.task.directive_strength",
        "rule.task.host_task_overlap",
        "rule.task.has_host_task",
    )

    def apply(self, unit: NormalizedUnit, sentences: Sequence[Sentence]) -> list[RuleHit]:
        text = unit.normalized_text
        if not text or len(sentences) < _MIN_SENTENCES:
            return []

        strengths = {
            sentence.index: directive_strength(sentence.text)
            for sentence in sentences
            if len(_content_words(sentence.text)) >= _MIN_SENTENCE_WORDS
        }
        if not strengths:
            return []

        directive_ratio = sum(1 for value in strengths.values() if value > 0) / len(sentences)
        outlier = _outlier_weight(directive_ratio)
        if outlier <= 0.0:
            # Instructional document: an instruction here is native content.
            return []

        host_task = str(unit.metadata.get("host_task") or "").strip()
        index = ContextIndex(text)
        hits: list[RuleHit] = []

        for sentence in sentences:
            strength = strengths.get(sentence.index, 0.0)
            if strength <= 0.0:
                continue

            overlap = topical_overlap(sentence.text, host_task) if host_task else 0.0
            damping = _ON_TASK_DAMPING if overlap >= 0.25 else 1.0

            score = _MAX_SCORE * strength * outlier * damping
            suppression = index.suppression(sentence.start, sentence.end)
            score = round(min(score * suppression.factor, 1.0), 4)
            if score < 0.08:
                continue

            hits.append(
                self._hit(
                    score=score,
                    start=sentence.start,
                    end=sentence.end,
                    explanation=self._explain(
                        directive_ratio, host_task, overlap, suppression.describe()
                    ),
                    text=text,
                    features={
                        "rule.task.directive_ratio": round(directive_ratio, 4),
                        "rule.task.directive_strength": round(strength, 4),
                        "rule.task.host_task_overlap": round(overlap, 4),
                        "rule.task.has_host_task": 1.0 if host_task else 0.0,
                    },
                    note="register_outlier",
                )
            )

        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:3]

    @staticmethod
    def _explain(ratio: float, host_task: str, overlap: float, suppression: str) -> str:
        base = (
            f"instruction in otherwise descriptive content "
            f"(only {ratio:.0%} of sentences give instructions)"
        )
        if host_task:
            base += (
                f"; shares {overlap:.0%} of its vocabulary with the host task “{host_task}”"
            )
        return f"{base} [{suppression}]" if suppression else base


def _outlier_weight(directive_ratio: float) -> float:
    """Map the document's directive ratio onto ``[0, 1]`` outlier weight."""

    if directive_ratio >= _NATIVE_RATIO:
        return 0.0
    if directive_ratio <= _OUTLIER_RATIO:
        return 1.0
    return (_NATIVE_RATIO - directive_ratio) / (_NATIVE_RATIO - _OUTLIER_RATIO)
