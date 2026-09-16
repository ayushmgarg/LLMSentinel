"""Which attack families a scan *looks like*, read from the rules that fired.

This is a prediction, not ground truth: a live scan has no label, so the only
evidence of "what kind of attack" is which rule families produced hits. The names
are mapped onto the corpus attack types so aggregation reads the same way as the
evaluation tables. A scan flagged by the model with no rule to explain it is
reported as ``model_only`` rather than being guessed into a family.

The trace format is the one every :class:`~llmsentinel.rules.base.RuleHit` prints
(``[family/rule_id score] explanation``), so verdicts from the SDK and chunk
assessments from the Studio are read by the same parser.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..rules.base import RuleFamily

__all__ = ["MODEL_ONLY", "families_from_trace"]

MODEL_ONLY = "model_only"

#: Rule family -> corpus attack type. Task conflict is corroborating evidence only
#: (see the rule engine), so on its own it names no family.
_FAMILY_TO_ATTACK: dict[str, str] = {
    RuleFamily.META_INSTRUCTION: "meta_instruction",
    RuleFamily.ASSISTANT_ADDRESS: "meta_instruction",
    RuleFamily.OBFUSCATION: "obfuscation",
    RuleFamily.EXFILTRATION: "exfiltration",
    RuleFamily.ACTION_HIJACK: "action_hijack",
    RuleFamily.METADATA_POISONING: "metadata_poisoning",
}
#: Rules whose meaning is narrower than their family.
_RULE_TO_ATTACK: dict[str, str] = {
    "answer_shaping.v1": "content_manipulation",
}
_TRACE = re.compile(r"\[(?P<family>[a-z_]+)/(?P<rule>[\w.]+)\s+[0-9.]+\]")


def families_from_trace(trace: Iterable[str], *, flagged: bool = False) -> list[str]:
    """Sorted attack families implied by a rule trace.

    ``flagged`` adds :data:`MODEL_ONLY` when the scan was flagged but no rule that
    names a family fired, so a model-driven detection is visible as such.
    """

    found: set[str] = set()
    for line in trace:
        for match in _TRACE.finditer(line):
            attack = _RULE_TO_ATTACK.get(match.group("rule")) or _FAMILY_TO_ATTACK.get(match.group("family"))
            if attack:
                found.add(attack)
    if flagged and not found:
        found.add(MODEL_ONLY)
    return sorted(found)
