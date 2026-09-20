"""Analyst workflow (checklist section 17): local scan history, review queue,
verdict overrides, aggregation, manifest-change alerts, regression fixtures and candidate-rule proposals.

Everything here is local and advisory. The store records what the guard concluded
and what a human decided about it; it never changes a verdict after the fact and it
never executes anything. See ``docs/analyst_workflow.md``.
"""

from __future__ import annotations

from .families import families_from_trace
from .fixtures import DISCOVERED_PATH, load_fixtures, promote_to_fixture, sanitise_for_fixture
from .proposals import (
    PROPOSALS_PATH,
    Candidate,
    advisory_hits,
    approved_rules,
    decide_proposal,
    evaluate_candidates,
    load_proposals,
    mine_candidates,
    write_proposals,
)
from .review import review_reasons_for
from .store import (
    DEFAULT_HISTORY_PATH,
    LABELS,
    STATS_KEYS,
    Alert,
    Override,
    ScanFilter,
    ScanRecord,
    ScanStore,
)

__all__ = [
    "DEFAULT_HISTORY_PATH",
    "DISCOVERED_PATH",
    "LABELS",
    "PROPOSALS_PATH",
    "STATS_KEYS",
    "Alert",
    "Candidate",
    "Override",
    "ScanFilter",
    "ScanRecord",
    "ScanStore",
    "advisory_hits",
    "approved_rules",
    "decide_proposal",
    "evaluate_candidates",
    "families_from_trace",
    "load_fixtures",
    "load_proposals",
    "mine_candidates",
    "promote_to_fixture",
    "review_reasons_for",
    "sanitise_for_fixture",
    "write_proposals",
]
