"""Generic regex rule with context suppression.

Most linguistic rules share the same shape: run a table of named patterns over
the normalised text, discount each match by its context, keep the strongest
match per pattern, and emit one hit per pattern that survived.  This class
implements that once so the individual rules only declare *what* they look for.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..normalize.units import NormalizedUnit, Sentence
from .base import Rule, RuleHit
from .context import ContextIndex
from .lexicons import NamedPatterns, compile_named

__all__ = ["PatternRule"]


class PatternRule(Rule):
    """A rule defined by a table of ``(name, regex, weight)`` patterns."""

    def __init__(
        self,
        *,
        rule_id: str,
        family: str,
        patterns: NamedPatterns,
        feature_prefix: str,
        min_score: float = 0.05,
        suppress: bool = True,
    ) -> None:
        self.rule_id = rule_id
        self.family = family
        self.feature_prefix = feature_prefix
        self.min_score = min_score
        self.suppress = suppress
        self._patterns = compile_named(patterns)
        self.feature_names = (
            f"{feature_prefix}.max",
            f"{feature_prefix}.count",
            f"{feature_prefix}.suppressed",
        )

    def apply(self, unit: NormalizedUnit, sentences: Sequence[Sentence]) -> list[RuleHit]:
        text = unit.normalized_text
        if not text:
            return []
        index = ContextIndex(text) if self.suppress else None

        best: dict[str, RuleHit] = {}
        for name, pattern, weight in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                score = weight
                reasons = ""
                if index is not None:
                    suppression = index.suppression(start, end)
                    score *= suppression.factor
                    reasons = suppression.describe()
                if score < self.min_score:
                    continue
                start, end = _widen_to_sentence(sentences, start, end)
                explanation = self._explain(name, text[match.start() : match.end()], reasons)
                hit = self._hit(
                    score=round(min(score, 1.0), 4),
                    start=start,
                    end=end,
                    explanation=explanation,
                    text=text,
                    features={f"{self.feature_prefix}.{name}": round(min(score, 1.0), 4)},
                    note=name,
                )
                if name not in best or hit.score > best[name].score:
                    best[name] = hit
        return sorted(best.values(), key=lambda hit: hit.score, reverse=True)

    def _explain(self, pattern_name: str, matched: str, suppression: str) -> str:
        readable = pattern_name.replace("_", " ")
        snippet = " ".join(matched.split())
        if len(snippet) > 90:
            snippet = snippet[:89] + "…"
        base = f"{readable}: “{snippet}”"
        return f"{base} [{suppression}]" if suppression else base


def _widen_to_sentence(
    sentences: Sequence[Sentence], start: int, end: int, max_chars: int = 400
) -> tuple[int, int]:
    """Expand a match to its sentence so the highlight is readable.

    Highlighting three words out of a hostile paragraph hides the context the
    reviewer needs; highlighting a 4 KB blob hides the payload.  Widening to the
    containing sentence, capped, is the compromise.
    """

    for sentence in sentences:
        if sentence.start <= start and end <= sentence.end:
            if sentence.end - sentence.start <= max_chars:
                return sentence.start, sentence.end
            break
    return start, end
