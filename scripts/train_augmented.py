"""Train the transformer with the embedded-injection augmentation (REMAINING_THINGS B4).

    python scripts/train_augmented.py --seeds 20250909,20250910,20250911 --device auto
    python scripts/train_augmented.py --seeds 20250909 --control      # also train the un-augmented control

GPU job (the cluster); do not run it on the laptop. For every seed it trains on the
canonical train split plus ``data/processed/augmented/train_embedded.jsonl``, saves the
checkpoint, and reports **dev** metrics for passage and segment scoring. With
``--control`` it also trains the same seed on the canonical train split alone, on the
same machine, so the comparison is augmentation vs no augmentation. The augmented run
also has 900 more positives (more records, steps and a different class balance): a
confound the comparison cannot separate from position.

The canonical test split is never read (it is spent). The comparison that counts is
fresh set v3, written and committed before this script existed:

    python scripts/fresh_eval.py --fresh data/fresh/fresh_eval_v3.yaml --out artifacts/results/fresh_v3 \\
        --extra augmented=artifacts/models/transformer_augmented_seed20250909 \\
        --extra control=artifacts/models/transformer_control_seed20250909
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmsentinel.data.splits import corpus_digest  # noqa: E402
from llmsentinel.evaluation import evaluate_scores, load_splits  # noqa: E402
from llmsentinel.models.segment import SegmentScorer  # noqa: E402
from llmsentinel.models.transformer import TransformerConfig, TransformerScorer  # noqa: E402
from llmsentinel.paths import (  # noqa: E402
    CORPUS_PATH,
    MODELS_DIR,
    PROCESSED_DIR,
    RESULTS_DIR,
    relative,
)
from llmsentinel.schema import read_jsonl  # noqa: E402

AUGMENTED = PROCESSED_DIR / "augmented" / "train_embedded.jsonl"
OUT = RESULTS_DIR / "augmented"


def _dev_report(scorer, dev) -> dict:
    report = {}
    for system in (scorer, SegmentScorer(scorer)):
        metrics = evaluate_scores(
            system=system.name, split="dev",
            y_true=[r.y for r in dev], y_score=system.score(dev),
            is_hard_negative=[r.is_hard_negative for r in dev],
            channels=[r.channel.value for r in dev],
            attack_types=[r.attack_type.value for r in dev],
            bootstrap=1000, seed=20250909,
        )
        report["segment" if isinstance(system, SegmentScorer) else "passage"] = metrics.to_dict()
        print(f"    {system.name:<22} {metrics.headline()}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", default="20250909,20250910,20250911")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--control", action="store_true", help="also train each seed without augmentation")
    args = parser.parse_args()

    splits = load_splits(CORPUS_PATH)
    augmented = read_jsonl(AUGMENTED)
    if any(r.split is None or r.split.value != "train" for r in augmented):
        raise SystemExit("augmented file contains non-train records; rebuild it")
    runs = [("augmented", splits["train"] + augmented)]
    if args.control:
        runs.append(("control", list(splits["train"])))

    OUT.mkdir(parents=True, exist_ok=True)
    for seed in [int(s) for s in args.seeds.split(",") if s.strip()]:
        for name, train in runs:
            print(f"\n== {name}, seed {seed}: {len(train)} train records")
            scorer = TransformerScorer(TransformerConfig(seed=seed, epochs=args.epochs, device=args.device))
            began = time.perf_counter()
            scorer.fit(train)
            minutes = (time.perf_counter() - began) / 60.0
            path = scorer.save(MODELS_DIR / f"transformer_{name}_seed{seed}")
            print(f"    trained in {minutes:.1f} min on {scorer.describe()['resolved_device']} -> {relative(path)}")
            payload = {
                "run": name,
                "seed": seed,
                "epochs": args.epochs,
                "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "minutes": round(minutes, 1),
                "device": scorer.describe().get("resolved_device"),
                "corpus_digest": corpus_digest(read_jsonl(CORPUS_PATH)),
                "augmented_digest": corpus_digest(augmented) if name == "augmented" else None,
                "train_records": len(train),
                "checkpoint": relative(path),
                "dev": _dev_report(scorer, splits["dev"]),
            }
            (OUT / f"dev_{name}_seed{seed}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
