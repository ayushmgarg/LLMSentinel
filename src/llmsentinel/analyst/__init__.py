"""Analyst workflow (checklist section 17): local scan history, review queue,
verdict overrides, aggregation, manifest-change alerts and regression fixtures.

Everything here is local and advisory. The store records what the guard concluded
and what a human decided about it; it never changes a verdict after the fact and it
never executes anything. See ``docs/analyst_workflow.md``.
"""

from __future__ import annotations

from .families import families_from_trace
from .fixtures import DISCOVERED_PATH, load_fixtures, promote_to_fixture, sanitise_for_fixture
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
    "STATS_KEYS",
    "Alert",
    "Override",
    "ScanFilter",
    "ScanRecord",
    "ScanStore",
    "families_from_trace",
    "load_fixtures",
    "promote_to_fixture",
    "review_reasons_for",
    "sanitise_for_fixture",
]
