"""Train the transformer detector and save the checkpoint.

Kept as a script rather than a library entry point because it is the only
long-running step in the project: on CPU it takes minutes, and it should be
startable, interruptible and re-runnable on its own.

    python scripts/train_transformer.py [--epochs 3] [--seed 20250909]
"""

from __future__ import annotations

import argparse
import time

from llmsentinel.constants import DEFAULT_SEED
from llmsentinel.evaluation import evaluate_scores, load_splits
from llmsentinel.models.transformer import TransformerConfig, TransformerScorer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--backbone", default=None)
    parser.add_argument("--out", default=None, help="checkpoint directory")
    parser.add_argument(
        "--truncate-training",
        action="store_true",
        help="train on truncated records instead of windows (ablation)",
    )
    args = parser.parse_args()

    splits = load_splits()
    config = TransformerConfig(
        epochs=args.epochs,
        seed=args.seed,
        max_length=args.max_length,
        batch_size=args.batch_size,
    )
    if args.backbone:
        config.backbone = args.backbone
    config.window_training = not args.truncate_training

    scorer = TransformerScorer(config)
    began = time.perf_counter()
    scorer.fit(splits["train"])
    minutes = (time.perf_counter() - began) / 60.0

    path = scorer.save(args.out)
    dev = splits["dev"]
    metrics = evaluate_scores(
        system=f"transformer(seed={args.seed})",
        split="dev",
        y_true=[record.y for record in dev],
        y_score=scorer.score(dev),
        is_hard_negative=[record.is_hard_negative for record in dev],
        channels=[record.channel.value for record in dev],
        attack_types=[record.attack_type.value for record in dev],
    )
    print(f"trained in {minutes:.1f} min on {len(splits['train'])} records -> {path}")
    print(metrics.headline())


if __name__ == "__main__":
    main()
