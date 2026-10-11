"""Per-source threshold calibration on the held-out sources (REMAINING_THINGS B1 / F7).

    python scripts/calibrate_per_source.py                    # rules-only + TF-IDF (CPU, minutes)
    python scripts/calibrate_per_source.py --transformer      # + the hardening checkpoints, when present

For each held-out source (BIPIA, InjecAgent) and each system:

1. fit on that direction's hardened train split (TF-IDF; the rules are fixed; the
   transformer is the checkpoint trained on that split, ``transformer_hardening_<source>``);
2. the dev threshold at 1% FPR, from that direction's dev split -- what the §16a study used;
3. the **calibrated** threshold at 1% FPR from the **clean** pages of a calibration half of
   the held-out source (split by group, injections never looked at);
4. recall and realised FPR of both thresholds on the other, evaluation half, plus a
   budget curve over how many clean pages the calibration had.

Protocol note, written into the output: the held-out sets were each scored once in
§16a. This is a **post-hoc** analysis of a new deployment procedure on them -- nothing
is tuned on the evaluation half, and the calibration half contributes clean pages only
-- and must be reported as such, not as a fresh held-out result.

Output: ``artifacts/results/calibration/per_source.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmsentinel.evaluation.calibration import (  # noqa: E402
    budget_curve,
    calibrated_threshold,
    evaluate_threshold,
    split_by_group,
)
from llmsentinel.evaluation.metrics import average_precision, threshold_at_fpr  # noqa: E402
from llmsentinel.evaluation.ood import (  # noqa: E402
    HELD_OUT_CHOICES,
    hardening_dir,
    load_hardening_sets,
)
from llmsentinel.models import RulesScorer, TfidfCharBaseline  # noqa: E402
from llmsentinel.paths import MODELS_DIR, RESULTS_DIR, relative  # noqa: E402

OUT = RESULTS_DIR / "calibration" / "per_source.json"
TARGET_FPR = 0.01
SEED = 20250909
BUDGETS = (25, 50, 100, 200, 400)
#: Clean pages the split-conformal bound needs to reach the target (99 for 1%).
MIN_CLEAN = int(np.ceil(1 / TARGET_FPR)) - 1


def _systems(held_out: str, use_transformer: bool) -> list[tuple[Any, bool, str | None]]:
    """(scorer, needs_fit, checkpoint) for one direction."""

    systems: list[tuple[Any, bool, str | None]] = [(RulesScorer(), False, None), (TfidfCharBaseline(), True, None)]
    if use_transformer:
        checkpoint = MODELS_DIR / f"transformer_hardening_{held_out}"
        if checkpoint.is_dir():
            from llmsentinel.models.segment import SegmentScorer
            from llmsentinel.models.transformer import TransformerScorer

            model = TransformerScorer.load(checkpoint)
            # A checkpoint retrained by `ood_eval.py train` (single seed), not the section 16a model.
            systems += [(model, False, relative(checkpoint)), (SegmentScorer(model), False, relative(checkpoint))]
        else:
            print(f"  (no {relative(checkpoint)}: transformer rows skipped; bring it back from the cluster)")
    return systems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--held-out", default="both", choices=[*HELD_OUT_CHOICES, "both"])
    parser.add_argument("--transformer", action="store_true", help="also score transformer_hardening_<source>")
    args = parser.parse_args()

    held_outs = HELD_OUT_CHOICES if args.held_out == "both" else (args.held_out,)
    report: dict[str, Any] = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_fpr": TARGET_FPR,
        "seed": SEED,
        "protocol": (
            "Post-hoc analysis on held-out sets already scored once in section 16a. The held-out "
            "source is split by group into calibration and evaluation halves; only the clean pages of "
            "the calibration half choose the calibrated threshold; results are on the evaluation half."
        ),
        "sources": {},
    }
    for held_out in held_outs:
        sets = load_hardening_sets(hardening_dir(held_out))
        calibration, evaluation = split_by_group(sets.ood, seed=SEED)
        cal_benign = [r for r in calibration if not r.y]
        eval_labels = [r.y for r in evaluation]
        informative = len(cal_benign) >= MIN_CLEAN
        print(f"\n=== {held_out}: calibration {len(calibration)} ({len(cal_benign)} clean used), "
              f"evaluation {len(evaluation)} ({sum(eval_labels)} injections)")
        source: dict[str, Any] = {
            "digests": sets.digests(),
            "calibration_records": len(calibration),
            "calibration_clean_pages": len(cal_benign),
            "evaluation_records": len(evaluation),
            "evaluation_injections": int(sum(eval_labels)),
            "informative": informative,
            "note": None if informative else (
                f"only {len(cal_benign)} clean calibration pages: the bound cannot reach {TARGET_FPR:.0%} "
                f"(needs {MIN_CLEAN}); the threshold is the strictest possible and nothing about FPR is guaranteed"
            ),
            "systems": {},
        }
        if not cal_benign:
            # Shared hosts can tie a whole source into a few connected components, leaving
            # one half without a single clean page: nothing can be calibrated, say so.
            source["note"] = (
                "no clean page in the calibration half: the source's clean hosts all share documents "
                "with injected copies, so the connected-component split cannot separate them"
            )
            print("  " + source["note"])
            report["sources"][held_out] = source
            continue
        for scorer, needs_fit, checkpoint in _systems(held_out, args.transformer):
            if needs_fit:
                scorer.fit(sets.train)
            dev_scores = np.asarray(scorer.score(sets.dev), dtype=float)
            _, dev_threshold = threshold_at_fpr([r.y for r in sets.dev], dev_scores, TARGET_FPR)
            cal_scores = np.asarray(scorer.score(cal_benign), dtype=float)
            eval_scores = np.asarray(scorer.score(evaluation), dtype=float)
            threshold, allowed, guaranteed = calibrated_threshold(cal_scores, TARGET_FPR)
            at_dev = evaluate_threshold(eval_labels, eval_scores, dev_threshold)
            at_cal = evaluate_threshold(eval_labels, eval_scores, threshold)
            source["systems"][scorer.name] = {
                "evaluation_auprc": round(average_precision(eval_labels, eval_scores), 4),
                "dev_threshold": at_dev.to_dict(),
                "calibrated_threshold": {
                    **at_cal.to_dict(),
                    "allowed_calibration_false_positives": allowed,
                    "guaranteed": guaranteed,
                    "fpr_bound_on_new_pages": round((allowed + 1) / (len(cal_scores) + 1), 4),
                },
                "provenance": {
                    "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "seed": SEED,
                    "digests": sets.digests(),
                    "checkpoint": checkpoint,
                },
                "budget_curve": budget_curve(
                    cal_scores, eval_labels, eval_scores, sizes=BUDGETS, target_fpr=TARGET_FPR, seed=SEED
                ),
            }
            print(f"  {scorer.name:<20} eval AUPRC {source['systems'][scorer.name]['evaluation_auprc']:.3f} | "
                  f"dev threshold: recall {at_dev.recall:.3f} FPR {at_dev.fpr:.3f} | "
                  f"calibrated: recall {at_cal.recall:.3f} FPR {at_cal.fpr:.3f}")
        report["sources"][held_out] = source

    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    # Keep rows from earlier runs (e.g. transformer rows added after the cluster run).
    for name, source in existing.get("sources", {}).items():
        merged = report["sources"].setdefault(name, source)
        for system, row in source.get("systems", {}).items():
            merged["systems"].setdefault(system, row)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
