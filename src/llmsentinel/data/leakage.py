"""Leakage checks, re-derived from the corpus rather than trusted from the build.

The split code already guarantees these properties by construction.  These
checks exist because "guaranteed by construction" is worth nothing in a report
unless it is verified independently, and because a hand-edited corpus file or a
new loader can break the guarantee without touching the splitter.

Every check returns findings rather than raising, so ``llmsentinel corpus check``
can report all problems at once.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..schema import CorpusRecord
from .splits import host_group_of

__all__ = ["LeakageReport", "check_leakage", "normalised_text_key"]


@dataclass(slots=True)
class LeakageReport:
    """Outcome of the leakage audit."""

    group_violations: list[str] = field(default_factory=list)
    host_violations: list[str] = field(default_factory=list)
    duplicate_texts: list[str] = field(default_factory=list)
    near_duplicate_pairs: list[str] = field(default_factory=list)
    unsplit_records: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (
            self.group_violations
            or self.host_violations
            or self.duplicate_texts
            or self.near_duplicate_pairs
            or self.unsplit_records
        )

    def summary(self) -> str:
        if self.ok:
            return (
                f"leakage checks passed: {self.stats.get('records', 0)} records, "
                f"{self.stats.get('content_groups', 0)} content groups, "
                f"{self.stats.get('host_groups', 0)} host groups"
            )
        parts = []
        if self.group_violations:
            parts.append(f"{len(self.group_violations)} content groups cross splits")
        if self.host_violations:
            parts.append(f"{len(self.host_violations)} host groups cross splits")
        if self.duplicate_texts:
            parts.append(f"{len(self.duplicate_texts)} duplicate texts across splits")
        if self.near_duplicate_pairs:
            parts.append(f"{len(self.near_duplicate_pairs)} near-duplicate pairs across splits")
        if self.unsplit_records:
            parts.append(f"{len(self.unsplit_records)} records without a split")
        return "LEAKAGE: " + "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "group_violations": self.group_violations[:50],
            "host_violations": self.host_violations[:50],
            "duplicate_texts": self.duplicate_texts[:50],
            "near_duplicate_pairs": self.near_duplicate_pairs[:50],
            "unsplit_records": self.unsplit_records[:50],
            "stats": self.stats,
        }


def normalised_text_key(text: str) -> str:
    """Whitespace- and case-insensitive key used for duplicate detection."""

    return hashlib.sha1(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


def _shingles(text: str, size: int = 5) -> set[str]:
    tokens = " ".join(text.lower().split()).split(" ")
    if len(tokens) < size:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def check_leakage(
    records: Sequence[CorpusRecord], *, near_duplicate_threshold: float = 0.85
) -> LeakageReport:
    """Audit a built corpus for the four ways a split can leak."""

    report = LeakageReport()
    group_splits: dict[str, set[str]] = {}
    host_splits: dict[str, set[str]] = {}
    text_splits: dict[str, set[str]] = {}
    text_examples: dict[str, str] = {}

    for record in records:
        if record.split is None:
            report.unsplit_records.append(record.record_id)
            continue
        split = record.split.value
        group_splits.setdefault(record.group_id, set()).add(split)
        host_splits.setdefault(host_group_of(record), set()).add(split)
        key = normalised_text_key(record.raw_text)
        text_splits.setdefault(key, set()).add(split)
        text_examples.setdefault(key, record.record_id)

    for group, splits in sorted(group_splits.items()):
        if len(splits) > 1:
            report.group_violations.append(f"{group}: {sorted(splits)}")
    for host, splits in sorted(host_splits.items()):
        if len(splits) > 1:
            report.host_violations.append(f"{host}: {sorted(splits)}")
    for key, splits in sorted(text_splits.items()):
        if len(splits) > 1:
            report.duplicate_texts.append(f"{text_examples[key]}: {sorted(splits)}")

    report.near_duplicate_pairs = _near_duplicates(records, near_duplicate_threshold)

    report.stats = {
        "records": len(records),
        "content_groups": len(group_splits),
        "host_groups": len(host_splits),
        "unique_texts": len(text_splits),
        "near_duplicate_threshold": near_duplicate_threshold,
    }
    return report


def _near_duplicates(records: Sequence[CorpusRecord], threshold: float) -> list[str]:
    """Jaccard check on 5-gram shingles, restricted to cross-split pairs.

    The comparison is limited to records that share a length bucket, which keeps
    the check well under a second on corpora of this size while still catching
    the realistic failure: the same host document with a different payload
    appearing on both sides of the split.
    """

    buckets: dict[int, list[tuple[CorpusRecord, set[str]]]] = {}
    for record in records:
        if record.split is None:
            continue
        shingles = _shingles(record.raw_text)
        bucket = len(record.raw_text) // 200
        buckets.setdefault(bucket, []).append((record, shingles))

    findings: list[str] = []
    for bucket, members in buckets.items():
        neighbours = members + buckets.get(bucket + 1, [])
        for i, (record_a, shingles_a) in enumerate(members):
            for record_b, shingles_b in neighbours[i + 1 :]:
                if record_a.split is record_b.split:
                    continue
                union = shingles_a | shingles_b
                if not union:
                    continue
                similarity = len(shingles_a & shingles_b) / len(union)
                if similarity >= threshold:
                    findings.append(
                        f"{record_a.record_id} ({record_a.split.value}) ~ "
                        f"{record_b.record_id} ({record_b.split.value}) "
                        f"jaccard={similarity:.2f}"
                    )
                    if len(findings) >= 200:
                        return findings
    return findings
