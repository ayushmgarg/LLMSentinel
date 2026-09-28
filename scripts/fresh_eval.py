"""Score every system on the fresh evaluation set, once (REMAINING_THINGS B0, F1).

    python scripts/fresh_eval.py                 # refuses if this digest was scored
    python scripts/fresh_eval.py --rules-only    # skip the transformer (no checkpoint)

Protocol, same as the canonical test split:

* baselines are fitted on the canonical **train** split; the fusion model on dev;
* every threshold comes from the canonical **dev** split, recomputed here and
  checked against ``results_dev.json``;
* the fresh set is scored **once per digest**; a second run needs ``--force`` and
  is recorded as such in the ledger.

Also scored here for the first time: the **deployed decision rule** the Studio and
SDK use -- flag if the transformer reaches its dev 1%-FPR threshold OR the rules
reach their dev 0.1%-FPR threshold -- which had never been evaluated as a system.

Outputs (``artifacts/results/fresh/``): ``results_fresh.json`` (metrics with
bootstrap CIs, per-category recall, the OR rule, paired tests) and
``scores.jsonl`` (per-record scores, so later tests need no re-scoring).
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

from llmsentinel.evaluation import evaluate_scores, load_splits  # noqa: E402
from llmsentinel.evaluation.fresh import FRESH_PATH, load_fresh  # noqa: E402
from llmsentinel.evaluation.significance import mcnemar, paired_bootstrap_delta  # noqa: E402
from llmsentinel.models import (  # noqa: E402
    KeywordBaseline,
    MajorityBaseline,
    RulesScorer,
    TfidfBaseline,
    TfidfCharBaseline,
)
from llmsentinel.models.fusion import FusionScorer  # noqa: E402
from llmsentinel.models.segment import SegmentScorer  # noqa: E402
from llmsentinel.paths import CORPUS_PATH, MODELS_DIR, RESULTS_DIR, relative  # noqa: E402

OUT = RESULTS_DIR / "fresh"
LEDGER = OUT / "runs.json"
BOOTSTRAP = 1000
SEED = 20250909


def _fields(records: list[Any]) -> dict[str, list[Any]]:
    return {
        "y_true": [r.y for r in records],
        "is_hard_negative": [r.is_hard_negative for r in records],
        "channels": [r.channel.value for r in records],
        "source_datasets": [str(r.extra.get("category", r.source_dataset)) for r in records],
        "attack_types": [r.attack_type.value for r in records],
    }


def _ledger(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _recall_by_category(categories: list[str], labels: np.ndarray, flagged: np.ndarray) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for category in sorted(set(categories)):
        mask = np.asarray([c == category for c in categories])
        positives = int(labels[mask].sum())
        negatives = int(mask.sum() - positives)
        row: dict[str, float] = {"n": int(mask.sum())}
        if positives:
            row["recall"] = round(float(flagged[mask & (labels == 1)].mean()), 4)
        if negatives:
            row["fpr"] = round(float(flagged[mask & (labels == 0)].mean()), 4)
        out[category] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fresh", default=str(FRESH_PATH))
    parser.add_argument("--corpus", default=str(CORPUS_PATH))
    parser.add_argument("--checkpoint", default=str(MODELS_DIR / "transformer"))
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--force", action="store_true", help="score a digest again (recorded; breaks score-once)")
    parser.add_argument("--out", default=str(OUT), help="output directory (a smoke test uses its own)")
    args = parser.parse_args()
    out = Path(args.out)
    ledger = out / LEDGER.name

    fresh = load_fresh(args.fresh)
    runs = _ledger(ledger)
    if any(run["digest"] == fresh.digest for run in runs) and not args.force:
        print(f"refusing: fresh set {fresh.digest[:12]} was already scored (see {relative(ledger)}).")
        return 1

    splits = load_splits(args.corpus)
    train, dev = splits["train"], splits["dev"]
    records = fresh.records
    categories = [c.category for c in fresh.cases]
    labels = np.asarray([r.y for r in records])
    print(f"fresh {fresh.digest[:12]}: {len(records)} records ({int(labels.sum())} injections); "
          f"dev {len(dev)}, train {len(train)}")

    rules = RulesScorer()
    systems: list[Any] = [MajorityBaseline(), KeywordBaseline(), TfidfBaseline(), TfidfCharBaseline(), rules]
    transformer = None
    if not args.rules_only:
        from llmsentinel.models.transformer import TransformerScorer

        transformer = TransformerScorer.load(Path(args.checkpoint))
        systems.append(transformer)
        # Segment-level scoring of the same checkpoint (no retraining); added after
        # fresh v1 exposed the masking failure, confirmed on fresh v2.
        systems.append(SegmentScorer(transformer))

    results: dict[str, Any] = {}
    fresh_scores: dict[str, np.ndarray] = {}
    dev_scores: dict[str, np.ndarray] = {}
    reference = {e["name"]: e["dev"]["thresholds"] for e in json.loads((RESULTS_DIR / "results_dev.json").read_text())}

    def score(system: Any, fit: bool) -> None:
        if fit:
            system.fit(train)
        d = np.asarray(system.score(dev), dtype=float)
        dev_metrics = evaluate_scores(system=system.name, split="dev", y_score=d, bootstrap=BOOTSTRAP, seed=SEED, **_fields(dev))
        f = np.asarray(system.score(records), dtype=float)
        fresh_metrics = evaluate_scores(
            system=system.name, split="fresh", y_score=f, thresholds=dev_metrics.thresholds,
            bootstrap=BOOTSTRAP, seed=SEED, **_fields(records),
        )
        drift = {
            key: round(abs(value - reference.get(system.name, {}).get(key, value)), 8)
            for key, value in dev_metrics.thresholds.items()
        }
        flagged = f >= dev_metrics.thresholds["fpr=0.01"]
        results[system.name] = {
            "dev": dev_metrics.to_dict(),
            "fresh": fresh_metrics.to_dict(),
            "by_category_at_dev_1pct": _recall_by_category(categories, labels, flagged),
            "threshold_difference_vs_results_dev_json": drift,
        }
        dev_scores[system.name], fresh_scores[system.name] = d, f
        ci = fresh_metrics.ci.get("auprc", (float("nan"), float("nan")))
        print(f"  {system.name:<16} dev AUPRC {dev_metrics.auprc:.3f}  fresh AUPRC {fresh_metrics.auprc:.3f} "
              f"[{ci[0]:.3f}, {ci[1]:.3f}]  fresh TPR@dev1% {fresh_metrics.tpr_at_fpr['fpr=0.01']:.3f} "
              f"(FPR {fresh_metrics.fpr_achieved['fpr=0.01']:.3f})")

    for system in systems:
        score(system, fit=not (system is transformer or isinstance(system, SegmentScorer)))
    fusion = FusionScorer(rules=rules, transformer=transformer)
    fusion.fit(dev)
    score(fusion, fit=False)

    # ---------------------------------------------------- deployed decision rule
    rules_t = results["rules-only"]["dev"]["thresholds"]
    decisions: dict[str, np.ndarray] = {
        "rules-only@1%": fresh_scores["rules-only"] >= rules_t["fpr=0.01"],
    }
    dev_decisions: dict[str, np.ndarray] = {"rules-only@1%": dev_scores["rules-only"] >= rules_t["fpr=0.01"]}
    if transformer is not None:
        tr_t = results["transformer"]["dev"]["thresholds"]
        decisions["deployed OR"] = (fresh_scores["transformer"] >= tr_t["fpr=0.01"]) | (
            fresh_scores["rules-only"] >= rules_t["fpr=0.001"]
        )
        dev_decisions["deployed OR"] = (dev_scores["transformer"] >= tr_t["fpr=0.01"]) | (
            dev_scores["rules-only"] >= rules_t["fpr=0.001"]
        )
        decisions["transformer@1%"] = fresh_scores["transformer"] >= tr_t["fpr=0.01"]
        dev_decisions["transformer@1%"] = dev_scores["transformer"] >= tr_t["fpr=0.01"]
        seg_t = results["transformer-segment"]["dev"]["thresholds"]
        decisions["deployed OR (segment)"] = (fresh_scores["transformer-segment"] >= seg_t["fpr=0.01"]) | (
            fresh_scores["rules-only"] >= rules_t["fpr=0.001"]
        )
        dev_decisions["deployed OR (segment)"] = (dev_scores["transformer-segment"] >= seg_t["fpr=0.01"]) | (
            dev_scores["rules-only"] >= rules_t["fpr=0.001"]
        )
    dev_labels = np.asarray([r.y for r in dev])
    hard = np.asarray([r.is_hard_negative for r in records])
    decision_report: dict[str, Any] = {}
    for name, flagged in decisions.items():
        dev_flagged = dev_decisions[name]
        decision_report[name] = {
            "fresh_tpr": round(float(flagged[labels == 1].mean()), 4),
            "fresh_fpr": round(float(flagged[labels == 0].mean()), 4),
            "fresh_hard_negative_fpr": round(float(flagged[hard].mean()), 4),
            "dev_tpr": round(float(dev_flagged[dev_labels == 1].mean()), 4),
            "dev_fpr": round(float(dev_flagged[dev_labels == 0].mean()), 4),
            "by_category": _recall_by_category(categories, labels, flagged),
        }
        print(f"  decision {name:<16} fresh TPR {decision_report[name]['fresh_tpr']:.3f} "
              f"FPR {decision_report[name]['fresh_fpr']:.3f} | dev TPR {decision_report[name]['dev_tpr']:.3f} "
              f"FPR {decision_report[name]['dev_fpr']:.3f}")

    # ------------------------------------------------------- significance (F1)
    tests: dict[str, Any] = {"paired_bootstrap_auprc": [], "mcnemar": []}
    anchor = "transformer" if transformer is not None else "rules-only"
    for split_name, scores, y in (("dev", dev_scores, dev_labels), ("fresh", fresh_scores, labels)):
        for other in scores:
            if other == anchor or other == "majority":
                continue
            result = paired_bootstrap_delta(y, scores[anchor], scores[other], names=(anchor, other), seed=SEED)
            tests["paired_bootstrap_auprc"].append({"split": split_name, **result.to_dict()})
    if transformer is not None:
        for split_name, table, y in (("dev", dev_decisions, dev_labels), ("fresh", decisions, labels)):
            pairs = (
                ("deployed OR (segment)", "deployed OR"),
                ("deployed OR", "transformer@1%"),
                ("deployed OR", "rules-only@1%"),
                ("transformer@1%", "rules-only@1%"),
            )
            for a, b in pairs:
                tests["mcnemar"].append({"split": split_name, **mcnemar(y, table[a], table[b], names=(a, b)).to_dict()})

    # ------------------------------------------------------------------ output
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "fresh_digest": fresh.digest,
        "fresh_path": relative(Path(args.fresh)),
        "corpus": relative(Path(args.corpus)),
        "checkpoint": relative(Path(args.checkpoint)) if transformer is not None else None,
        "scored_at": stamp,
        "bootstrap": BOOTSTRAP,
        "seed": SEED,
        "counts": {"records": len(records), "injections": int(labels.sum()), "benign": int(len(labels) - labels.sum())},
        "systems": results,
        "decisions": decision_report,
        "significance": tests,
    }
    (out / "results_fresh.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (out / "scores.jsonl").open("w", encoding="utf-8") as handle:
        for index, case in enumerate(fresh.cases):
            row = {
                "record_id": case.record.record_id,
                "label": int(labels[index]),
                "category": case.category,
                "channel": case.record.channel.value,
                "scores": {name: round(float(values[index]), 6) for name, values in fresh_scores.items()},
                "decisions": {name: bool(values[index]) for name, values in decisions.items()},
            }
            handle.write(json.dumps(row) + "\n")
    runs.append({"digest": fresh.digest, "scored_at": stamp, "forced": bool(args.force), "transformer": transformer is not None})
    ledger.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    print(f"wrote {relative(out / 'results_fresh.json')} and scores.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
