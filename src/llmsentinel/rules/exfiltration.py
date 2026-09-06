"""Exfiltration rule: an outward action, a sensitive object, and a destination.

Any one of the three ingredients on its own is ordinary English:

* "send the report" -- an action with no sensitive object,
* "your API key is shown in the dashboard" -- an object with no action,
* "https://docs.example.com/guide" -- a destination in every technical page.

The rule therefore scores *co-occurrence inside one sentence*, and reserves its
high scores for the full triple.  The checklist's two negative tests map onto
this directly: a URL or e-mail address without a malicious action stays low, and
action verbs without a sensitive destination stay low.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ..normalize.units import NormalizedUnit, Sentence
from .base import Rule, RuleFamily, RuleHit
from .context import ContextIndex
from .lexicons import ACTION_VERBS, DESTINATION_PATTERNS, SENSITIVE_OBJECTS, compile_named

__all__ = ["ExfiltrationRule"]

_ACTIONS = compile_named(ACTION_VERBS)
_OBJECTS = compile_named(SENSITIVE_OBJECTS)
_DESTINATIONS = compile_named(DESTINATION_PATTERNS)

#: Domains that appear in ordinary documentation and are not a plausible
#: attacker drop point on their own.
_COMMON_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "localhost",
        "github.com",
        "docs.python.org",
        "python.org",
        "wikipedia.org",
        "w3.org",
        "mozilla.org",
        "stackoverflow.com",
        "microsoft.com",
        "google.com",
        "apache.org",
    }
)

_HOST_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:https?://|@|^|\s)((?:[\w\-]+\.)+[a-z]{2,})", re.IGNORECASE
)

#: "your API key" is the reader's own credential in a tutorial; "the user's API
#: key" is somebody else's, which is what an exfiltration payload targets.
_SELF_OWNED_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:your|my|our)\b\W+(?:\w+\W+){0,2}$", re.IGNORECASE
)
_THIRD_PARTY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:the\s+)?(?:user'?s?|human'?s?|customer'?s?|their|his|her|system)\b\W+(?:\w+\W+){0,2}$",
    re.IGNORECASE,
)
_SELF_OWNED_DAMPING: Final[float] = 0.55
_THIRD_PARTY_BOOST: Final[float] = 1.15

#: Score contributions.  Tuned on train/dev only; see experiments/EXPERIMENTS.md.
_W_TRIPLE: Final[float] = 0.95
_W_ACTION_OBJECT: Final[float] = 0.62
_W_ACTION_DESTINATION: Final[float] = 0.40
_W_OBJECT_DESTINATION: Final[float] = 0.30


@dataclass(frozen=True, slots=True)
class _Match:
    name: str
    start: int
    end: int
    weight: float


class ExfiltrationRule(Rule):
    rule_id = "exfiltration.v1"
    family = RuleFamily.EXFILTRATION
    feature_names = (
        "rule.exfil.max",
        "rule.exfil.triple",
        "rule.exfil.action_object",
        "rule.exfil.action_destination",
        "rule.exfil.has_external_destination",
    )

    def apply(self, unit: NormalizedUnit, sentences: Sequence[Sentence]) -> list[RuleHit]:
        text = unit.normalized_text
        if not text:
            return []
        index = ContextIndex(text)
        scopes = sentences or [Sentence(0, text, 0, len(text))]

        hits: list[RuleHit] = []
        for sentence in scopes:
            window = sentence.text
            actions = _find(_ACTIONS, window)
            objects = _find(_OBJECTS, window)
            destinations = [d for d in _find(_DESTINATIONS, window) if not _is_common(window, d)]
            if not actions:
                continue
            if not objects and not destinations:
                continue

            score, kind = self._combine(actions, objects, destinations)
            ownership, ownership_reason = _ownership_modifier(window, objects)
            score *= ownership
            if score <= 0:
                continue

            start, end = sentence.start, sentence.end
            suppression = index.suppression(start, end)
            score = round(min(score * suppression.factor, 1.0), 4)
            if score < 0.08:
                continue

            hits.append(
                self._hit(
                    score=score,
                    start=start,
                    end=end,
                    explanation=self._explain(
                        kind,
                        actions,
                        objects,
                        destinations,
                        "; ".join(x for x in (ownership_reason, suppression.describe()) if x),
                    ),
                    text=text,
                    features={
                        "rule.exfil.triple": 1.0 if kind == "triple" else 0.0,
                        "rule.exfil.action_object": 1.0 if objects else 0.0,
                        "rule.exfil.action_destination": 1.0 if destinations else 0.0,
                        "rule.exfil.has_external_destination": float(bool(destinations)),
                    },
                    note=kind,
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:5]

    @staticmethod
    def _combine(
        actions: list[_Match], objects: list[_Match], destinations: list[_Match]
    ) -> tuple[float, str]:
        action_weight = max(match.weight for match in actions)
        object_weight = max((match.weight for match in objects), default=0.0)
        destination_weight = max((match.weight for match in destinations), default=0.0)

        if objects and destinations:
            return _W_TRIPLE * action_weight * max(object_weight, destination_weight), "triple"
        if objects:
            return _W_ACTION_OBJECT * action_weight * object_weight, "action_object"
        return _W_ACTION_DESTINATION * action_weight * destination_weight, "action_destination"

    def _explain(
        self,
        kind: str,
        actions: list[_Match],
        objects: list[_Match],
        destinations: list[_Match],
        suppression: str,
    ) -> str:
        parts = [f"action “{actions[0].name}”"]
        if objects:
            parts.append(f"sensitive object “{objects[0].name}”")
        if destinations:
            parts.append(f"external destination “{destinations[0].name}”")
        label = {
            "triple": "exfiltration pattern",
            "action_object": "sensitive-data action",
            "action_destination": "outbound action",
        }[kind]
        base = f"{label}: " + " + ".join(parts) + " in one sentence"
        return f"{base} [{suppression}]" if suppression else base


def _find(
    table: tuple[tuple[str, re.Pattern[str], float], ...], text: str
) -> list[_Match]:
    found: list[_Match] = []
    for name, pattern, weight in table:
        match = pattern.search(text)
        if match:
            found.append(_Match(name, match.start(), match.end(), weight))
    return sorted(found, key=lambda match: match.weight, reverse=True)


def _is_common(text: str, destination: _Match) -> bool:
    """Drop destinations that point at well-known documentation hosts.

    Handles bare hosts (``api.example.com/v1``) as well as full URLs and e-mail
    addresses, because API references quote all three forms.
    """

    fragment = text[destination.start : destination.end]
    for match in _HOST_RE.finditer(fragment):
        host = match.group(1).lower()
        host = host[4:] if host.startswith("www.") else host
        if host in _COMMON_DOMAINS or any(host.endswith("." + d) for d in _COMMON_DOMAINS):
            return True
    return False


def _ownership_modifier(window: str, objects: list[_Match]) -> tuple[float, str]:
    """Weight the sensitive object by *whose* secret it is.

    Tutorials talk about "your API key"; payloads talk about "the user's API
    key" or name no owner at all.  This single distinction removes a large share
    of the documentation false positives.
    """

    if not objects:
        return 1.0, ""
    prefix = window[: objects[0].start]
    if _THIRD_PARTY_RE.search(prefix):
        return _THIRD_PARTY_BOOST, "targets another party's data"
    if _SELF_OWNED_RE.search(prefix):
        return _SELF_OWNED_DAMPING, "refers to the reader's own credential"
    return 1.0, ""
