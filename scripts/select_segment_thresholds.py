"""Select the segment-scoring thresholds on the canonical dev split (dev only).

    python scripts/select_segment_thresholds.py

Writes ``artifacts/results/segment_thresholds.json``: the dev AUPRC of
``SegmentScorer(transformer)`` and its thresholds at the same false-positive budgets
as every other system. The Studio guard and the SDK read them when segment scoring is
on (the default since the fresh-v2 confirmation, docs/EXPERIMENTS.md 2026-09-27).
Nothing but the dev split is read.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmsentinel.evaluation import evaluate_scores, load_splits  # noqa: E402
from llmsentinel.models.segment import MIN_WORDS, SegmentScorer  # noqa: E402
from llmsentinel.models.transformer import TransformerScorer  # noqa: E402
from llmsentinel.paths import CORPUS_PATH, MODELS_DIR, RESULTS_DIR, relative  # noqa: E402

OUT = RESULTS_DIR / "segment_thresholds.json"


def main() -> int:
    dev = load_splits(CORPUS_PATH)["dev"]
    checkpoint = MODELS_DIR / "transformer"
    scorer = SegmentScorer(TransformerScorer.load(checkpoint))
    scores = np.asarray(scorer.score(dev), dtype=float)
    metrics = evaluate_scores(
        system=scorer.name,
        split="dev",
        y_true=[r.y for r in dev],
        y_score=scores,
        is_hard_negative=[r.is_hard_negative for r in dev],
        channels=[r.channel.value for r in dev],
        bootstrap=1000,
        seed=20250909,
    )
    payload = {
        "name": scorer.name,
        "checkpoint": relative(checkpoint),
        "corpus": relative(CORPUS_PATH),
        "min_words": MIN_WORDS,
        "selected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dev": {
            "auprc": metrics.auprc,
            "auprc_ci": list(metrics.ci.get("auprc", ())),
            "thresholds": metrics.thresholds,
            "tpr_at_fpr": metrics.tpr_at_fpr,
            "hard_negative_fpr": metrics.hard_negative_fpr,
        },
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"{scorer.name} dev AUPRC {metrics.auprc:.4f} thresholds {metrics.thresholds} -> {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
