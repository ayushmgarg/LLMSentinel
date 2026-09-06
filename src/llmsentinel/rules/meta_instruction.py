"""Rules for text that tries to re-programme the assistant.

Three related but separately ablatable rules:

``meta_instruction``
    Direct attempts to cancel or replace earlier instructions, reveal the system
    prompt, or reassign the model's role.
``secrecy_directive``
    Instructions to hide behaviour from the user.  Benign documents essentially
    never contain these, which makes the rule unusually high precision.
``assistant_address``
    Text that addresses an AI reader at all.  On its own this is weak evidence
    (a security blog addresses AI readers too), which is why its base weights
    are low and it earns its keep only inside the fusion layer.
"""

from __future__ import annotations

from .base import RuleFamily
from .lexicons import ASSISTANT_ADDRESS_PATTERNS, META_INSTRUCTION_PATTERNS, SECRECY_PATTERNS
from .pattern_rule import PatternRule

__all__ = ["AssistantAddressRule", "MetaInstructionRule", "SecrecyRule"]


class MetaInstructionRule(PatternRule):
    def __init__(self) -> None:
        super().__init__(
            rule_id="meta_instruction.v1",
            family=RuleFamily.META_INSTRUCTION,
            patterns=META_INSTRUCTION_PATTERNS,
            feature_prefix="rule.meta",
        )


class SecrecyRule(PatternRule):
    def __init__(self) -> None:
        super().__init__(
            rule_id="secrecy_directive.v1",
            family=RuleFamily.META_INSTRUCTION,
            patterns=SECRECY_PATTERNS,
            feature_prefix="rule.secrecy",
        )


class AssistantAddressRule(PatternRule):
    def __init__(self) -> None:
        super().__init__(
            rule_id="assistant_address.v1",
            family=RuleFamily.ASSISTANT_ADDRESS,
            patterns=ASSISTANT_ADDRESS_PATTERNS,
            feature_prefix="rule.address",
        )
