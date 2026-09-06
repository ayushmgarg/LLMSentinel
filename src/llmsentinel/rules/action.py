"""Rules for text that tries to make the agent *do* something.

``tool_invocation``
    Retrieved content telling the agent which tool or command to run.
``destructive_action``
    Deletion, security-control removal, or money movement.  These map directly
    onto the ``destructive`` and ``send`` capability classes in the policy
    layer, so a hit here changes the demo's decision, not just its score.
"""

from __future__ import annotations

from .base import RuleFamily
from .lexicons import DESTRUCTIVE_PATTERNS, TOOL_INVOCATION_PATTERNS
from .pattern_rule import PatternRule

__all__ = ["DestructiveActionRule", "ToolInvocationRule"]


class ToolInvocationRule(PatternRule):
    def __init__(self) -> None:
        super().__init__(
            rule_id="tool_invocation.v1",
            family=RuleFamily.ACTION_HIJACK,
            patterns=TOOL_INVOCATION_PATTERNS,
            feature_prefix="rule.tool",
        )


class DestructiveActionRule(PatternRule):
    def __init__(self) -> None:
        super().__init__(
            rule_id="destructive_action.v1",
            family=RuleFamily.ACTION_HIJACK,
            patterns=DESTRUCTIVE_PATTERNS,
            feature_prefix="rule.destructive",
        )
