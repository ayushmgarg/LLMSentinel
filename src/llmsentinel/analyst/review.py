"""When a scan belongs in the analyst review queue.

Reuses :func:`llmsentinel.semantic.review.review_reasons` for the triggers the
project already defined (degraded rules, a score just under the elevated threshold,
rule and model scores that disagree), and adds the two that only make sense once a
verdict has been decided:

* **elevated, not high** -- the risk cleared the dev 1%-FPR point but not the 0.1%
  point, which is exactly the band where false positives concentrate;
* **unexplained** -- the detector flagged the text but no rule produced a span or a
  reason, so a reviewer has nothing to check the call against.

A high-confidence, explained detection is *not* queued: the queue is for the cases a
human can actually improve, not a copy of every alert.
"""

from __future__ import annotations

from ..semantic.review import review_reasons
from ..verdict import RiskBand

__all__ = ["review_reasons_for"]


def review_reasons_for(
    *,
    risk: float,
    band: str,
    thresholds: dict[str, float],
    flagged: bool,
    explained: bool,
    rule_score: float | None = None,
    model_score: float | None = None,
    degraded: bool = False,
) -> list[str]:
    """Reasons to send this scan to a human; an empty list means no review needed."""

    reasons = review_reasons(
        risk,
        thresholds,
        rule_score=rule_score,
        model_score=model_score,
        degraded=degraded,
    )
    if band == RiskBand.ELEVATED:
        reasons.append("elevated but not high: above the dev 1%-FPR point, below the 0.1%-FPR point")
    if flagged and not explained:
        reasons.append("flagged with no rule span or reason to check the call against")
    return list(dict.fromkeys(reasons))
