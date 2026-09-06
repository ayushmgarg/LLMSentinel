"""Evaluate each rule family on its own, and with one family removed.

Answers two questions the report has to answer about the rule engine:

* what does each family detect *by itself*?  A family that adds nothing alone
  and nothing when removed is dead weight and should be dropped.
* what does the engine lose when one family is removed?  This is the
  leave-one-family-out ablation, run here on **dev** so that the retained rule
  set is chosen before test is ever scored.

    python scripts/rule_family_eval.py
"""

from __future__ import annotations

from llmsentinel.evaluation import evaluate_scores, load_splits
from llmsentinel.models import RulesScorer
from llmsentinel.rules import RuleEngine, RuleEngineConfig, RuleFamily


def score_dev(engine: RuleEngine, records) -> tuple[float, float]:
    scorer = RulesScorer(engine=engine)
    metrics = evaluate_scores(
        system="rules",
        split="dev",
        y_true=[record.y for record in records],
        y_score=scorer.score(records),
        is_hard_negative=[record.is_hard_negative for record in records],
    )
    return metrics.auprc, metrics.hard_negative_fpr.get("fpr=0.01", 0.0)


def main() -> None:
    dev = load_splits()["dev"]
    full_auprc, full_hard = score_dev(RuleEngine(), dev)
    print(f"all families            AUPRC={full_auprc:.3f}  hard-neg FPR@1%={full_hard:.3f}")
    print()
    print(f"{'family':<22} {'alone':>16} {'without it':>18}")
    for family in RuleFamily.ALL:
        only = RuleEngineConfig(
            disabled_families=frozenset(set(RuleFamily.ALL) - {family})
        )
        without = RuleEngineConfig(disabled_families=frozenset({family}))
        alone_auprc, _ = score_dev(RuleEngine(config=only), dev)
        without_auprc, _ = score_dev(RuleEngine(config=without), dev)
        delta = full_auprc - without_auprc
        print(
            f"{family:<22} AUPRC={alone_auprc:.3f}   "
            f"AUPRC={without_auprc:.3f} ({delta:+.3f})"
        )


if __name__ == "__main__":
    main()
