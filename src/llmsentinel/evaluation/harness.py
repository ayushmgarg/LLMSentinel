"""Evaluation harness: one path from corpus to comparable numbers.

The protocol is enforced here rather than left to discipline:

* every system is fitted on **train** only;
* operating thresholds are chosen on **dev** only;
* **test** is scored once, with the dev thresholds, and only when the caller
  explicitly asks for it -- so an accidental peek is impossible in a normal run;
* the realised false-positive rate on test is reported next to the target, since
  a dev threshold does not carry its budget across splits.

Every result carries the corpus digest and the seed, so a number in the report
can be traced back to the exact data that produced it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_SEED, TARGET_FPRS
from ..models.base import Scorer, timed_scores
from ..paths import CORPUS_PATH, RESULTS_DIR
from ..schema import CorpusRecord, Split, read_jsonl
from .metrics import BinaryMetrics, evaluate_scores

__all__ = [
    "SystemResult",
    "load_splits",
    "per_dataset_table",
    "results_table",
    "run_system",
    "run_systems",
    "save_results",
]


def load_splits(path: str | Path | None = None) -> dict[str, list[CorpusRecord]]:
    """Load the built corpus grouped by split."""

    records = read_jsonl(Path(path) if path else CORPUS_PATH)
    grouped: dict[str, list[CorpusRecord]] = {split.value: [] for split in Split}
    for record in records:
        if record.split is not None:
            grouped[record.split.value].append(record)
    return grouped


@dataclass(slots=True)
class SystemResult:
    """Dev and (optionally) test metrics for one system."""

    name: str
    dev: BinaryMetrics
    test: BinaryMetrics | None = None
    config: dict[str, Any] = field(default_factory=dict)
    data_version: str = ""
    seed: int = DEFAULT_SEED

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "config": self.config,
            "data_version": self.data_version,
            "seed": self.seed,
            "dev": self.dev.to_dict(),
            "test": self.test.to_dict() if self.test else None,
        }

    @property
    def warnings(self) -> list[str]:
        return list(self.dev.warnings) + list(self.test.warnings if self.test else [])


def _fields(records: Sequence[CorpusRecord]) -> dict[str, list[Any]]:
    return {
        "y_true": [record.y for record in records],
        "is_hard_negative": [record.is_hard_negative for record in records],
        "channels": [record.channel.value for record in records],
        "source_datasets": [record.source_dataset for record in records],
        "attack_types": [record.attack_type.value for record in records],
    }


def run_system(
    system: Scorer,
    splits: dict[str, Sequence[CorpusRecord]],
    *,
    fit: bool = True,
    include_test: bool = False,
    bootstrap: int = 0,
    seed: int = DEFAULT_SEED,
    data_version: str = "",
    measure_latency: bool = True,
) -> SystemResult:
    """Fit on train, select thresholds on dev, optionally score test once."""

    train = list(splits.get("train", []))
    dev = list(splits.get("dev", []))
    test = list(splits.get("test", []))
    if not dev:
        raise ValueError("dev split is empty; thresholds cannot be selected")

    if fit and train:
        system.fit(train)

    if measure_latency and not getattr(system, "scores_from_cache", False):
        timed = timed_scores(system, dev, batch=1)
        dev_scores, latencies = timed.scores, timed.latencies_ms
    else:
        dev_scores, latencies = system.score(dev), None

    dev_metrics = evaluate_scores(
        system=system.name,
        split="dev",
        y_score=dev_scores,
        target_fprs=TARGET_FPRS,
        latencies_ms=latencies,
        bootstrap=bootstrap,
        seed=seed,
        **_fields(dev),
    )

    test_metrics: BinaryMetrics | None = None
    if include_test:
        if not test:
            raise ValueError("test split is empty")
        test_metrics = evaluate_scores(
            system=system.name,
            split="test",
            y_score=system.score(test),
            target_fprs=TARGET_FPRS,
            thresholds=dev_metrics.thresholds,
            bootstrap=bootstrap,
            seed=seed,
            **_fields(test),
        )

    return SystemResult(
        name=system.name,
        dev=dev_metrics,
        test=test_metrics,
        config=system.describe(),
        data_version=data_version,
        seed=seed,
    )


def run_systems(
    systems: Sequence[Scorer],
    splits: dict[str, Sequence[CorpusRecord]],
    **kwargs: Any,
) -> list[SystemResult]:
    return [run_system(system, splits, **kwargs) for system in systems]


# --------------------------------------------------------------------- output
def results_table(results: Sequence[SystemResult], split: str = "dev") -> str:
    """Markdown comparison table for one split."""

    rows: list[list[str]] = []
    for result in results:
        metrics = result.dev if split == "dev" else result.test
        if metrics is None:
            continue
        cells = [
            metrics.system,
            f"{metrics.auprc:.3f}",
            f"{metrics.auroc:.3f}",
        ]
        for key in metrics.tpr_at_fpr:
            achieved = metrics.fpr_achieved.get(key, float("nan"))
            flag = " OVER" if metrics.fpr_budget_exceeded.get(key) else ""
            cells.append(f"{metrics.tpr_at_fpr[key]:.3f} ({achieved:.4f}{flag})")
        cells.append(
            ", ".join(f"{value:.3f}" for value in metrics.hard_negative_fpr.values()) or "n/a"
        )
        cells.append(
            f"{metrics.latency_ms.get('mean', float('nan')):.1f} / "
            f"{metrics.latency_ms.get('p95', float('nan')):.1f}"
            if metrics.latency_ms
            else "n/a"
        )
        rows.append(cells)

    if not rows:
        return f"_no results for split {split}_"

    first = next(r.dev if split == "dev" else r.test for r in results if (r.dev if split == "dev" else r.test))
    headers = ["system", "AUPRC", "AUROC"]
    headers += [f"TPR@{key} (realised FPR)" for key in first.tpr_at_fpr]
    headers += ["hard-neg FPR", "latency ms mean/p95"]

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    lines.append("")
    lines.append(
        f"_Split `{split}`: {first.n} records, {first.positives} injection "
        f"({first.positive_rate:.1%} positive). Realised FPR is shown in brackets; "
        f"`OVER` marks an operating point whose false-positive budget was not met._"
    )
    return "\n".join(lines)


def per_dataset_table(results: Sequence[SystemResult], split: str = "dev") -> str:
    """Per-source-dataset AUPRC for each system, so a combined-corpus headline
    cannot hide that one source carries it. ``n/a`` marks a source with too few
    of either class to compute AUPRC on this split."""

    datasets: list[str] = []
    for result in results:
        metrics = result.dev if split == "dev" else result.test
        if metrics is None:
            continue
        for name in metrics.per_dataset:
            if name not in datasets:
                datasets.append(name)
    datasets.sort()
    if not datasets:
        return f"_no per-dataset metrics for split {split}_"

    support = {}
    headers = ["system", *datasets]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for result in results:
        metrics = result.dev if split == "dev" else result.test
        if metrics is None:
            continue
        cells = [result.name]
        for name in datasets:
            entry = metrics.per_dataset.get(name, {})
            support[name] = (int(entry.get("n", 0)), int(entry.get("positives", 0)))
            cells.append(f"{entry['auprc']:.3f}" if "auprc" in entry else "n/a")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "_Per-source AUPRC on `" + split + "`; support (n, positives): "
        + ", ".join(f"{name} {n}/{pos}" for name, (n, pos) in sorted(support.items()))
        + "._"
    )
    return "\n".join(lines)


def save_results(
    results: Sequence[SystemResult], path: str | Path | None = None
) -> Path:
    target = Path(path) if path else RESULTS_DIR / "results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target
