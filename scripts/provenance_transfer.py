"""Do provenance (source-aware) features help or hurt cross-source transfer?

Source-aware features — channel, JSON-path class, document type, tool identity —
can teach a detector the shape of *the datasets it trained on* rather than the
shape of an attack. This script measures that directly: it trains the semantic
scorer on two of the three source datasets and tests on the held-out one, with
provenance features switched on and off, and reports the AUPRC gap.

If provenance features help transfer, the `with source` column is higher on the
unseen source; if they overfit to the training sources, it is lower. Either way
the number is logged rather than assumed.

This is an in-house transfer probe on our combined corpus, not a public-benchmark
claim. Deterministic and offline.

    python scripts/provenance_transfer.py
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

import numpy as np

from llmsentinel.evaluation.metrics import average_precision
from llmsentinel.paths import CORPUS_PATH
from llmsentinel.schema import CorpusRecord, read_jsonl
from llmsentinel.semantic import SemanticScorer

SOURCES = ("builtin", "bipia", "injecagent")


def _by_source(records: Sequence[CorpusRecord]) -> dict[str, list[CorpusRecord]]:
    grouped: dict[str, list[CorpusRecord]] = {name: [] for name in SOURCES}
    for record in records:
        if record.source_dataset in grouped:
            grouped[record.source_dataset].append(record)
    return grouped


def _auprc(scorer: SemanticScorer, records: Sequence[CorpusRecord]) -> tuple[float, int, int]:
    labels = [r.y for r in records]
    positives = sum(labels)
    if positives == 0 or positives == len(labels):
        return float("nan"), len(labels), positives
    return average_precision(labels, scorer.score(records)), len(labels), positives


def main() -> int:
    records = read_jsonl(CORPUS_PATH)
    grouped = _by_source(records)
    print("corpus sizes by source: " + ", ".join(f"{k}={len(v)}" for k, v in grouped.items()))
    print("\n## Leave-one-source-out transfer (semantic scorer)\n")
    print("| held-out source | n / positives | AUPRC with source feats | AUPRC without | delta |")
    print("|---|---|---|---|---|")

    deltas: list[float] = []
    for held_out in SOURCES:
        train = [r for name in SOURCES if name != held_out for r in grouped[name]]
        test = grouped[held_out]
        if not test or sum(r.y for r in test) == 0:
            print(f"| {held_out} | {len(test)} / {sum(r.y for r in test)} | n/a (no positives) | n/a | - |")
            continue

        with_src = SemanticScorer(use_source_features=True, seed=0).fit(train)
        without_src = SemanticScorer(use_source_features=False, seed=0).fit(train)
        a_with, n, pos = _auprc(with_src, test)
        a_without, _, _ = _auprc(without_src, test)
        delta = a_with - a_without
        deltas.append(delta)
        print(f"| {held_out} | {n} / {pos} | {a_with:.3f} | {a_without:.3f} | {delta:+.3f} |")

    if deltas:
        mean = float(np.mean(deltas))
        verdict = (
            "help" if mean > 0.02 else "hurt" if mean < -0.02 else "are roughly neutral for"
        )
        print(
            f"\nMean delta {mean:+.3f}: on this corpus, provenance features {verdict} "
            f"transfer to an unseen source. Interpret with the small per-source positive "
            f"counts in mind (see the support column)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
