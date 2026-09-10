"""Does the semantic / context-aware layer add anything over lexical matching?

Two comparisons, both logged to the experiment log by hand from this output:

1. On the corpus dev split, compare a TF-IDF word baseline (lexical), the
   rule engine, and the semantic scorer with and without source features, using
   the same harness and thresholds as every other system.

2. On the hand-written contrastive cases, report — per category — what the
   corroboration-gated conflict flag does and what the learned scorer does. This
   is where the layer is supposed to shine (vocabulary-reuse attacks) and where a
   naive use of topicality would misfire (benign off-topic text); both are
   reported honestly rather than hidden.

Deterministic and offline (lexical embedder). Set ``LLMSENTINEL_EMBEDDER=st`` to
use the neural backend if the ``semantic`` extra and weights are installed.

    python scripts/semantic_eval.py
"""

from __future__ import annotations

import sys

import numpy as np

from llmsentinel.evaluation import load_splits, results_table, run_system
from llmsentinel.models import RulesScorer, TfidfBaseline
from llmsentinel.semantic import (
    SemanticFeatureExtractor,
    SemanticScorer,
    build_context,
    load_contrastive_cases,
)
from llmsentinel.semantic.similarity import default_embedder


def _corpus_comparison() -> None:
    splits = load_splits()
    systems = [
        TfidfBaseline(),
        RulesScorer(),
        SemanticScorer(),
        SemanticScorer(use_source_features=False),
    ]
    results = [run_system(s, splits, measure_latency=False) for s in systems]
    print("## Dev comparison (lexical vs rules vs semantic)\n")
    print(results_table(results, split="dev"))
    print()
    for result in results:
        if result.name.startswith("semantic"):
            top = result.config.get("top_features", [])[:5]
            joined = ", ".join(f"{f['feature']}={f['weight']:+.2f}" for f in top)
            print(f"- `{result.name}` top weights: {joined}")


def _contrastive_report() -> None:
    cases = load_contrastive_cases()
    extractor = SemanticFeatureExtractor()
    scorer = SemanticScorer().fit(load_splits()["dev"])

    print(f"\n## Contrastive cases (embedder: {default_embedder().name})\n")
    print("| category | id | label | conflict_flag | scorer | lexical_overlap |")
    print("|---|---|---|---|---|---|")
    for case in cases:
        record = case.as_record()
        feats = extractor.one(*build_context(record))
        score = float(scorer.score([record])[0])
        print(
            f"| {case.category} | {case.case_id} | {case.label.name.lower()} | "
            f"{'FLAG' if feats.conflict_flag else '-'} | {score:.3f} | "
            f"{feats.values['lexical_overlap']:.2f} |"
        )

    # Honest headline: does the corroboration-gated flag get the curated cases
    # right, and where does the learned scorer's use of topicality misfire?
    flag_correct = sum(
        (extractor.one(*build_context(c.as_record())).conflict_flag) == (c.label.value == 1)
        for c in cases
        if c.category != "lexical_vs_semantic"  # reported-speech hard negatives excepted
    )
    total = sum(1 for c in cases if c.category != "lexical_vs_semantic")
    print(
        f"\nConflict flag on vocab-reuse + off-topic cases: {flag_correct}/{total} correct "
        f"(reported-speech hard negatives in `lexical_vs_semantic` are the rule "
        f"engine's citation-suppression job, not this flag's)."
    )

    offtopic = [c for c in cases if c.category == "benign_off_topic"]
    ot_scores = scorer.score([c.as_record() for c in offtopic])
    print(
        f"Caveat: the learned scorer gives benign off-topic text a mean score of "
        f"{float(np.mean(ot_scores)):.3f} - topicality alone is a weak, noisy signal, "
        f"which is why detection requires the corroboration features, not `off_topic`."
    )


def main() -> int:
    _corpus_comparison()
    _contrastive_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
