"""Rule interface, hits and reports.

Design contract for every rule in this package:

* it returns **spans**, never a bare boolean, so the demo can highlight;
* it returns a **human-readable explanation** that names the matched evidence;
* it returns **features** (named floats) that the fusion layer can consume,
  so the hybrid model never re-implements rule logic;
* it is **high precision by construction**.  A rule that fires on ordinary
  documentation is worse than no rule, because the fusion layer will learn to
  ignore it and the demo will lose credibility.  Recall is the transformer's
  job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..normalize.units import NormalizedUnit, Sentence
from ..schema import Span

__all__ = ["Rule", "RuleError", "RuleFamily", "RuleHit", "RuleReport"]


class RuleFamily:
    """Families used for ablation ("leave one rule family out") and reporting."""

    META_INSTRUCTION: Final[str] = "meta_instruction"
    OBFUSCATION: Final[str] = "obfuscation"
    EXFILTRATION: Final[str] = "exfiltration"
    ACTION_HIJACK: Final[str] = "action_hijack"
    ASSISTANT_ADDRESS: Final[str] = "assistant_address"
    METADATA_POISONING: Final[str] = "metadata_poisoning"
    TASK_CONFLICT: Final[str] = "task_conflict"

    ALL: Final[tuple[str, ...]] = (
        META_INSTRUCTION,
        OBFUSCATION,
        EXFILTRATION,
        ACTION_HIJACK,
        ASSISTANT_ADDRESS,
        METADATA_POISONING,
        TASK_CONFLICT,
    )


@dataclass(frozen=True, slots=True)
class RuleError:
    """A rule that raised while scoring one unit.

    Rules must not crash the guard -- it runs on hostile input by definition --
    but a swallowed exception is a silently disabled detector.  Every failure is
    therefore recorded here, counted by the engine, and logged, so a broken rule
    shows up as a number in the results rather than as missing recall.
    """

    rule_id: str
    family: str
    unit_id: str
    exception_type: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "family": self.family,
            "unit_id": self.unit_id,
            "exception_type": self.exception_type,
            "message": self.message,
        }

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.rule_id} failed on {self.unit_id}: {self.exception_type}: {self.message}"


@dataclass(frozen=True, slots=True)
class RuleHit:
    """One firing of one rule, anchored in the normalised text."""

    rule_id: str
    family: str
    score: float
    span: Span
    explanation: str
    features: dict[str, float] = field(default_factory=dict)
    #: Text actually matched, kept for the trace so the UI never has to re-slice.
    matched_text: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"{self.rule_id}: score {self.score} outside [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "family": self.family,
            "score": round(self.score, 4),
            "span": self.span.to_dict(),
            "explanation": self.explanation,
            "features": self.features,
            "matched_text": self.matched_text,
        }

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.family}/{self.rule_id} {self.score:.2f}] {self.explanation}"


@dataclass(slots=True)
class RuleReport:
    """Aggregated rule output for one unit."""

    unit_id: str
    hits: list[RuleHit] = field(default_factory=list)
    features: dict[str, float] = field(default_factory=dict)
    #: Aggregate rules-only risk in [0, 1]; see ``RuleEngine.aggregate``.
    score: float = 0.0
    #: Rules that raised on this unit.  Non-empty means the score is incomplete.
    errors: list[RuleError] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when at least one rule failed, so the score under-reports risk."""

        return bool(self.errors)

    @property
    def families(self) -> set[str]:
        return {hit.family for hit in self.hits}

    def top_hits(self, limit: int = 5) -> list[RuleHit]:
        return sorted(self.hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def spans(self) -> list[Span]:
        return [hit.span for hit in self.hits]

    def trace(self) -> list[str]:
        return [str(hit) for hit in sorted(self.hits, key=lambda h: h.score, reverse=True)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "score": round(self.score, 4),
            "hits": [hit.to_dict() for hit in self.hits],
            "features": {k: round(v, 4) for k, v in self.features.items()},
            "errors": [error.to_dict() for error in self.errors],
            "degraded": self.degraded,
        }


class Rule(ABC):
    """Base class for all rules."""

    #: Stable identifier used in ablations and experiment logs.
    rule_id: str = "rule"
    #: One of :class:`RuleFamily`.
    family: str = "unspecified"
    #: Names of the features this rule can emit, so the fusion feature vector
    #: has a fixed layout even when the rule does not fire.
    feature_names: tuple[str, ...] = ()

    @abstractmethod
    def apply(self, unit: NormalizedUnit, sentences: Sequence[Sentence]) -> list[RuleHit]:
        """Return every hit for ``unit``.  Must not raise on adversarial input."""

    # ------------------------------------------------------------- utilities
    def _hit(
        self,
        *,
        score: float,
        start: int,
        end: int,
        explanation: str,
        text: str,
        features: dict[str, float] | None = None,
        note: str | None = None,
    ) -> RuleHit:
        span = Span(start, end, field="normalized_text", note=note or self.rule_id)
        return RuleHit(
            rule_id=self.rule_id,
            family=self.family,
            score=score,
            span=span,
            explanation=explanation,
            features=features or {},
            matched_text=text[start:end],
        )

    def __repr__(self) -> str:  # pragma: no cover - display helper
        return f"<{type(self).__name__} id={self.rule_id!r} family={self.family!r}>"
