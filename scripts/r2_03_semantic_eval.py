"""R2.3: semantic signals (B12 task conflict, B13 similarity to confirmed attacks).

    python scripts/r2_03_semantic_eval.py

Systems, each fitted on train only:
* ``semantic (lexical)`` -- the existing 18-feature task-conflict scorer with the lexical
  similarity proxy (its September measurement, repeated on the current corpus);
* ``semantic (MiniLM)`` -- the same scorer with real sentence embeddings (never measured);
* ``attack-similarity`` -- max cosine between a record's sentences and the train split's
  injected spans (B13).

Each gets AUPRC and recall at a 1%-FPR threshold chosen on **dev**. Then, post-hoc on the
spent fresh sets v1-v3 (v4 not read), what each adds to the deployed guard: records it
flags that the guard missed, and its false alarms on clean records.

Output: artifacts/results/r2/03_semantic/semantic_eval.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from r2_02_nli_eval import SETS, deployed  # noqa: E402

from llmsentinel.evaluation import load_splits  # noqa: E402
from llmsentinel.evaluation.fresh import load_fresh  # noqa: E402
from llmsentinel.evaluation.metrics import average_precision, threshold_at_fpr  # noqa: E402
from llmsentinel.paths import CORPUS_PATH, RESULTS_DIR, relative  # noqa: E402
from llmsentinel.semantic import (  # noqa: E402
    LexicalEmbedder,
    SemanticScorer,
    SentenceTransformerEmbedder,
)
from llmsentinel.semantic.attack_similarity import AttackSimilarityScorer  # noqa: E402

OUT = RESULTS_DIR / "r2" / "03_semantic" / "semantic_eval.json"
TARGET_FPR = 0.01
CLEAN = ("counterpart", "hard_negative")


def main() -> int:
    splits = load_splits(CORPUS_PATH)
    train, dev = splits["train"], splits["dev"]
    dev_y = np.asarray([r.y for r in dev])
    minilm = SentenceTransformerEmbedder()
    systems = {
        "semantic (lexical)": SemanticScorer(LexicalEmbedder()),
        "semantic (MiniLM)": SemanticScorer(minilm),
        "attack-similarity (MiniLM)": AttackSimilarityScorer(minilm),
    }
    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": "fitted on train; threshold at 1% FPR on dev; fresh v1-v3 post-hoc (already scored once); v4 not read",
        "systems": {},
    }
    fresh_sets = [(name, load_fresh(path, normalise=False), deployed(RESULTS_DIR / res)[0]) for name, path, res in SETS]
    for name, scorer in systems.items():
        scorer.fit(train)
        dev_scores = np.asarray(scorer.score(dev), dtype=float)
        _, threshold = threshold_at_fpr(dev_y.tolist(), dev_scores, TARGET_FPR)
        flagged_dev = dev_scores >= threshold
        row = {
            "dev_auprc": round(average_precision(dev_y.tolist(), dev_scores), 4),
            "dev_threshold_1pct": round(float(threshold), 6),
            "dev_recall_at_threshold": round(float(flagged_dev[dev_y == 1].mean()), 4),
            "dev_fpr_at_threshold": round(float(flagged_dev[dev_y == 0].mean()), 4),
            "fresh_posthoc": {},
        }
        for set_name, fresh, base in fresh_sets:
            cases = [c for c in fresh.cases if c.category != "tool"]
            scores = np.asarray(scorer.score([c.record for c in cases]), dtype=float)
            table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for case, score in zip(cases, scores, strict=True):
                hit, was = bool(score >= threshold), base[case.record.record_id]
                t = table[case.category]
                t["n"] += 1
                t["flagged"] += int(hit)
                t["deployed"] += int(was)
                t["added"] += int(hit and not was)
            injections = [c for c in table if c not in CLEAN]
            row["fresh_posthoc"][set_name] = {
                "by_category": {k: dict(v) for k, v in sorted(table.items())},
                "injections_added_over_deployed": sum(table[c]["added"] for c in injections),
                "injections": sum(table[c]["n"] for c in injections),
                "clean_false_alarms": sum(table[c]["flagged"] for c in CLEAN),
                "clean": sum(table[c]["n"] for c in CLEAN),
                "clean_added_false_alarms": sum(table[c]["added"] for c in CLEAN),
            }
        report["systems"][name] = row
        summary = " | ".join(
            f"{s}: +{v['injections_added_over_deployed']}/{v['injections']} inj, {v['clean_false_alarms']}/{v['clean']} FA"
            for s, v in row["fresh_posthoc"].items()
        )
        print(f"{name:<28} dev AUPRC {row['dev_auprc']:.3f}  recall@1% {row['dev_recall_at_threshold']:.3f} | {summary}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
