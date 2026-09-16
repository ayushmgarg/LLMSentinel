"""The capability gate: a deterministic lookup over (action class, risk band).

Division of labour, and the reason for it
-----------------------------------------
The detector is **probabilistic and advisory**.  It produces a score that is
wrong some of the time, in both directions, and the Week 2 results quantify how
often.  The policy is **deterministic and auditable**: the same action in the
same risk band always yields the same outcome, and the mapping is a data file a
reviewer can read without reading any code.

Putting the decision in the model would mean the guard's false negatives become
executed actions.  Putting it in the table means a false negative degrades to
"the confirmation prompt the operator would have seen anyway" for anything
sensitive, and to nothing at all for a destructive action, which is blocked
regardless of score.

Three invariants
----------------
1. **Nothing executes.**  :meth:`CapabilityPolicy.decide` returns a
   :class:`PolicyDecision`.  This package holds no callables, no subprocess, no
   network client; ``test_policy.py`` asserts that the decision object exposes
   no way to run anything.
2. **Failure is safe.**  An unlisted tool takes the configured fallback class
   (``sensitive_read``, not ``read_only``), and a degraded detector escalates
   the outcome one step.  No path leads to a *more* permissive result than the
   table specifies.
3. **The score never overrides the table.**  Risk selects a column; it cannot
   change what the column says.  A destructive action is blocked at risk 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..paths import PROJECT_ROOT
from ..verdict import RiskBand, Verdict
from .actions import ActionCategory, Outcome, ProposedAction

__all__ = ["DEFAULT_POLICY_PATH", "CapabilityPolicy", "PolicyDecision"]

DEFAULT_POLICY_PATH = PROJECT_ROOT / "configs" / "policy.yaml"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The outcome, and everything needed to justify it after the fact."""

    outcome: Outcome
    action: ProposedAction
    category: ActionCategory
    risk_band: str
    risk: float
    #: Outcome the table gave before any escalation.
    table_outcome: Outcome
    reasons: tuple[str, ...] = ()
    #: True when the tool was not in the policy file and the fallback applied.
    tool_was_unknown: bool = False
    #: True when the detector reported a degraded verdict for this context.
    detector_degraded: bool = False
    policy_version: int = 0

    @property
    def escalated(self) -> bool:
        return self.outcome is not self.table_outcome

    def summary(self) -> str:
        line = (
            f"{self.outcome.value.upper()} {self.action.tool_name} "
            f"({self.category.value}, risk {self.risk:.3f} = {self.risk_band})"
        )
        if self.escalated:
            line += f" [escalated from {self.table_outcome.value}]"
        return line

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "table_outcome": self.table_outcome.value,
            "escalated": self.escalated,
            "action": self.action.to_dict(),
            "category": self.category.value,
            "risk": round(self.risk, 4),
            "risk_band": self.risk_band,
            "reasons": list(self.reasons),
            "tool_was_unknown": self.tool_was_unknown,
            "detector_degraded": self.detector_degraded,
            "policy_version": self.policy_version,
        }


@dataclass(slots=True)
class _PolicyConfig:
    version: int
    tools: dict[str, ActionCategory]
    unknown_tool_category: ActionCategory
    decisions: dict[ActionCategory, dict[str, Outcome]]
    escalate_when_degraded: bool
    escalation_order: tuple[Outcome, ...]


class CapabilityPolicy:
    """Deterministic capability gate over proposed tool actions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_POLICY_PATH
        self.config = self._load(self.path)

    # ------------------------------------------------------------------ load
    @staticmethod
    def _load(path: Path) -> _PolicyConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        decisions: dict[ActionCategory, dict[str, Outcome]] = {}
        for category_name, bands in (raw.get("decisions") or {}).items():
            category = ActionCategory.coerce(category_name)
            decisions[category] = {
                str(band): Outcome.coerce(outcome) for band, outcome in bands.items()
            }

        missing = [
            category.value for category in ActionCategory if category not in decisions
        ]
        if missing:
            raise ValueError(
                f"{path}: no decision row for action class(es) {missing}. Every class "
                f"needs an explicit row -- an unmapped class would have to fall back to "
                f"a default, and a silent default is exactly what this table exists to "
                f"prevent."
            )

        required_bands = {RiskBand.LOW, RiskBand.ELEVATED, RiskBand.HIGH}
        for category, bands in decisions.items():
            absent = required_bands - set(bands)
            if absent:
                raise ValueError(
                    f"{path}: action class {category.value} has no outcome for risk "
                    f"band(s) {sorted(absent)}"
                )

        return _PolicyConfig(
            version=int(raw.get("version", 0)),
            tools={
                str(name): ActionCategory.coerce(value)
                for name, value in (raw.get("tools") or {}).items()
            },
            unknown_tool_category=ActionCategory.coerce(
                raw.get("unknown_tool_category", ActionCategory.SENSITIVE_READ)
            ),
            decisions=decisions,
            escalate_when_degraded=bool(raw.get("escalate_when_degraded", True)),
            escalation_order=tuple(
                Outcome.coerce(item)
                for item in raw.get(
                    "escalation_order", ["allow", "isolate", "confirm", "block"]
                )
            ),
        )

    # -------------------------------------------------------------- decision
    def categorise(self, action: ProposedAction) -> tuple[ActionCategory, bool]:
        """Return the action's class and whether the tool was unknown."""

        if action.category is not None:
            return action.category, False
        known = self.config.tools.get(action.tool_name)
        if known is not None:
            return known, False
        return self.config.unknown_tool_category, True

    def decide(
        self,
        action: ProposedAction,
        *,
        verdict: Verdict | None = None,
        risk: float | None = None,
        risk_band: str | None = None,
        degraded: bool | None = None,
    ) -> PolicyDecision:
        """Decide whether ``action`` may proceed in the given risk context.

        The risk context can be supplied as a :class:`~llmsentinel.verdict.Verdict`
        (the normal path) or as a band and score directly (used by tests and by
        callers that have no detector). When nothing is supplied the context is
        treated as :attr:`RiskBand.HIGH`: no evidence of safety is not evidence
        of safety.
        """

        if verdict is not None:
            band = risk_band or verdict.band
            score = verdict.risk if risk is None else risk
            is_degraded = verdict.degraded if degraded is None else degraded
        else:
            band = risk_band or RiskBand.HIGH
            score = 0.0 if risk is None else risk
            is_degraded = bool(degraded)

        if band not in (RiskBand.LOW, RiskBand.ELEVATED, RiskBand.HIGH):
            raise ValueError(f"unknown risk band {band!r}")

        category, unknown = self.categorise(action)
        table_outcome = self.config.decisions[category][band]

        reasons = [
            f"tool {action.tool_name!r} is classed {category.value}"
            + (" (not in the policy file; fallback applied)" if unknown else ""),
            f"context risk {score:.3f} falls in band {band}",
            f"policy table: {category.value} + {band} -> {table_outcome.value}",
        ]

        outcome = table_outcome
        if is_degraded and self.config.escalate_when_degraded:
            outcome = self._escalate(outcome)
            if outcome is not table_outcome:
                reasons.append(
                    "detector reported a degraded verdict, so the outcome is one "
                    f"step stricter: {outcome.value}"
                )

        return PolicyDecision(
            outcome=outcome,
            action=action,
            category=category,
            risk_band=band,
            risk=score,
            table_outcome=table_outcome,
            reasons=tuple(reasons),
            tool_was_unknown=unknown,
            detector_degraded=is_degraded,
            policy_version=self.config.version,
        )

    def _escalate(self, outcome: Outcome) -> Outcome:
        order = self.config.escalation_order
        if outcome not in order:
            return Outcome.BLOCK
        index = order.index(outcome)
        return order[min(index + 1, len(order) - 1)]

    # ------------------------------------------------------------------ misc
    def describe(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "version": self.config.version,
            "tools": len(self.config.tools),
            "unknown_tool_category": self.config.unknown_tool_category.value,
            "escalate_when_degraded": self.config.escalate_when_degraded,
            "table": {
                category.value: {band: outcome.value for band, outcome in bands.items()}
                for category, bands in self.config.decisions.items()
            },
        }

    def table_markdown(self) -> str:
        """The decision table as documentation, generated from the file itself."""

        bands = [RiskBand.LOW, RiskBand.ELEVATED, RiskBand.HIGH]
        lines = ["| action class | " + " | ".join(bands) + " |", "|---|---|---|---|"]
        for category in ActionCategory:
            row = self.config.decisions[category]
            lines.append(
                f"| {category.value} | " + " | ".join(row[band].value for band in bands) + " |"
            )
        return "\n".join(lines)

