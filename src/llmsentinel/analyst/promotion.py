"""Gated auto-promotion of candidate rules (REMAINING_THINGS B10).

"Let the rule engine update itself from what it sees" is exactly what an attacker
wants: plant pages built around harmless common phrases, and the guard learns to fire
on everyone's documents (blinding), or on one victim's own wording (steering). Spam
filters that retrained on incoming mail were poisoned this way. So a candidate is
promoted automatically only when every gate below holds, and even then only into
the *advisory* engine -- never into the scored detector or the fusion feature vector.

Gates (``PromotionGate``):

* **human-confirmed** -- mined from reviewer-labelled injections, not only from the
  model's own unexplained detections (which include its false positives);
* **independent sources** -- the supporting cases come from at least ``min_sources``
  different source domains, so one attacker planting many pages is not enough;
* **clean on dev** -- no benign dev match, and dev precision at least
  ``min_dev_precision`` where it matched anything;
* **shadow period** -- the candidate has been run silently over at least
  ``min_shadow_scans`` recorded scans other than the ones that proposed it, with no
  hit on a scan a reviewer labelled benign;
* **rate limit** -- at most ``max_per_week`` automatic promotions in seven days.

Every promotion is a normal decision entry (reviewer ``auto-gate``) listing the
checks it passed, and ``rules rollback`` retires a candidate in one step. The set of
active advisory rules has a version (``advisory_version``) so a hit can be traced to
the rule set that produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .proposals import PROPOSALS_PATH, _write, decide_proposal, load_proposals
from .store import ScanFilter, ScanStore

__all__ = [
    "AUTO_REVIEWER",
    "PromotionGate",
    "advisory_version",
    "auto_promote",
    "check_gate",
    "record_shadow",
    "shadow_report",
]

AUTO_REVIEWER = "auto-gate"


@dataclass(frozen=True, slots=True)
class PromotionGate:
    min_sources: int = 3
    require_reviewer: bool = True
    max_dev_benign: int = 0
    min_dev_precision: float = 0.9
    min_shadow_scans: int = 50
    max_shadow_false_positives: int = 0
    max_per_week: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _label(store: ScanStore, scan_id: str) -> str | None:
    history = store.overrides(scan_id)
    return history[-1].label if history else None


def shadow_report(entry: dict[str, Any], store: ScanStore, *, limit: int = 2000) -> dict[str, Any]:
    """Run one candidate silently over recorded scans, excluding its own supporters."""

    pattern = re.compile(str(entry["pattern"]), re.IGNORECASE | re.MULTILINE)
    supporters = set(entry.get("scan_ids") or [])
    counts = {
        "scanned": 0,
        "hits": 0,
        "hits_reviewed_injection": 0,
        "false_positives": 0,  # hits on scans a reviewer labelled benign
        "hits_unreviewed_flagged": 0,
        "hits_unreviewed_unflagged": 0,
    }
    for record in store.list(ScanFilter(kind="content"), limit=limit):
        if not record.text or record.scan_id in supporters:
            continue
        counts["scanned"] += 1
        if not pattern.search(record.text):
            continue
        counts["hits"] += 1
        label = _label(store, record.scan_id)
        if label == "benign":
            counts["false_positives"] += 1
        elif label == "injection":
            counts["hits_reviewed_injection"] += 1
        elif record.flagged:
            counts["hits_unreviewed_flagged"] += 1
        else:
            counts["hits_unreviewed_unflagged"] += 1
    return {**counts, "at": _now().isoformat(timespec="seconds"), "limit": limit}


def record_shadow(candidate_id: str, report: dict[str, Any], *, path: str | Path = PROPOSALS_PATH) -> dict[str, Any]:
    """Append a shadow report to a proposal (reports accumulate; none is rewritten)."""

    path = Path(path)
    proposals = load_proposals(path)
    for entry in proposals:
        if str(entry.get("candidate_id")) == candidate_id:
            entry.setdefault("shadow_reports", []).append(report)
            _write(path, proposals)
            return entry
    raise KeyError(f"no proposal {candidate_id!r}")


def _recent_auto_promotions(proposals: list[dict[str, Any]], now: datetime) -> int:
    since = now - timedelta(days=7)
    count = 0
    for entry in proposals:
        for decision in entry.get("decisions") or []:
            if decision.get("reviewer") != AUTO_REVIEWER or decision.get("status") != "approved":
                continue
            try:
                at = datetime.fromisoformat(str(decision.get("at")))
            except ValueError:
                continue
            if at >= since:
                count += 1
    return count


def check_gate(
    entry: dict[str, Any],
    store: ScanStore,
    gate: PromotionGate,
    *,
    recent_promotions: int = 0,
) -> list[tuple[str, bool, str]]:
    """Every gate with pass/fail and the evidence behind it."""

    checks: list[tuple[str, bool, str]] = []
    checks.append(("still proposed", entry.get("status") == "proposed", f"status {entry.get('status')}"))
    provenance = entry.get("provenance") or []
    checks.append(
        (
            "human-confirmed",
            ("reviewer" in provenance) or not gate.require_reviewer,
            f"provenance {', '.join(provenance) or 'none'}",
        )
    )
    domains = set()
    for scan_id in entry.get("scan_ids") or []:
        record = store.get(scan_id)
        if record is not None:
            domains.add(record.source_domain or record.source or "unknown")
    checks.append(
        (
            "independent sources",
            len(domains) >= gate.min_sources,
            f"{len(domains)} source domain(s), need {gate.min_sources}",
        )
    )
    dev = entry.get("dev") or {}
    checks.append(("dev evaluated", bool(dev.get("available")), str(dev.get("reason") or "dev split read")))
    benign = dev.get("benign_matched")
    checks.append(
        (
            "clean on dev",
            benign is not None and benign <= gate.max_dev_benign,
            f"{benign} benign dev match(es), allowed {gate.max_dev_benign}",
        )
    )
    precision = dev.get("precision")
    checks.append(
        (
            "dev precision",
            precision is None or precision >= gate.min_dev_precision,
            "no dev match" if precision is None else f"{precision:.3f}, need {gate.min_dev_precision}",
        )
    )
    reports = entry.get("shadow_reports") or []
    latest = reports[-1] if reports else None
    checks.append(
        (
            "shadow period",
            latest is not None and latest["scanned"] >= gate.min_shadow_scans,
            "no shadow run" if latest is None else f"{latest['scanned']} scan(s), need {gate.min_shadow_scans}",
        )
    )
    checks.append(
        (
            "no shadow false positive",
            latest is not None and latest["false_positives"] <= gate.max_shadow_false_positives,
            "no shadow run" if latest is None else f"{latest['false_positives']} hit(s) on reviewer-benign scans",
        )
    )
    checks.append(
        (
            "rate limit",
            recent_promotions < gate.max_per_week,
            f"{recent_promotions} automatic promotion(s) in 7 days, limit {gate.max_per_week}",
        )
    )
    return checks


def auto_promote(
    store: ScanStore,
    *,
    path: str | Path = PROPOSALS_PATH,
    gate: PromotionGate | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Promote every proposed candidate that passes every gate; report all of them."""

    gate = gate or PromotionGate()
    now = now or _now()
    results: list[dict[str, Any]] = []
    for entry in load_proposals(path):
        if entry.get("status") != "proposed":
            continue
        recent = _recent_auto_promotions(load_proposals(path), now)
        checks = check_gate(entry, store, gate, recent_promotions=recent)
        passed = all(ok for _, ok, _ in checks)
        results.append(
            {
                "candidate_id": entry["candidate_id"],
                "phrase": entry.get("phrase"),
                "promoted": passed and not dry_run,
                "passed": passed,
                "checks": [{"check": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
            }
        )
        if passed and not dry_run:
            decide_proposal(
                str(entry["candidate_id"]),
                status="approved",
                reviewer=AUTO_REVIEWER,
                rationale="Passed every promotion gate: " + "; ".join(f"{n} ({d})" for n, _, d in checks),
                path=path,
            )
    return results


def advisory_version(path: str | Path = PROPOSALS_PATH) -> str:
    """Short digest of the active advisory rule set (id, pattern, weight, family)."""

    active = sorted(
        (str(e["candidate_id"]), str(e["pattern"]), float(e["weight"]), str(e.get("family")))
        for e in load_proposals(path)
        if e.get("status") == "approved"
    )
    return hashlib.sha256(json.dumps(active).encode("utf-8")).hexdigest()[:12]
