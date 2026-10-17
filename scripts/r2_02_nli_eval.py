"""R2.2: what the NLI soft-claim check adds to the deployed guard, post-hoc on fresh v1-v3.

    python scripts/r2_02_nli_eval.py

v1-v3 are spent (each scored once for detection); this is a post-hoc analysis of a new
layer on them, labelled as such in the output. Fresh v4 is not read. Nothing is tuned:
the NLI decision is the model's own top label.

For each set: per category, how many records the deployed guard flagged (from that set's
saved per-record scores and dev thresholds), how many the NLI check flags, and how many
the two together flag; false positives on counterparts and hard negatives; and how many
soft claims the claim extractor found at all (the NLI check cannot see the rest).
v1 predates segment scoring, so its baseline is the guard as deployed then (passage).

Output: artifacts/results/r2/02_nli/nli_fresh_posthoc.json
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmsentinel.evaluation.fresh import FRESH_PATH, load_fresh  # noqa: E402
from llmsentinel.nli import DEFAULT_NLI_MODEL, NLIClaimChecker  # noqa: E402
from llmsentinel.output_check import _prose, directed_claim_sentences  # noqa: E402
from llmsentinel.paths import RESULTS_DIR, relative  # noqa: E402

OUT = RESULTS_DIR / "r2" / "02_nli" / "nli_fresh_posthoc.json"
SETS = (("v1", FRESH_PATH, "fresh"), ("v2", FRESH_PATH.with_name("fresh_eval_v2.yaml"), "fresh_v2"),
        ("v3", FRESH_PATH.with_name("fresh_eval_v3.yaml"), "fresh_v3"))
SKIP = ("tool",)  # tool descriptions carry no "say that ..." claims about a page


def deployed(results_dir: Path) -> tuple[dict[str, bool], str]:
    results = json.loads((results_dir / "results_fresh.json").read_text(encoding="utf-8"))["systems"]
    rules_t = results["rules-only"]["dev"]["thresholds"]["fpr=0.001"]
    model = "transformer-segment" if "transformer-segment" in results else "transformer"
    model_t = results[model]["dev"]["thresholds"]["fpr=0.01"]
    flags = {}
    for line in (results_dir / "scores.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        s = row["scores"]
        flags[row["record_id"]] = bool(s[model] >= model_t or s["rules-only"] >= rules_t)
    return flags, f"{model} >= dev 1% threshold OR rules-only >= dev 0.1% threshold"


def main() -> int:
    checker = NLIClaimChecker()
    checker._load()
    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": DEFAULT_NLI_MODEL,
        "decision": "the NLI model's top label is contradiction (no threshold tuned)",
        "protocol": "post-hoc on fresh sets v1-v3, each already scored once for detection; v4 not read",
        "sets": {},
    }
    for name, path, results_name in SETS:
        fresh = load_fresh(path, normalise=False)
        base, rule = deployed(RESULTS_DIR / results_name)
        table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        hits, timings = [], []
        for case in fresh.cases:
            if case.category in SKIP:
                continue
            record = case.record
            began = time.perf_counter()
            found = checker.check(record.raw_text)
            timings.append(time.perf_counter() - began)
            nli = bool(found)
            row = table[case.category]
            row["n"] += 1
            row["label_injection"] += int(record.y)
            row["extracted_claim"] += int(any(directed_claim_sentences(leaf) for leaf in _prose(record.raw_text)))
            row["deployed"] += int(base[record.record_id])
            row["nli"] += int(nli)
            row["deployed_or_nli"] += int(base[record.record_id] or nli)
            row["nli_only"] += int(nli and not base[record.record_id])
            if found:
                hits.append({"id": record.record_id, "category": case.category, "label": record.y,
                             **found[0].to_dict()})
        report["sets"][name] = {
            "fresh_digest": fresh.digest[:16],
            "baseline": rule,
            "by_category": {k: dict(v) for k, v in sorted(table.items())},
            "nli_hits": hits,
            "seconds_per_record": round(sum(timings) / max(1, len(timings)), 3),
        }
        soft = table["soft_claim"]
        print(f"{name}: soft claims {soft['n']} | extracted {soft['extracted_claim']} | deployed {soft['deployed']} "
              f"| NLI {soft['nli']} | together {soft['deployed_or_nli']} | NLI false alarms on clean: "
              f"{table['counterpart']['nli'] + table['hard_negative']['nli']} of "
              f"{table['counterpart']['n'] + table['hard_negative']['n']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
