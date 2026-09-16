"""Train the transformer across several seeds and report the dev variance.

A single training run is a point estimate; a reviewer will ask how much of the
number is the seed. This trains N seeds, scores each on dev, and writes the
mean +/- standard deviation to ``artifacts/results/seed_variance.json``. The
first seed's checkpoint is saved as the canonical ``artifacts/models/transformer``
(so the rest of the pipeline uses it); the other seeds are trained only to
measure spread and are not kept, so only one checkpoint has to be sent back.

Uses the GPU automatically when present (``--device auto``). On an RTX 3060 the
three-seed sweep is a few minutes total.

    python scripts/train_seeds.py --seeds 20250909,20250910,20250911
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

from llmsentinel.evaluation import evaluate_scores, load_splits
from llmsentinel.models.transformer import TransformerConfig, TransformerScorer
from llmsentinel.paths import MODELS_DIR, RESULTS_DIR, relative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="20250909,20250910,20250911")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--device", default="auto", help="auto | cpu | cuda")
    args = parser.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    splits = load_splits()
    canonical = seeds[0]
    per_seed: list[dict[str, float]] = []

    for seed in seeds:
        config = TransformerConfig(epochs=args.epochs, seed=seed, device=args.device)
        scorer = TransformerScorer(config)
        began = time.perf_counter()
        scorer.fit(splits["train"])
        minutes = (time.perf_counter() - began) / 60.0
        if seed == canonical:
            scorer.save(MODELS_DIR / "transformer")
        dev = splits["dev"]
        metrics = evaluate_scores(
            system=f"transformer(seed={seed})",
            split="dev",
            y_true=[r.y for r in dev],
            y_score=scorer.score(dev),
            is_hard_negative=[r.is_hard_negative for r in dev],
        )
        row = {
            "seed": seed,
            "auprc": round(metrics.auprc, 4),
            "auroc": round(metrics.auroc, 4),
            "tpr@1%fpr": round(metrics.tpr_at_fpr.get("fpr=0.01", 0.0), 4),
            "minutes": round(minutes, 1),
            "device": scorer.describe()["resolved_device"],
        }
        per_seed.append(row)
        print(f"seed {seed}: AUPRC {row['auprc']} AUROC {row['auroc']} "
              f"TPR@1%FPR {row['tpr@1%fpr']} ({row['minutes']} min, {row['device']})")

    def agg(key: str) -> dict[str, float]:
        vals = [r[key] for r in per_seed]
        return {
            "mean": round(statistics.mean(vals), 4),
            "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": min(vals),
            "max": max(vals),
        }

    summary = {
        "seeds": seeds,
        "canonical_seed": canonical,
        "per_seed": per_seed,
        "dev_auprc": agg("auprc"),
        "dev_auroc": agg("auroc"),
        "dev_tpr_at_1pct_fpr": agg("tpr@1%fpr"),
    }
    out = RESULTS_DIR / "seed_variance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    a = summary["dev_auprc"]
    print(f"\ndev AUPRC across {len(seeds)} seeds: {a['mean']} +/- {a['std']} "
          f"(min {a['min']}, max {a['max']})")
    print(f"canonical checkpoint: {relative(MODELS_DIR / 'transformer')}")
    print(f"summary: {relative(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
