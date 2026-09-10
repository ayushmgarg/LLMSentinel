"""Section-12 robustness and generalisation probes, in one runnable report.

Three parts, all printed as Markdown for docs/robustness.md and the experiment
log:

1. **Perturbation robustness** — apply surface / Unicode / rewrite transforms to
   sampled injection positives and hard negatives, and report recall kept and
   false positives gained at the rules-only dev operating point. Failures are
   listed, not hidden.
2. **Cross-channel transfer** — train the lexical baseline on one channel and
   test on another (disjoint by construction), to see how much a detector keyed
   to one channel generalises to the others.
3. **Metadata vs tool-response scanning** — AUPRC on each tool channel
   separately, because a number pooled across them hides that manifests and
   responses behave differently.

Deterministic and offline. Pass --checkpoint to add the transformer to part 1.

    python scripts/robustness_suite.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from llmsentinel.evaluation.metrics import average_precision
from llmsentinel.models import RulesScorer, TfidfBaseline
from llmsentinel.models.base import Scorer
from llmsentinel.paths import CORPUS_PATH, RESULTS_DIR
from llmsentinel.robustness import run_suite
from llmsentinel.schema import Channel, CorpusRecord, read_jsonl

CHANNELS = ("rag_document", "tool_response", "tool_metadata")


def _rules_threshold() -> float:
    path = RESULTS_DIR / "results_dev.json"
    if path.is_file():
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if entry.get("name") == "rules-only":
                return float(entry["dev"]["thresholds"].get("fpr=0.01", 0.875))
    return 0.875


def _perturbation_report(records: Sequence[CorpusRecord], threshold: float, checkpoint: str | None) -> None:
    print("## 1. Perturbation robustness (rules-only)\n")
    systems: list[Scorer] = [RulesScorer()]
    if checkpoint:
        from pathlib import Path

        from llmsentinel.models.transformer import TransformerScorer, torch_available

        if Path(checkpoint).is_dir() and torch_available():
            systems.append(TransformerScorer.load(checkpoint))

    for scorer in systems:
        suite = run_suite(records, scorer, threshold=threshold, seed=0)
        base = suite.baseline
        print(
            f"### {scorer.name}  (threshold {suite.threshold:.4f}, "
            f"{suite.n_pos} positives, {suite.n_neg} hard negatives)\n"
        )
        print("| transform | group | recall kept | mean risk | hard-neg FPR |")
        print("|---|---|---|---|---|")
        for r in suite.results:
            print(
                f"| {r.name} | {r.group} | {r.pos_detection:.2f} | "
                f"{r.pos_mean_risk:.3f} | {r.neg_fpr:.2f} |"
            )
        failures = suite.failures()
        print(
            f"\nbaseline recall {base.pos_detection:.2f}, baseline hard-neg FPR "
            f"{base.neg_fpr:.2f}. "
            + (
                f"**Failures** (recall drop >0.10 or FPR rise >0.05): {', '.join(failures)}."
                if failures
                else "No transform dropped recall >0.10 or raised FPR >0.05."
            )
            + "\n"
        )


def _auprc(scorer: Scorer, records: Sequence[CorpusRecord]) -> float:
    labels = [r.y for r in records]
    if sum(labels) in (0, len(labels)):
        return float("nan")
    return average_precision(labels, scorer.score(records))


def _cross_channel(records: Sequence[CorpusRecord]) -> None:
    print("## 2. Cross-channel transfer (tfidf-word, AUPRC)\n")
    by_channel = {c: [r for r in records if r.channel.value == c] for c in CHANNELS}
    print("| train \\ test | " + " | ".join(CHANNELS) + " |")
    print("|---|" + "|".join("---" for _ in CHANNELS) + "|")
    for train_c in CHANNELS:
        train = by_channel[train_c]
        if sum(r.y for r in train) < 2 or sum(1 - r.y for r in train) < 2:
            print(f"| {train_c} | " + " | ".join("n/a" for _ in CHANNELS) + " |")
            continue
        model = TfidfBaseline().fit(train)
        cells = []
        for test_c in CHANNELS:
            test = by_channel[test_c]
            cells.append("n/a" if not test else f"{_auprc(model, test):.3f}")
        print(f"| {train_c} | " + " | ".join(cells) + " |")
    print(
        "\nDiagonal is in-channel (train and test the same channel, disjoint "
        "records); off-diagonal is transfer to an unseen channel.\n"
    )


def _metadata_vs_response(records: Sequence[CorpusRecord]) -> None:
    print("## 3. Metadata vs tool-response scanning (rules-only, AUPRC)\n")
    rules = RulesScorer()
    print("| channel | n / positives | AUPRC |")
    print("|---|---|---|")
    for channel in (Channel.TOOL_RESPONSE, Channel.TOOL_METADATA):
        subset = [r for r in records if r.channel is channel]
        pos = sum(r.y for r in subset)
        auprc = "n/a" if pos in (0, len(subset)) else f"{_auprc(rules, subset):.3f}"
        print(f"| {channel.value} | {len(subset)} / {pos} | {auprc} |")
    print(
        "\nReported separately because a tool manifest (advertised metadata) and a "
        "tool response (returned data) are different surfaces; a pooled number "
        "would hide a gap between them.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=None)
    args = parser.parse_args()

    records = read_jsonl(CORPUS_PATH)
    threshold = _rules_threshold()
    print(f"corpus {CORPUS_PATH.name}: {len(records)} records\n")
    _perturbation_report(records, threshold, args.checkpoint)
    _cross_channel(records)
    _metadata_vs_response(records)
    print(
        "Note: genuine paraphrase and multilingual robustness are out of scope "
        "here - the corpus is English and offline paraphrase is unreliable; the "
        "`synonym`/`declarative` transforms are weak lexical approximations, and "
        "multilingual evaluation needs a suitable benchmark (see limitations)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
