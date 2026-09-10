"""Action classes and the proposed action a policy decides about.

Nothing in this package can execute anything.  A :class:`ProposedAction` is a
description of what an agent *says* it wants to do -- a tool name and its
arguments as data -- and the policy returns another piece of data saying whether
that would be permitted.  There is no callable anywhere in the path, which is
the structural guarantee behind the plan's "no automatic execution of sensitive
actions".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["ActionCategory", "Outcome", "ProposedAction"]


class ActionCategory(str, Enum):
    """What class of effect a tool can have, at its worst.

    A tool is classified by its most damaging possible effect, not its typical
    one: ``read_file`` is ``SENSITIVE_READ`` because a path can point at a
    credential file, even though it usually reads ordinary text.
    """

    READ_ONLY = "read_only"
    SENSITIVE_READ = "sensitive_read"
    EXTERNAL_SEND = "external_send"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    #: Actions that raise the agent's own privilege or grant access to others
    #: (role grants, admin elevation, disabling authentication, impersonation).
    #: Treated as the most severe class because it widens every later action.
    PRIVILEGE_ESCALATION = "privilege_escalation"

    @classmethod
    def coerce(cls, value: Any) -> ActionCategory:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(
                f"unknown action category {value!r}; expected one of "
                f"{[member.value for member in cls]}"
            ) from exc


class Outcome(str, Enum):
    """What the policy permits.  Ordered from most to least permissive."""

    ALLOW = "allow"
    ISOLATE = "isolate"
    CONFIRM = "confirm"
    BLOCK = "block"

    @classmethod
    def coerce(cls, value: Any) -> Outcome:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(
                f"unknown outcome {value!r}; expected one of "
                f"{[member.value for member in cls]}"
            ) from exc

    @property
    def requires_human(self) -> bool:
        return self in (Outcome.CONFIRM, Outcome.BLOCK)

    @property
    def permits_action(self) -> bool:
        """True only when the action may proceed without a human.

        ``ISOLATE`` permits the action but not the context that proposed it:
        the flagged text is stripped before the model continues.
        """

        return self in (Outcome.ALLOW, Outcome.ISOLATE)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """A tool call an agent has proposed but not performed.

    ``arguments`` is carried as opaque data for the audit trail.  The policy
    reads the tool name and, optionally, an explicitly supplied category; it
    never interprets the arguments, because argument-level reasoning would be a
    second detector and would need its own evaluation.
    """

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: Set when the caller already knows the class (e.g. from a tool manifest).
    #: When absent, the policy looks the tool up in its configuration.
    category: ActionCategory | None = None
    #: Free-text description shown in the audit trail.
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "category": self.category.value if self.category else None,
            "description": self.description,
        }
