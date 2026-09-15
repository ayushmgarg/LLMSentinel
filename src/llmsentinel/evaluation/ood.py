"""Harder, out-of-distribution evaluation (checklist section 16a).

The headline (~0.98 test AUPRC) is measured on held-out records *of the same
sources* the detector was trained on. That is a legitimate in-distribution
number, but a sceptical reviewer will ask whether the model learned "prompt
injection" or "what these datasets look like". This module answers that with a
second, strictly separate protocol:

1. **Collect** every source with the hardening settings: BIPIA with raised (but
   still leakage-free) caps, InjecAgent un-capped, and the builtin seed thickened
   with the opt-in ``data/seed/hardening`` metadata set.
2. **Deduplicate** exact text across *all* sources before anything else, so no
   identical text can sit on both sides.
3. **Hold out one whole source**. None of its records are used for fitting or for
   choosing thresholds. Both directions are supported: ``injecagent`` and ``bipia``.
4. **Split the remaining pool** with the source-stratified, leakage-free
   splitter into train / dev / test ("in-distribution, hardened").
5. **Scrub the out-of-distribution set**: drop any held-out record that is a
   near-duplicate (5-gram Jaccard >= 0.85) of a train/dev record, or shares a
   grouping key with one. The counts are reported, never hidden.
6. **Evaluate** each system: fit on train, pick operating points on dev, then
   score the in-distribution test and the OOD set once each with those dev
   thresholds. A once-only ledger refuses repeat scoring on the same digests.

Prevalence matters. After exact deduplication InjecAgent has ~1,054 unique
injections but only ~16 unique benign tool responses (its clean responses are a
handful of templates reused across thousands of cases), so its OOD AUPRC is
dominated by prevalence (~0.985) and says little. Every OOD result therefore
carries its support and an ``auprc_informative`` flag, and always reports recall
at the dev operating points, which *is* meaningful on an almost all-positive set.
BIPIA held out is ~43% positive, so its AUPRC is informative.

Numbers produced here are reported *next to*, never *instead of*, the canonical
section-15 results, and a drop under distribution shift is a finding in itself.
"""

from __future__ import annotations

import datetime
import json
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_SEED, TARGET_FPRS
from ..data.build import _deduplicate
from ..data.leakage import _shingles, check_leakage
from ..data.loaders.base import Loader
from ..data.loaders.bipia import BipiaLoader
from ..data.loaders.builtin import BuiltinSeedLoader
from ..data.loaders.injecagent import InjecAgentLoader
from ..data.splits import SplitConfig, apply_splits, corpus_digest, host_group_of
from ..models.base import Scorer
from ..normalize.pipeline import Normalizer
from ..paths import PROCESSED_DIR, RESULTS_DIR, SEED_DIR
from ..schema import CorpusRecord, Split, read_jsonl, write_jsonl
from .metrics import BinaryMetrics, evaluate_scores

__all__ = [
    "HARDENING_DIR",
    "HELD_OUT_CHOICES",
    "MIN_CLASS_SUPPORT",
    "OOD_LEDGER",
    "OOD_RESULTS_DIR",
    "HardeningConfig",
    "HardeningSets",
    "OODResult",
    "aggregate_seeds",
    "auprc_informative",
    "build_hardening_sets",
    "collect_records",
    "cross_set_near_duplicates",
    "default_hardening_loaders",
    "evaluate_system",
    "hardening_dir",
    "load_hardening_sets",
    "ood_table",
    "partition_and_split",
    "record_scoring",
    "run_key",
    "scoring_allowed",
    "write_hardening_sets",
]

HARDENING_DIR = PROCESSED_DIR / "hardening"
OOD_RESULTS_DIR = RESULTS_DIR / "ood"
OOD_LEDGER = OOD_RESULTS_DIR / "test_runs.json"
HELD_OUT_CHOICES = ("injecagent", "bipia")

#: Below this many records of either class, or outside a 10-90% prevalence band,
#: AUPRC mostly measures prevalence and is flagged as not informative.
MIN_CLASS_SUPPORT = 30


@dataclass(frozen=True, slots=True)
class HardeningConfig:
    """Everything that changes the hardening corpus; recorded in its manifest.

    BIPIA caps were chosen by a structural sweep (no model involved) over hosts
    per attack, with benign and positive caps raised to 1100:

    ==============  =================  ========  ==============================
    hosts/attack    unique pos / ben   families  split positives train/dev/test
    ==============  =================  ========  ==============================
    2               300 / 779          29        210 / 40 / 50
    **4**           **600 / 779**      **29**    **420 / 120 / 60**
    8               1100 / 779         27        40 / 1060 / 0  (chains)
    16              1100 / 779         14        1100 / 0 / 0   (chains)
    ==============  =================  ========  ==============================

    More hosts per attack links every positive into one leakage component, which
    the stratified splitter must keep in a single split. Four is the largest
    leakage-free slice: 600 positives over all 29 attack families (canonical:
    350 over 18). Fully un-capped BIPIA (~165k positives vs ~1.1k benign) would
    also drown every other source.
    """

    held_out: str = "injecagent"
    bipia_max_hosts_per_attack: int = 4
    bipia_max_benign: int = 1100
    bipia_max_positive: int = 1100
    injecagent_max_benign: int = 1_000_000
    injecagent_max_positive: int = 1_000_000
    thicken_metadata: bool = True
    seed: int = DEFAULT_SEED
    near_duplicate_threshold: float = 0.85


@dataclass(slots=True)
class HardeningSets:
    """In-distribution (hardened) splits plus the held-out OOD set."""

    config: HardeningConfig
    train: list[CorpusRecord]
    dev: list[CorpusRecord]
    test: list[CorpusRecord]
    ood: list[CorpusRecord]
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def indist(self) -> list[CorpusRecord]:
        return [*self.train, *self.dev, *self.test]

    def digests(self) -> dict[str, str]:
        return {"indist": corpus_digest(self.indist), "ood": corpus_digest(self.ood)}


def hardening_dir(held_out: str, root: Path = HARDENING_DIR) -> Path:
    return Path(root) / held_out


# ------------------------------------------------------------------ building
def default_hardening_loaders(config: HardeningConfig) -> list[Loader]:
    extra = (SEED_DIR / "hardening",) if config.thicken_metadata else ()
    return [
        BuiltinSeedLoader(extra_seed_dirs=extra),
        BipiaLoader(
            max_hosts_per_attack=config.bipia_max_hosts_per_attack,
            max_benign=config.bipia_max_benign,
            max_positive=config.bipia_max_positive,
        ),
        InjecAgentLoader(
            max_benign=config.injecagent_max_benign,
            max_positive=config.injecagent_max_positive,
        ),
    ]


def collect_records(loaders: Sequence[Loader]) -> tuple[list[CorpusRecord], list[str]]:
    records: list[CorpusRecord] = []
    skipped: list[str] = []
    for loader in loaders:
        if not loader.available():
            skipped.append(loader.unavailable_reason())
            continue
        records.extend(loader.load())
    return records, skipped


def cross_set_near_duplicates(
    reference: Sequence[CorpusRecord],
    candidates: Sequence[CorpusRecord],
    threshold: float = 0.85,
) -> set[str]:
    """Ids of ``candidates`` whose 5-gram Jaccard with any ``reference`` record
    is at least ``threshold``. Length-bucketed, with a size-ratio bound (Jaccard
    can never exceed ``min/max`` of the two shingle-set sizes) to skip pairs."""

    buckets: dict[int, list[set[str]]] = {}
    for record in reference:
        buckets.setdefault(len(record.raw_text) // 200, []).append(_shingles(record.raw_text))

    def near(shingles: set[str], bucket: int) -> bool:
        size = len(shingles)
        for neighbour in (bucket - 1, bucket, bucket + 1):
            for other in buckets.get(neighbour, ()):
                small, large = sorted((size, len(other)))
                if large == 0 or small / large < threshold:
                    continue
                overlap = len(shingles & other)
                if overlap / (size + len(other) - overlap) >= threshold:
                    return True
        return False

    return {
        record.record_id
        for record in candidates
        if near(_shingles(record.raw_text), len(record.raw_text) // 200)
    }


def _keys(record: CorpusRecord) -> tuple[str, str]:
    return record.group_id, host_group_of(record)


def partition_and_split(
    records: Sequence[CorpusRecord],
    config: HardeningConfig,
    *,
    normalise: bool = True,
    skipped: Sequence[str] = (),
) -> HardeningSets:
    """Steps 2-5 of the protocol on already-collected records."""

    deduped, exact_removed = _deduplicate(list(records))
    held = [r for r in deduped if r.source_dataset == config.held_out]
    pool = [r for r in deduped if r.source_dataset != config.held_out]
    if not held:
        raise ValueError(f"held-out source {config.held_out!r} produced no records")
    if not pool:
        raise ValueError(f"nothing left to train on after holding out {config.held_out!r}")

    kept, manifest = apply_splits(pool, SplitConfig(seed=config.seed, stratify_by_source=True))
    train = [r for r in kept if r.split is Split.TRAIN]
    dev = [r for r in kept if r.split is Split.DEV]
    test = [r for r in kept if r.split is Split.TEST]

    reference = [*train, *dev]
    near = cross_set_near_duplicates(reference, held, config.near_duplicate_threshold)
    reference_keys = {key for record in reference for key in _keys(record)}
    ood: list[CorpusRecord] = []
    shared_dropped = 0
    for record in held:
        if record.record_id in near:
            continue
        if any(key in reference_keys for key in _keys(record)):
            shared_dropped += 1
            continue
        ood.append(record.with_split(Split.TEST))

    if normalise:
        normalizer = Normalizer()
        for record in [*kept, *ood]:
            normalizer.normalize_record(record)

    sets = HardeningSets(config=config, train=train, dev=dev, test=test, ood=ood)
    ood_pos = sum(r.y for r in ood)
    sets.report = {
        "config": asdict(config),
        "sizes": {"train": len(train), "dev": len(dev), "test": len(test), "ood": len(ood)},
        "ood_support": {
            "positives": ood_pos,
            "negatives": len(ood) - ood_pos,
            "prevalence": round(ood_pos / len(ood), 4) if ood else 0.0,
        },
        "exact_duplicates_removed": exact_removed,
        "pool_cross_group_dropped": manifest.dropped_cross_group,
        "ood_near_duplicates_dropped": len(near),
        "ood_shared_key_dropped": shared_dropped,
        "leakage_indist_ok": check_leakage(kept).ok,
        "skipped_sources": list(skipped),
        "counts": _counts(sets),
        "tool_metadata": _metadata_counts(sets),
        "digests": sets.digests(),
    }
    return sets


def build_hardening_sets(
    config: HardeningConfig | None = None, loaders: Sequence[Loader] | None = None
) -> HardeningSets:
    config = config or HardeningConfig()
    records, skipped = collect_records(loaders or default_hardening_loaders(config))
    return partition_and_split(records, config, skipped=skipped)


def _named_sets(sets: HardeningSets) -> tuple[tuple[str, list[CorpusRecord]], ...]:
    return (("train", sets.train), ("dev", sets.dev), ("test", sets.test), ("ood", sets.ood))


def _counts(sets: HardeningSets) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for name, records in _named_sets(sets):
        tally = Counter((r.source_dataset, r.y) for r in records)
        out[name] = {
            source: {"injection": tally[(source, 1)], "benign": tally[(source, 0)]}
            for source in sorted({s for s, _ in tally})
        }
    return out


def _metadata_counts(sets: HardeningSets) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name, records in _named_sets(sets):
        meta = [r for r in records if r.channel.value == "tool_metadata"]
        out[name] = {"injection": sum(r.y for r in meta), "benign": sum(1 - r.y for r in meta)}
    return out


# ------------------------------------------------------------------ storage
def write_hardening_sets(sets: HardeningSets, out_dir: Path | None = None) -> dict[str, Path]:
    out_dir = Path(out_dir) if out_dir else hardening_dir(sets.config.held_out)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "indist": out_dir / "indist.jsonl",
        "ood": out_dir / f"ood_{sets.config.held_out}.jsonl",
        "manifest": out_dir / "manifest.json",
    }
    write_jsonl(sets.indist, paths["indist"])
    write_jsonl(sets.ood, paths["ood"])
    paths["manifest"].write_text(json.dumps(sets.report, indent=2, sort_keys=True), encoding="utf-8")
    return paths


def load_hardening_sets(out_dir: Path) -> HardeningSets:
    out_dir = Path(out_dir)
    report = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    config = HardeningConfig(**report["config"])
    indist = read_jsonl(out_dir / "indist.jsonl")
    ood = read_jsonl(out_dir / f"ood_{config.held_out}.jsonl")
    sets = HardeningSets(
        config=config,
        train=[r for r in indist if r.split is Split.TRAIN],
        dev=[r for r in indist if r.split is Split.DEV],
        test=[r for r in indist if r.split is Split.TEST],
        ood=ood,
        report=report,
    )
    if sets.digests() != report.get("digests"):
        raise ValueError(
            f"hardening sets in {out_dir} do not match their manifest digests "
            f"({sets.digests()} vs {report.get('digests')}); rebuild with "
            f"`python scripts/ood_eval.py build`"
        )
    return sets


# ---------------------------------------------------------------- evaluation
def auprc_informative(metrics: BinaryMetrics) -> bool:
    """AUPRC is only reported as a finding when both classes have real support
    and prevalence is not so extreme that the score mostly restates it."""

    return (
        metrics.positives >= MIN_CLASS_SUPPORT
        and metrics.negatives >= MIN_CLASS_SUPPORT
        and 0.1 <= metrics.positive_rate <= 0.9
    )


@dataclass(slots=True)
class OODResult:
    system: str
    dev: BinaryMetrics
    test: BinaryMetrics
    ood: BinaryMetrics
    config: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None

    @property
    def shift(self) -> float:
        """OOD AUPRC minus in-distribution test AUPRC (negative = drop)."""

        return self.ood.auprc - self.test.auprc

    @property
    def ood_informative(self) -> bool:
        return auprc_informative(self.ood)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "seed": self.seed,
            "config": self.config,
            "dev": self.dev.to_dict(),
            "test": self.test.to_dict(),
            "ood": self.ood.to_dict(),
            "ood_support": {
                "n": self.ood.n,
                "positives": self.ood.positives,
                "negatives": self.ood.negatives,
                "prevalence": round(self.ood.positive_rate, 4),
            },
            "ood_auprc_informative": self.ood_informative,
            "ood_recall_at_dev_thresholds": self.ood.tpr_at_fpr,
            "ood_realised_fpr": self.ood.fpr_achieved,
            "shift_auprc": round(self.shift, 4),
        }


def _fields(records: Sequence[CorpusRecord]) -> dict[str, list[Any]]:
    return {
        "y_true": [r.y for r in records],
        "is_hard_negative": [r.is_hard_negative for r in records],
        "channels": [r.channel.value for r in records],
        "source_datasets": [r.source_dataset for r in records],
        "attack_types": [r.attack_type.value for r in records],
    }


def evaluate_system(
    system: Scorer,
    sets: HardeningSets,
    *,
    fit: bool = True,
    name: str | None = None,
    seed: int | None = None,
) -> OODResult:
    """Fit on train, thresholds from dev, score in-dist test and OOD once each."""

    if fit:
        system.fit(sets.train)
    label = name or system.name
    dev = evaluate_scores(
        system=label, split="dev", y_score=system.score(sets.dev),
        target_fprs=TARGET_FPRS, **_fields(sets.dev),
    )
    test = evaluate_scores(
        system=label, split="test", y_score=system.score(sets.test),
        target_fprs=TARGET_FPRS, thresholds=dev.thresholds, **_fields(sets.test),
    )
    ood = evaluate_scores(
        system=label, split=f"ood:{sets.config.held_out}", y_score=system.score(sets.ood),
        target_fprs=TARGET_FPRS, thresholds=dev.thresholds, **_fields(sets.ood),
    )
    return OODResult(system=label, dev=dev, test=test, ood=ood, config=system.describe(), seed=seed)


def aggregate_seeds(results: Sequence[OODResult]) -> dict[str, dict[str, float]]:
    """Mean / std / min / max across seeds for AUPRC and OOD recall at 1% FPR."""

    def stats(values: list[float]) -> dict[str, float]:
        return {
            "mean": round(statistics.mean(values), 4),
            "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    return {
        "dev_auprc": stats([r.dev.auprc for r in results]),
        "test_auprc": stats([r.test.auprc for r in results]),
        "ood_auprc": stats([r.ood.auprc for r in results]),
        "ood_recall_at_1pct_fpr_threshold": stats(
            [r.ood.tpr_at_fpr.get("fpr=0.01", 0.0) for r in results]
        ),
        "shift_auprc": stats([r.shift for r in results]),
    }


def ood_table(results: Sequence[OODResult]) -> str:
    """Markdown table. OOD AUPRC is marked ``n/i`` (not informative) when support
    or prevalence make it mostly a restatement of the class balance."""

    key = "fpr=0.01"
    lines = [
        "| system | dev AUPRC | in-dist test AUPRC | OOD AUPRC | shift | "
        "OOD recall @dev 1%-FPR thr | OOD realised FPR |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        informative = r.ood_informative
        ood_auprc = f"{r.ood.auprc:.3f}" + ("" if informative else " (n/i)")
        shift = f"{r.shift:+.3f}" if informative else "n/i"
        flag = " OVER" if r.ood.fpr_budget_exceeded.get(key) else ""
        lines.append(
            f"| {r.system} | {r.dev.auprc:.3f} | {r.test.auprc:.3f} | {ood_auprc} | {shift} | "
            f"{r.ood.tpr_at_fpr.get(key, 0.0):.3f} | {r.ood.fpr_achieved.get(key, float('nan')):.4f}{flag} |"
        )
    if results:
        ood = results[0].ood
        lines.append("")
        lines.append(
            f"_OOD `{ood.split}`: {ood.n} records, {ood.positives} injection / {ood.negatives} "
            f"benign (prevalence {ood.positive_rate:.1%}). Thresholds are the dev operating points; "
            f"`n/i` marks an AUPRC dominated by class balance (either class < {MIN_CLASS_SUPPORT} "
            f"or prevalence outside 10-90%)._"
        )
    return "\n".join(lines)


# -------------------------------------------------------------------- ledger
def run_key(system: str, sets: HardeningSets) -> str:
    digests = sets.digests()
    return f"{system}|{sets.config.held_out}|{digests['indist']}|{digests['ood']}"


def scoring_allowed(key: str, *, force: bool, ledger: Path = OOD_LEDGER) -> bool:
    if force or not Path(ledger).is_file():
        return True
    entries = json.loads(Path(ledger).read_text(encoding="utf-8"))
    return not any(entry.get("key") == key for entry in entries)


def record_scoring(key: str, *, forced: bool, ledger: Path = OOD_LEDGER) -> None:
    ledger = Path(ledger)
    entries = json.loads(ledger.read_text(encoding="utf-8")) if ledger.is_file() else []
    entries.append(
        {
            "key": key,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "forced": forced,
        }
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(entries, indent=2), encoding="utf-8")
