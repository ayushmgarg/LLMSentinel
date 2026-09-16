"""Explain the detector's worst mistakes on dev.

The Week 2 exit review requires at least one false positive explained correctly
and one false negative explained honestly.  This script surfaces both from the
same scores the results table reports, at the 1% FPR operating point, so the
explanation is about the system that was measured and not a re-run of it.

    python scripts/error_analysis.py [--system rules-only|hybrid]
"""

from __future__ import annotations

import argparse
import math

from llmsentinel.evaluation import evaluate_scores, load_splits
from llmsentinel.models import RulesScorer
from llmsentinel.models.fusion import FusionScorer
from llmsentinel.models.transformer import TransformerScorer, torch_available


def excerpt(text: str, limit: int = 200) -> str:
    """Console-safe excerpt.

    The records under analysis contain zero-width and homoglyph characters by
    design, and a Windows console encoded as cp1252 raises on them; escaping
    keeps the evidence visible instead of killing the report.
    """

    collapsed = " ".join(text.split())[:limit]
    return collapsed.encode("ascii", "backslashreplace").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", default="rules-only", choices=["rules-only", "hybrid"])
    parser.add_argument("--checkpoint", default="artifacts/models/transformer")
    parser.add_argument("-n", type=int, default=3)
    args = parser.parse_args()

    splits = load_splits()
    dev = splits["dev"]
    rules = RulesScorer()

    if args.system == "hybrid":
        transformer = None
        if torch_available():
            try:
                transformer = TransformerScorer.load(args.checkpoint)
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"note: transformer unavailable ({exc}); fusing rules only")
        scorer = FusionScorer(rules=rules, transformer=transformer)
        scorer.fit(dev)
    else:
        scorer = rules

    scores = scorer.score(dev)
    metrics = evaluate_scores(
        system=args.system,
        split="dev",
        y_true=[record.y for record in dev],
        y_score=scores,
        is_hard_negative=[record.is_hard_negative for record in dev],
    )
    threshold = metrics.thresholds["fpr=0.01"]
    if not math.isfinite(threshold):
        # No cutoff reaches 1% FPR on this split: the top of the ranking already
        # holds too many benign records. Fall back to the highest positive score
        # so the mistakes stay inspectable, and say so rather than printing an
        # empty report.
        positives = sorted((s for s, r in zip(scores, dev, strict=True) if r.y), reverse=True)
        threshold = positives[0] if positives else 0.0
        print(
            f"{args.system}: AUPRC={metrics.auprc:.3f}; NO operating point reaches 1% FPR "
            f"on dev, so errors are shown at the top positive score {threshold:.4f}\n"
        )
    else:
        print(f"{args.system}: AUPRC={metrics.auprc:.3f}, threshold@1%FPR={threshold:.4f}\n")

    ranked = sorted(zip(dev, scores, strict=True), key=lambda pair: pair[1], reverse=True)

    print("=== FALSE POSITIVES (highest-scoring benign records) ===")
    shown = 0
    for record, score in ranked:
        if record.y or score < threshold:
            continue
        report = rules.report_for(record)
        print(f"\n[{score:.3f}] {record.record_id} channel={record.channel.value} "
              f"hard_negative={record.is_hard_negative}")
        print(f"  text: {excerpt(record.raw_text)}")
        for reason in report.trace()[:2]:
            print(f"  rule: {reason[:170]}")
        shown += 1
        if shown >= args.n:
            break
    if not shown:
        print("  none at this operating point")

    print("\n=== FALSE NEGATIVES (lowest-scoring injections) ===")
    missed = [(record, score) for record, score in ranked if record.y and score < threshold]
    for record, score in sorted(missed, key=lambda pair: pair[1])[: args.n]:
        report = rules.report_for(record)
        print(f"\n[{score:.3f}] {record.record_id} attack={record.attack_type.value} "
              f"channel={record.channel.value} family={record.extra.get('insertion_family')}")
        print(f"  text: {excerpt(record.raw_text)}")
        print(f"  rules fired: {[hit.family for hit in report.hits] or 'none'}")
    print(f"\n{len(missed)} of {sum(r.y for r in dev)} injections fall below that threshold")


if __name__ == "__main__":
    main()
