"""Abstain / human-review recommendation for uncertain or conflicting evidence.

The detector is probabilistic; the policy is deterministic. Between them there is
a third, honest option: say "not sure, send this to a human". This module turns
the signals that should trigger that into an explicit, reasoned recommendation.

It is advisory and experimental. It does not override the capability policy (a
destructive action is still blocked regardless); it marks a verdict as one a
reviewer should look at, with the reasons attached, so an analyst queue can be
built on top of it.
"""

from __future__ import annotations

__all__ = ["REVIEW", "review_reasons"]

REVIEW = "review"


def review_reasons(
    risk: float,
    thresholds: dict[str, float],
    *,
    rule_score: float | None = None,
    model_score: float | None = None,
    assembled_gain: float = 0.0,
    degraded: bool = False,
    margin: float = 0.25,
    disagreement: float = 0.5,
    gain: float = 0.3,
) -> list[str]:
    """Why (if at all) this case should go to human review. Empty list = no.

    Triggers, each independent:

    * **degraded** — a rule failed, so the score under-reports risk.
    * **borderline** — the risk sits in a band just below the elevated
      threshold, where a small perturbation flips the decision.
    * **disagreement** — the rule and model scores are far apart, so the
      explainable and the learned views conflict.
    * **assembly** — the risk rises materially when ordered chunks are
      concatenated, the signature of a payload split across retrieval chunks.
    """

    reasons: list[str] = []
    if degraded:
        reasons.append("a rule failed on this input; the score under-reports risk")

    loose = thresholds.get("fpr=0.01")
    if loose is not None and loose * (1.0 - margin) <= risk < loose:
        reasons.append(
            f"risk {risk:.3f} sits just below the elevated threshold {loose:.3f}"
        )

    if (
        rule_score is not None
        and model_score is not None
        and abs(rule_score - model_score) >= disagreement
    ):
        reasons.append(
            f"rule score {rule_score:.2f} and model score {model_score:.2f} disagree"
        )

    if assembled_gain >= gain:
        reasons.append(
            f"risk rises by {assembled_gain:.2f} when chunks are concatenated "
            f"(possible payload split across chunks)"
        )
    return reasons
