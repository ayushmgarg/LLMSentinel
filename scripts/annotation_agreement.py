"""Inter-annotator agreement for the independent double-annotation study.

Two annotators labelled the same 50-record sample from the annotation guideline
alone, without the gold labels and without seeing each other's work. This
computes their agreement with each other (the real inter-annotator number,
including Cohen's kappa) and each annotator's agreement with the corpus's
construction labels, and lists every disagreement so the guideline can be
refined.

    python scripts/annotation_agreement.py
"""

from __future__ import annotations

import json

from llmsentinel.paths import DATA_DIR, DOCS_DIR

INTERIM = DATA_DIR / "interim"


def _load(name: str) -> dict[str, dict]:
    return json.loads((INTERIM / name).read_text(encoding="utf-8"))


def _cohen_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    # Expected agreement under independence of the two label marginals.
    pa1, pb1 = sum(a) / n, sum(b) / n
    expected = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def _agreement(a: list[int], b: list[int]) -> float:
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def main() -> None:
    ann_a = _load("annotator_A.json")
    ann_b = _load("annotator_B.json")
    gold = _load("annotation_gold.json")
    items = sorted(gold)

    la = [int(ann_a[i]["label"]) for i in items]
    lb = [int(ann_b[i]["label"]) for i in items]
    lg = [int(gold[i]["label"]) for i in items]

    print(f"sample size: {len(items)}")
    print()
    print("=== inter-annotator (A vs B) ===")
    print(f"  raw agreement: {_agreement(la, lb):.3f}")
    print(f"  Cohen's kappa: {_cohen_kappa(la, lb):.3f}")
    print()
    print("=== each annotator vs corpus construction label ===")
    print(f"  A vs gold: agreement {_agreement(la, lg):.3f}, kappa {_cohen_kappa(la, lg):.3f}")
    print(f"  B vs gold: agreement {_agreement(lb, lg):.3f}, kappa {_cohen_kappa(lb, lg):.3f}")
    print()

    disagreements = [i for i in items if ann_a[i]["label"] != ann_b[i]["label"]]
    print(f"=== A/B disagreements: {len(disagreements)} ===")
    for i in disagreements:
        print(
            f"  {i} gold={gold[i]['label']} A={ann_a[i]['label']} B={ann_b[i]['label']}"
            f"  A:{ann_a[i].get('reason', '')[:60]!r}  B:{ann_b[i].get('reason', '')[:60]!r}"
        )

    both_wrong = [i for i in items if ann_a[i]["label"] != lg[items.index(i)] and ann_b[i]["label"] != lg[items.index(i)]]
    print()
    print(f"=== items where BOTH annotators differ from the corpus label: {len(both_wrong)} ===")
    for i in both_wrong:
        print(f"  {i} gold={gold[i]['label']} source={gold[i].get('source')} A={ann_a[i]['label']} B={ann_b[i]['label']}")

    report = {
        "n": len(items),
        "inter_annotator_agreement": round(_agreement(la, lb), 4),
        "inter_annotator_kappa": round(_cohen_kappa(la, lb), 4),
        "A_vs_gold_agreement": round(_agreement(la, lg), 4),
        "B_vs_gold_agreement": round(_agreement(lb, lg), 4),
        "A_vs_gold_kappa": round(_cohen_kappa(la, lg), 4),
        "B_vs_gold_kappa": round(_cohen_kappa(lb, lg), 4),
        "n_ab_disagreements": len(disagreements),
        "ab_disagreements": disagreements,
        "both_differ_from_gold": both_wrong,
    }
    out = DOCS_DIR / "annotation_agreement.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"written {out}")


if __name__ == "__main__":
    main()
