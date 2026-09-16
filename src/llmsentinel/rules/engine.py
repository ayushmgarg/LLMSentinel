"""Rule engine: run every rule, build a fixed feature vector, aggregate a score.

Two consumers with different needs:

* the **rules-only baseline** and the demo need a single interpretable score;
* the **fusion layer** needs a fixed-length numeric vector whose layout never
  changes between training and inference.

Both come from the same :class:`RuleReport`, so a number shown in the demo can
never disagree with the number that fed the model.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..normalize.pipeline import Normalizer
from ..normalize.units import NormalizedUnit, Sentence
from ..schema import Channel
from .action import DestructiveActionRule, ToolInvocationRule
from .base import Rule, RuleError, RuleFamily, RuleHit, RuleReport
from .exfiltration import ExfiltrationRule
from .meta_instruction import (
    AnswerShapingRule,
    AssistantAddressRule,
    MetaInstructionRule,
    SecrecyRule,
)
from .metadata import ToolMetadataRule
from .obfuscation import ObfuscationRule
from .task_conflict import TaskConflictRule

__all__ = ["RuleEngine", "RuleEngineConfig", "default_rules"]

LOGGER = logging.getLogger("llmsentinel.rules")


def default_rules() -> list[Rule]:
    """The rule set retained after Week 2 evaluation.

    Order is irrelevant to scoring but fixed for reproducible feature layouts.
    """

    return [
        MetaInstructionRule(),
        SecrecyRule(),
        AnswerShapingRule(),
        AssistantAddressRule(),
        ObfuscationRule(),
        ExfiltrationRule(),
        ToolInvocationRule(),
        DestructiveActionRule(),
        ToolMetadataRule(),
        TaskConflictRule(),
    ]


@dataclass(frozen=True, slots=True)
class RuleEngineConfig:
    """Family weights for the rules-only aggregate.

    Weights express how much a *maximal* hit in one family should move the
    aggregate on its own.  They were chosen on train/dev and are reported in the
    ablation table; the fusion model does not use them, it learns its own.
    """

    family_weights: dict[str, float] = field(
        default_factory=lambda: {
            RuleFamily.META_INSTRUCTION: 0.95,
            RuleFamily.OBFUSCATION: 0.65,
            RuleFamily.EXFILTRATION: 0.85,
            RuleFamily.ACTION_HIJACK: 0.70,
            RuleFamily.ASSISTANT_ADDRESS: 0.45,
            RuleFamily.METADATA_POISONING: 0.90,
            # Corroborating evidence only: topical foreignness is meaningful
            # next to a directive, never on its own.
            RuleFamily.TASK_CONFLICT: 0.50,
        }
    )
    #: Families excluded from this run.  Used by the leave-one-family-out ablation.
    disabled_families: frozenset[str] = frozenset()
    #: Individual rules excluded from this run.
    disabled_rules: frozenset[str] = frozenset()

    def with_family_disabled(self, family: str) -> RuleEngineConfig:
        return RuleEngineConfig(
            family_weights=dict(self.family_weights),
            disabled_families=self.disabled_families | {family},
            disabled_rules=self.disabled_rules,
        )


class RuleEngine:
    """Applies the rule set to normalised units."""

    def __init__(
        self,
        rules: Iterable[Rule] | None = None,
        config: RuleEngineConfig | None = None,
        normalizer: Normalizer | None = None,
        *,
        strict: bool = False,
    ) -> None:
        self.config = config or RuleEngineConfig()
        self.normalizer = normalizer or Normalizer()
        self._all_rules = list(rules) if rules is not None else default_rules()
        self.rules = [
            rule
            for rule in self._all_rules
            if rule.rule_id not in self.config.disabled_rules
            and rule.family not in self.config.disabled_families
        ]
        self.feature_names = self._build_feature_layout()
        #: Re-raise rule exceptions instead of degrading. Used by the test suite
        #: and by any batch job that must not silently lose a detector.
        self.strict = strict
        #: Failures per rule id since construction, for run-level telemetry.
        self.error_counts: dict[str, int] = {}
        #: Units scored since construction, so an error rate can be reported.
        self.units_scored: int = 0

    # ------------------------------------------------------------ evaluation
    def analyse(
        self, unit: NormalizedUnit, sentences: Sequence[Sentence] | None = None
    ) -> RuleReport:
        """Run every enabled rule over one unit."""

        if sentences is None:
            sentences = self.normalizer.sentences(unit)

        hits: list[RuleHit] = []
        errors: list[RuleError] = []
        for rule in self.rules:
            try:
                hits.extend(rule.apply(unit, sentences))
            except Exception as exc:
                # A crashing rule must not take down the guard -- it runs on
                # hostile input by definition -- but a swallowed exception is a
                # silently disabled detector, so the failure is recorded,
                # counted and logged rather than turned into a zero-score hit.
                if self.strict:
                    raise
                error = RuleError(
                    rule_id=rule.rule_id,
                    family=rule.family,
                    unit_id=unit.unit_id,
                    exception_type=type(exc).__name__,
                    message=str(exc)[:300],
                )
                errors.append(error)
                self.error_counts[rule.rule_id] = self.error_counts.get(rule.rule_id, 0) + 1
                LOGGER.exception(
                    "rule %s failed on unit %s (%s); score is degraded",
                    rule.rule_id,
                    unit.unit_id,
                    type(exc).__name__,
                )

        self.units_scored += 1
        report = RuleReport(unit_id=unit.unit_id, hits=hits, errors=errors)
        report.features = self.features(report)
        report.score = self.aggregate(report)
        return report

    def analyse_text(
        self,
        text: str,
        *,
        channel: Channel | str = Channel.RAG_DOCUMENT,
        host_task: str | None = None,
        json_path: str | None = None,
    ) -> tuple[NormalizedUnit, RuleReport]:
        """Convenience path used by tests, the demo and the rules-only baseline.

        ``host_task`` is what the user actually asked for.  Passing it enables
        :class:`~llmsentinel.rules.task_conflict.TaskConflictRule`, which is the
        only rule that can tell a directive belonging to the document from one
        that replaces the user's task.
        """

        unit = self.normalizer.normalize_text(
            text,
            channel=channel,
            json_path=json_path,
            metadata={"host_task": host_task} if host_task else None,
        )
        return unit, self.analyse(unit)

    def error_report(self) -> dict[str, Any]:
        """Run-level rule-failure telemetry, recorded alongside results."""

        total = sum(self.error_counts.values())
        return {
            "units_scored": self.units_scored,
            "rule_failures": dict(sorted(self.error_counts.items())),
            "total_failures": total,
            "failure_rate": (total / self.units_scored) if self.units_scored else 0.0,
            "healthy": total == 0,
        }

    # -------------------------------------------------------------- features
    def _build_feature_layout(self) -> tuple[str, ...]:
        names: set[str] = set()
        for family in RuleFamily.ALL:
            names.add(f"family.{family}.max")
            names.add(f"family.{family}.count")
        for rule in self.rules:
            names.update(rule.feature_names)
        return tuple(sorted(names))

    def features(self, report: RuleReport) -> dict[str, float]:
        """Fixed-layout feature dictionary; absent signals are explicit zeros."""

        values = dict.fromkeys(self.feature_names, 0.0)
        for hit in report.hits:
            family_max = f"family.{hit.family}.max"
            family_count = f"family.{hit.family}.count"
            if family_max in values:
                values[family_max] = max(values[family_max], hit.score)
                values[family_count] += 1.0
            for name, value in hit.features.items():
                if name in values:
                    values[name] = max(values[name], value)
        # Rule-declared aggregate features that individual hits do not set.
        for rule in self.rules:
            prefix_max = f"{_prefix(rule)}.max"
            if prefix_max in values and values[prefix_max] == 0.0:
                rule_hits = [hit.score for hit in report.hits if hit.rule_id == rule.rule_id]
                if rule_hits:
                    values[prefix_max] = max(rule_hits)
        return values

    def feature_vector(self, report: RuleReport) -> list[float]:
        values = report.features or self.features(report)
        return [values.get(name, 0.0) for name in self.feature_names]

    # ------------------------------------------------------------- aggregate
    def aggregate(self, report: RuleReport) -> float:
        """Noisy-OR over per-family maxima.

        Noisy-OR is used rather than a sum because independent weak signals
        should accumulate without any single family being able to saturate the
        score, and because the result stays in [0, 1] without clipping.
        """

        family_best: dict[str, float] = {}
        for hit in report.hits:
            family_best[hit.family] = max(family_best.get(hit.family, 0.0), hit.score)

        complement = 1.0
        for family, best in family_best.items():
            weight = self.config.family_weights.get(family, 0.5)
            complement *= 1.0 - min(1.0, weight * best)
        return round(1.0 - complement, 6)

    # ------------------------------------------------------------------ misc
    def describe(self) -> dict[str, Any]:
        return {
            "rules": [rule.rule_id for rule in self.rules],
            "disabled_families": sorted(self.config.disabled_families),
            "disabled_rules": sorted(self.config.disabled_rules),
            "feature_count": len(self.feature_names),
            "strict": self.strict,
            "errors": self.error_report(),
        }


def _prefix(rule: Rule) -> str:
    return getattr(rule, "feature_prefix", f"rule.{rule.rule_id.split('.')[0]}")
