"""Section 16a: build the hardening / out-of-distribution sets and evaluate on them.

Three sub-commands:

    python scripts/ood_eval.py build [--held-out injecagent|bipia|both]
        Needs the raw benchmarks in data/raw/. For each held-out source, builds the
        hardened in-distribution splits from the other sources (builtin with the
        thickened metadata set, BIPIA with raised leakage-free caps, InjecAgent
        un-capped), scrubs overlap with the held-out set, and writes
        data/processed/hardening/<held_out>/{indist.jsonl, ood_<held_out>.jsonl, manifest.json}.

    python scripts/ood_eval.py eval --systems baselines
    python scripts/ood_eval.py eval --systems transformer --seeds 20250909,20250910,20250911 --device auto
        Needs only the committed hardening files. Fits on train, selects thresholds
        on dev, scores the in-distribution test and the OOD set once each, and writes
        artifacts/results/ood/<held_out>/ood_<systems>.json.

    python scripts/ood_eval.py train --held-out both [--seed 20250909] --device auto
        GPU job. Trains and saves artifacts/models/transformer_hardening_<held_out>
        without scoring anything (the held-out sets are spent); per-source
        calibration (scripts/calibrate_per_source.py --transformer) uses them.

Scoring the same system on the same data digests twice is refused unless
--force-test is given (and the forced run is recorded).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys

from llmsentinel.evaluation.ood import (
    HARDENING_DIR,
    HELD_OUT_CHOICES,
    OOD_RESULTS_DIR,
    HardeningConfig,
    aggregate_seeds,
    build_hardening_sets,
    evaluate_system,
    hardening_dir,
    load_hardening_sets,
    ood_table,
    record_scoring,
    run_key,
    scoring_allowed,
    write_hardening_sets,
)
from llmsentinel.paths import MODELS_DIR, relative


def _held_outs(choice: str) -> tuple[str, ...]:
    return HELD_OUT_CHOICES if choice == "both" else (choice,)


def cmd_build(args: argparse.Namespace) -> int:
    ok = True
    for held_out in _held_outs(args.held_out):
        config = HardeningConfig(held_out=held_out, thicken_metadata=not args.no_thicken)
        sets = build_hardening_sets(config)
        paths = write_hardening_sets(sets, hardening_dir(held_out, args.root))
        report = sets.report
        print(f"\n=== held out: {held_out} ===")
        print(json.dumps({k: report[k] for k in (
            "sizes", "ood_support", "exact_duplicates_removed", "ood_near_duplicates_dropped",
            "ood_shared_key_dropped", "leakage_indist_ok", "tool_metadata", "digests",
            "skipped_sources",
        )}, indent=2))
        print("counts:", json.dumps(report["counts"], indent=2))
        for name, path in paths.items():
            print(f"wrote {name}: {relative(path)} ({path.stat().st_size / 1e6:.1f} MB)")
        ok = ok and report["leakage_indist_ok"]
    return 0 if ok else 1


def _baselines() -> list:
    from llmsentinel.models import (
        KeywordBaseline,
        MajorityBaseline,
        RulesScorer,
        TfidfBaseline,
        TfidfCharBaseline,
    )

    return [MajorityBaseline(), KeywordBaseline(), TfidfBaseline(), TfidfCharBaseline(), RulesScorer()]


def _eval_one(args: argparse.Namespace, held_out: str) -> int:
    sets = load_hardening_sets(hardening_dir(held_out, args.root))
    print(f"\n=== held out: {held_out} === train={len(sets.train)} dev={len(sets.dev)} "
          f"test={len(sets.test)} ood={len(sets.ood)} digests={sets.digests()}")

    results = []
    seed_results = []
    refused: list[str] = []

    if args.systems in ("baselines", "all"):
        for system in _baselines():
            key = run_key(system.name, sets)
            if not scoring_allowed(key, force=args.force_test):
                refused.append(system.name)
                continue
            results.append(evaluate_system(system, sets))
            record_scoring(key, forced=args.force_test)

    if args.systems in ("transformer", "all"):
        from llmsentinel.models.transformer import (
            TransformerConfig,
            TransformerScorer,
            torch_available,
        )

        if not torch_available():
            print("transformer extra not installed; see docs/TRAINING_HANDOFF.md")
            return 1
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
        for index, seed in enumerate(seeds):
            label = f"transformer(seed={seed})"
            key = run_key(label, sets)
            if not scoring_allowed(key, force=args.force_test):
                refused.append(label)
                continue
            scorer = TransformerScorer(
                TransformerConfig(seed=seed, epochs=args.epochs, device=args.device)
            )
            scorer.fit(sets.train)
            if index == 0:
                scorer.save(MODELS_DIR / f"transformer_hardening_{held_out}")
            result = evaluate_system(scorer, sets, fit=False, name=label, seed=seed)
            record_scoring(key, forced=args.force_test)
            results.append(result)
            seed_results.append(result)
            print(f"{label}: test AUPRC {result.test.auprc:.3f} | OOD AUPRC {result.ood.auprc:.3f} "
                  f"| OOD recall@1% {result.ood.tpr_at_fpr.get('fpr=0.01', 0.0):.3f} "
                  f"({scorer.describe()['resolved_device']})")

    if refused:
        print("refused (already scored on these digests; use --force-test to override): "
              + ", ".join(refused))
    if not results:
        return 1

    print()
    print(ood_table(results))
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "held_out": held_out,
        "digests": sets.digests(),
        "sizes": sets.report.get("sizes"),
        "ood_support": sets.report.get("ood_support"),
        "results": [r.to_dict() for r in results],
    }
    if len(seed_results) > 1:
        payload["seed_aggregate"] = aggregate_seeds(seed_results)
        agg = payload["seed_aggregate"]
        print(f"\ntransformer across {len(seed_results)} seeds: test AUPRC "
              f"{agg['test_auprc']['mean']} +/- {agg['test_auprc']['std']} | OOD AUPRC "
              f"{agg['ood_auprc']['mean']} +/- {agg['ood_auprc']['std']} | OOD recall@1% "
              f"{agg['ood_recall_at_1pct_fpr_threshold']['mean']} +/- "
              f"{agg['ood_recall_at_1pct_fpr_threshold']['std']}")

    out_dir = OOD_RESULTS_DIR / held_out
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ood_{args.systems}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"saved {relative(out)}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    codes = [_eval_one(args, held_out) for held_out in _held_outs(args.held_out)]
    return max(codes) if codes else 1


def cmd_train(args: argparse.Namespace) -> int:
    """Train and save the hardening checkpoints only -- no scoring.

    The held-out sets were scored once in section 16a; per-source calibration
    (scripts/calibrate_per_source.py) needs the checkpoints, not another scoring.
    """

    from llmsentinel.models.transformer import TransformerConfig, TransformerScorer, torch_available

    if not torch_available():
        print("transformer extra not installed; see docs/TRAINING_HANDOFF.md")
        return 1
    for held_out in _held_outs(args.held_out):
        sets = load_hardening_sets(hardening_dir(held_out, args.root))
        scorer = TransformerScorer(TransformerConfig(seed=args.seed, epochs=args.epochs, device=args.device))
        scorer.fit(sets.train)
        path = scorer.save(MODELS_DIR / f"transformer_hardening_{held_out}")
        print(f"{held_out}: trained on {len(sets.train)} records ({scorer.describe()['resolved_device']}) "
              f"-> {relative(path)}; held-out set not scored")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    choices = [*HELD_OUT_CHOICES, "both"]

    build = sub.add_parser("build", help="build the hardening + OOD sets (needs data/raw)")
    build.add_argument("--held-out", default="both", choices=choices)
    build.add_argument("--no-thicken", action="store_true", help="skip the opt-in metadata seed set")
    build.add_argument("--root", default=str(HARDENING_DIR))
    build.set_defaults(func=cmd_build)

    ev = sub.add_parser("eval", help="evaluate systems on the committed hardening sets")
    ev.add_argument("--held-out", default="both", choices=choices)
    ev.add_argument("--root", default=str(HARDENING_DIR))
    ev.add_argument("--systems", default="baselines", choices=["baselines", "transformer", "all"])
    ev.add_argument("--seeds", default="20250909,20250910,20250911")
    ev.add_argument("--epochs", type=int, default=3)
    ev.add_argument("--device", default="auto")
    ev.add_argument("--force-test", action="store_true")
    ev.set_defaults(func=cmd_eval)

    tr = sub.add_parser("train", help="train and save transformer_hardening_<source> without scoring")
    tr.add_argument("--held-out", default="both", choices=choices)
    tr.add_argument("--root", default=str(HARDENING_DIR))
    tr.add_argument("--seed", type=int, default=20250909)
    tr.add_argument("--epochs", type=int, default=3)
    tr.add_argument("--device", default="auto")
    tr.set_defaults(func=cmd_train)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
