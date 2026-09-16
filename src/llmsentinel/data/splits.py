"""Deterministic, leakage-free splitting.

Two grouping keys have to be respected at once:

* the **content family** -- payload template, distractor, or hard-negative id;
* the **host document** -- the passage or tool response the content sits in.

A record whose payload family is in ``test`` but whose host document is in
``train`` leaks: the model has already seen most of the characters of that
record.  The reverse leaks too.

The splitter therefore assigns *every* key -- content families and host
documents alike -- from one global namespace, and then keeps only the records
whose two keys landed in the same split.  Records that straddle a boundary are
dropped and counted, which costs data but makes the guarantee trivially
checkable: :mod:`llmsentinel.data.leakage` re-derives it from the corpus alone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_SEED
from ..schema import CorpusRecord, Split

__all__ = ["SplitConfig", "SplitManifest", "apply_splits", "assign_group_splits", "host_group_of"]


@dataclass(frozen=True, slots=True)
class SplitConfig:
    train: float = 0.70
    dev: float = 0.15
    test: float = 0.15
    seed: int = DEFAULT_SEED
    #: When True, benchmark sources (everything but the builtin seed) are split
    #: at the level of connected (payload-family + host) components, with the
    #: components stratified by label within each source. This guarantees every
    #: source contributes both labels to dev and test -- fixing the confound where
    #: a source's positives all landed in one split -- and drops no benchmark
    #: record to a straddled boundary. The builtin seed keeps the per-key hash
    #: assignment its generator plans against, so it is unaffected.
    stratify_by_source: bool = False

    def __post_init__(self) -> None:
        total = self.train + self.dev + self.test
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"split ratios must sum to 1.0, got {total}")

    @property
    def ratios(self) -> tuple[tuple[Split, float], ...]:
        return ((Split.TRAIN, self.train), (Split.DEV, self.dev), (Split.TEST, self.test))


@dataclass(slots=True)
class SplitManifest:
    """Everything needed to reproduce or audit a split."""

    seed: int
    ratios: dict[str, float]
    assignments: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    dropped_cross_group: int = 0
    dropped_examples: list[str] = field(default_factory=list)
    corpus_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "ratios": self.ratios,
            "counts": self.counts,
            "dropped_cross_group": self.dropped_cross_group,
            "dropped_examples": self.dropped_examples[:20],
            "corpus_digest": self.corpus_digest,
            "assignments": self.assignments,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> SplitManifest:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            seed=payload["seed"],
            ratios=payload["ratios"],
            assignments=payload.get("assignments", {}),
            counts=payload.get("counts", {}),
            dropped_cross_group=payload.get("dropped_cross_group", 0),
            dropped_examples=payload.get("dropped_examples", []),
            corpus_digest=payload.get("corpus_digest", ""),
        )


def host_group_of(record: CorpusRecord) -> str:
    """The record's host-document key, falling back to its content key."""

    value = record.extra.get("host_group")
    return str(value) if value else record.group_id


def _stratum(key: str) -> str:
    """Keys are stratified by kind so each split keeps the same key mixture."""

    return key.split(":", 1)[0] if ":" in key else "other"


def split_of_key(key: str, config: SplitConfig) -> Split:
    """Deterministic split for one grouping key.

    Assignment is a pure function of ``(seed, key)`` -- a hash mapped onto the
    ratio intervals -- and deliberately *not* a shuffle of the key list.  Two
    components need the same answer: the seed-corpus generator, which pairs
    payloads with hosts inside a split, and the splitter, which re-derives the
    assignment from the written corpus.  A shuffle-based assignment depends on
    the exact set of keys present, so a family that happened to emit no record
    would silently shift every other key into a different split.  Hashing is
    stable under any change to the key set, which is what makes the two
    derivations agree and the leakage audit meaningful.

    The cost is that proportions hold only in expectation.  With the key counts
    in this project (tens of families, tens of host documents) the realised
    proportions are reported in the corpus card, and the split manifest records
    them exactly.
    """

    digest = hashlib.sha256(f"{config.seed}|{key}".encode()).digest()
    position = int.from_bytes(digest[:8], "big") / float(1 << 64)
    if position < config.train:
        return Split.TRAIN
    if position < config.train + config.dev:
        return Split.DEV
    return Split.TEST


def assign_group_splits(keys: Iterable[str], config: SplitConfig) -> dict[str, Split]:
    """Assign every grouping key to exactly one split."""

    return {key: split_of_key(key, config) for key in sorted(set(keys))}


#: The builtin seed keeps per-key hash assignment (its generator plans against
#: it); other sources are eligible for component-level source stratification.
_HASH_SOURCE = "builtin"


def _quota_counts(n: int, config: SplitConfig) -> tuple[int, int, int]:
    """Split a count of items into (train, dev, test), guaranteeing at least one
    dev and one test item once there are enough to go round."""

    if n <= 0:
        return 0, 0, 0
    if n == 1:
        return 1, 0, 0
    if n == 2:
        return 1, 1, 0
    n_test = max(1, round(n * config.test))
    n_dev = max(1, round(n * config.dev))
    while n_test + n_dev >= n:  # leave at least one for train
        if n_test >= n_dev and n_test > 1:
            n_test -= 1
        elif n_dev > 1:
            n_dev -= 1
        else:
            break
    return n - n_dev - n_test, n_dev, n_test


def _stratified_assignment(
    records: Sequence[CorpusRecord], config: SplitConfig
) -> dict[str, Split]:
    """Assign grouping keys to splits, stratifying benchmark sources by
    label-balanced connected components (see :attr:`SplitConfig.stratify_by_source`)."""

    from collections import defaultdict

    by_source: dict[str, list[CorpusRecord]] = defaultdict(list)
    for record in records:
        by_source[record.source_dataset].append(record)

    assignment: dict[str, Split] = {}
    for source, recs in by_source.items():
        if source == _HASH_SOURCE:
            for record in recs:
                for key in (record.group_id, host_group_of(record)):
                    assignment[key] = split_of_key(key, config)
            continue

        # Union payload-family and host keys into components so a kept record
        # never straddles: both of its keys share a component, hence a split.
        roots = _component_roots(
            (record.group_id, host_group_of(record)) for record in recs
        )
        members: dict[str, list[CorpusRecord]] = defaultdict(list)
        for record in recs:
            members[roots[record.group_id]].append(record)

        # Split components by label, each ordered by a stable per-component hash
        # so the quota slice is deterministic but uncorrelated with label or size.
        positive = sorted(
            (c for c, rs in members.items() if any(r.y for r in rs)),
            key=lambda c: _component_hash(source, c, config.seed),
        )
        benign = sorted(
            (c for c, rs in members.items() if not any(r.y for r in rs)),
            key=lambda c: _component_hash(source, c, config.seed),
        )

        for comp_list in (positive, benign):
            n_train, n_dev, _n_test = _quota_counts(len(comp_list), config)
            for index, comp in enumerate(comp_list):
                if index < n_train:
                    split = Split.TRAIN
                elif index < n_train + n_dev:
                    split = Split.DEV
                else:
                    split = Split.TEST
                for record in members[comp]:
                    for key in (record.group_id, host_group_of(record)):
                        assignment[key] = split
    return assignment


def _component_roots(edges: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Union-find over (key_a, key_b) edges; returns each key's component root."""

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for a, b in edges:
        parent[find(a)] = find(b)
    return {key: find(key) for key in parent}


def _component_hash(source: str, component: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}|{source}|{component}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def apply_splits(
    records: Sequence[CorpusRecord], config: SplitConfig | None = None
) -> tuple[list[CorpusRecord], SplitManifest]:
    """Assign splits and drop records that straddle two splits."""

    config = config or SplitConfig()

    if config.stratify_by_source:
        assignments = _stratified_assignment(records, config)
        return _apply_assignment(records, assignments, config)

    keys: list[str] = []
    for record in records:
        keys.append(record.group_id)
        keys.append(host_group_of(record))

    assignments = assign_group_splits(keys, config)
    return _apply_assignment(records, assignments, config)


def _apply_assignment(
    records: Sequence[CorpusRecord],
    assignments: dict[str, Split],
    config: SplitConfig,
) -> tuple[list[CorpusRecord], SplitManifest]:
    """Keep records whose content and host keys share a split; build the manifest."""

    manifest = SplitManifest(
        seed=config.seed,
        ratios={"train": config.train, "dev": config.dev, "test": config.test},
        assignments={key: split.value for key, split in sorted(assignments.items())},
    )

    kept: list[CorpusRecord] = []
    for record in records:
        content_split = assignments[record.group_id]
        host_split = assignments[host_group_of(record)]
        if content_split is not host_split:
            manifest.dropped_cross_group += 1
            if len(manifest.dropped_examples) < 20:
                manifest.dropped_examples.append(
                    f"{record.record_id} ({record.group_id} -> {content_split.value}, "
                    f"{host_group_of(record)} -> {host_split.value})"
                )
            continue
        kept.append(record.with_split(content_split))

    for record in kept:
        assert record.split is not None
        key = f"{record.split.value}/{'injection' if record.y else 'benign'}"
        manifest.counts[key] = manifest.counts.get(key, 0) + 1
    manifest.counts["total"] = len(kept)
    manifest.corpus_digest = corpus_digest(kept)
    return kept, manifest


def corpus_digest(records: Sequence[CorpusRecord]) -> str:
    """Content hash of a corpus, used as the ``data_version`` in experiment logs.

    Hashes the full serialised record -- text, label, channel, attack type,
    spans, host task, json path, split and id -- not just the id. An earlier
    version hashed ids alone, so editing a record's text without changing its id
    left the reported ``data_version`` unchanged; that is the bug this closes.
    The digest value therefore differs from ids-only digests logged before
    2026-09-10, which is expected and noted in the experiment log.
    """

    digest = hashlib.sha256()
    for line in sorted(record.to_json() for record in records):
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()[:16]
