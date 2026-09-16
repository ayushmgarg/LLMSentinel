"""The verdict: what the guard concluded, and why.

A score alone is not a usable output for this project.  A reviewer looking at a
flagged document has to be able to answer four questions without reading the
code: which bytes were flagged, where those bytes came from, which signals
fired, and how confident the system is.  :class:`Verdict` carries all four, and
it is the single object the demo, the report and any future policy layer read.

Deliberately **not** here: the action decision.  Deciding what an agent may do
is the capability policy's job (Week 3), it is deterministic, and it must not be
confused with a detector's probabilistic output.  The verdict says how risky the
text is; it never says what to do about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalize.evidence import Evidence
from .normalize.units import NormalizedUnit
from .rules.base import RuleHit, RuleReport
from .schema import Channel, Span

__all__ = ["RiskBand", "Verdict", "build_verdict"]


class RiskBand:
    """Coarse label for a score, relative to the dev-selected thresholds.

    Bands exist for display only.  They are derived from thresholds chosen on
    dev, and the boundaries are reported with every verdict so that a band can
    always be traced back to the operating point that produced it.
    """

    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"

    @staticmethod
    def of(score: float, thresholds: dict[str, float]) -> str:
        strict = thresholds.get("fpr=0.001")
        loose = thresholds.get("fpr=0.01")
        if strict is not None and score >= strict:
            return RiskBand.HIGH
        if loose is not None and score >= loose:
            return RiskBand.ELEVATED
        return RiskBand.LOW


@dataclass(slots=True)
class Verdict:
    """One scored unit of untrusted text, with full provenance and reasons."""

    # --- identity and provenance -------------------------------------------
    unit_id: str
    channel: Channel
    #: JSON path for tool responses and tool metadata; ``None`` for documents.
    json_path: str | None = None
    #: Set when this text was recovered from an encoded region of another unit.
    parent_unit_id: str | None = None
    provenance: str = ""

    # --- the answer ---------------------------------------------------------
    risk: float = 0.0
    band: str = RiskBand.LOW
    thresholds: dict[str, float] = field(default_factory=dict)
    #: Score contributed by the rules alone, kept next to the fused score so a
    #: reader can see whether a detection was explainable or model-driven.
    rule_score: float = 0.0
    model_score: float | None = None

    # --- the reasons --------------------------------------------------------
    #: Spans in the *raw* text, ready to highlight in the original input.
    flagged_spans: list[Span] = field(default_factory=list)
    rule_trace: list[str] = field(default_factory=list)
    hits: list[RuleHit] = field(default_factory=list)
    normalisation_evidence: list[Evidence] = field(default_factory=list)

    # --- health -------------------------------------------------------------
    #: True when a rule failed on this unit, so the score under-reports risk.
    degraded: bool = False
    errors: list[str] = field(default_factory=list)
    normalisation_version: str = ""

    # ------------------------------------------------------------------ views
    @property
    def explained(self) -> bool:
        """True when at least one rule can justify the score in words."""

        return bool(self.hits)

    def summary(self) -> str:
        where = self.json_path or self.channel.value
        head = f"risk {self.risk:.3f} ({self.band}) at {where}"
        if self.degraded:
            head += " [degraded: a rule failed]"
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "channel": self.channel.value,
            "json_path": self.json_path,
            "parent_unit_id": self.parent_unit_id,
            "provenance": self.provenance,
            "risk": round(self.risk, 4),
            "band": self.band,
            "thresholds": self.thresholds,
            "rule_score": round(self.rule_score, 4),
            "model_score": None if self.model_score is None else round(self.model_score, 4),
            "flagged_spans": [span.to_dict() for span in self.flagged_spans],
            "rule_trace": self.rule_trace,
            "normalisation_evidence": [item.to_dict() for item in self.normalisation_evidence],
            "degraded": self.degraded,
            "errors": self.errors,
            "normalisation_version": self.normalisation_version,
        }


def build_verdict(
    unit: NormalizedUnit,
    report: RuleReport,
    *,
    risk: float | None = None,
    model_score: float | None = None,
    thresholds: dict[str, float] | None = None,
    max_spans: int = 6,
) -> Verdict:
    """Assemble a verdict from a normalised unit and its rule report.

    Rule spans index the normalised text; they are projected back onto the raw
    text here, so a caller that highlights ``flagged_spans`` highlights the
    bytes the user actually pasted -- including the ones normalisation removed.
    """

    thresholds = dict(thresholds or {})
    final_risk = report.score if risk is None else risk

    hits = report.top_hits(max_spans)
    spans: list[Span] = []
    for hit in hits:
        raw_span = unit.to_raw_span(hit.span.start, hit.span.end, note=hit.rule_id)
        if not any(raw_span.overlaps(existing) for existing in spans):
            spans.append(raw_span)

    return Verdict(
        unit_id=unit.unit_id,
        channel=unit.channel,
        json_path=unit.json_path,
        parent_unit_id=unit.parent_unit_id,
        provenance=unit.provenance,
        risk=float(final_risk),
        band=RiskBand.of(float(final_risk), thresholds),
        thresholds=thresholds,
        rule_score=report.score,
        model_score=model_score,
        flagged_spans=spans,
        rule_trace=report.trace(),
        hits=hits,
        normalisation_evidence=list(unit.evidence),
        degraded=report.degraded,
        errors=[str(error) for error in report.errors],
        normalisation_version=unit.normalisation_version,
    )
