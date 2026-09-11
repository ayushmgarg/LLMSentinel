"""Generate the report figures from whatever results are current.

Two kinds of figure:

* **From the results JSON** (`artifacts/results/results_*.json`) — the headline
  AUPRC comparison and the per-channel breakdown, so the bars match the numbers
  the harness reported exactly.
* **Re-scored for curves** — precision-recall and a reliability (calibration)
  diagram need per-record scores, which the results JSON does not store, so the
  splits are re-scored here. This is visualisation only: it selects nothing and
  changes no reported number. It loads the transformer if a checkpoint is
  present, otherwise it draws the curves it can.

Everything reads the *current* corpus and checkpoint, so re-running after a
retrain refreshes every figure. Output: PNGs under `artifacts/figures/`.

    python scripts/make_figures.py
"""

from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from llmsentinel.evaluation import load_splits
from llmsentinel.evaluation.metrics import average_precision
from llmsentinel.models import RulesScorer, TfidfBaseline
from llmsentinel.paths import CORPUS_PATH, FIGURES_DIR, RESULTS_DIR
from llmsentinel.schema import Channel, read_jsonl

_SYSTEMS_ORDER = ["tfidf-word", "rules-only", "transformer", "hybrid"]


def _load_results(name: str) -> list[dict]:
    path = RESULTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _auprc_by_system(entries: list[dict], split: str) -> dict[str, float]:
    out = {}
    for entry in entries:
        block = entry.get(split)
        if block:
            out[entry["name"]] = block["auprc"]
    return out


def fig_corpus_composition() -> None:
    records = read_jsonl(CORPUS_PATH)
    splits = ["train", "dev", "test"]
    pos = [sum(1 for r in records if (r.split and r.split.value == s) and r.y) for s in splits]
    neg = [sum(1 for r in records if (r.split and r.split.value == s) and not r.y) for s in splits]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(splits, neg, label="benign", color="#4c78a8")
    ax.bar(splits, pos, bottom=neg, label="injection", color="#e45756")
    for i in range(len(splits)):
        ax.text(i, neg[i] + pos[i] + 5, f"{neg[i]+pos[i]}", ha="center", fontsize=9)
    ax.set_ylabel("records")
    ax.set_title(f"Corpus composition by split (n={len(records)})")
    ax.legend()
    _save(fig, "corpus_composition.png")


def fig_model_comparison() -> None:
    dev = _auprc_by_system(_load_results("results_dev.json"), "dev")
    test = _auprc_by_system(_load_results("results_test.json"), "test")
    systems = [s for s in _SYSTEMS_ORDER if s in dev or s in test]
    if not systems:
        return
    x = np.arange(len(systems))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - 0.2, [dev.get(s, np.nan) for s in systems], 0.4, label="dev", color="#4c78a8")
    ax.bar(x + 0.2, [test.get(s, np.nan) for s in systems], 0.4, label="test", color="#f58518")
    ax.set_xticks(x)
    ax.set_xticklabels(systems, rotation=15)
    ax.set_ylabel("AUPRC")
    ax.set_ylim(0, 1)
    ax.set_title("AUPRC by system (dev vs held-out test)")
    ax.legend()
    _save(fig, "model_comparison.png")


def fig_per_channel() -> None:
    entries = _load_results("results_test.json")
    channels = [c.value for c in Channel if c is not Channel.UNKNOWN]
    systems = [e for e in entries if e["name"] in ("rules-only", "hybrid") and e.get("test")]
    if not systems:
        return
    x = np.arange(len(channels))
    fig, ax = plt.subplots(figsize=(7, 4))
    width = 0.8 / max(1, len(systems))
    for i, entry in enumerate(systems):
        per = entry["test"].get("per_channel", {})
        vals = [per.get(c, {}).get("auprc", np.nan) for c in channels]
        ax.bar(x + i * width - 0.4 + width / 2, vals, width, label=entry["name"])
    ax.set_xticks(x)
    ax.set_xticklabels(channels, rotation=15)
    ax.set_ylabel("AUPRC (test)")
    ax.set_ylim(0, 1)
    ax.set_title("Per-channel AUPRC on test")
    ax.legend()
    _save(fig, "per_channel.png")


def _scored_systems():
    """Re-score dev/test for curve figures. Visualisation only."""

    splits = load_splits()
    rules = RulesScorer()
    systems = {"rules-only": rules, "tfidf-word": TfidfBaseline().fit(splits["train"])}
    transformer = None
    checkpoint = RESULTS_DIR.parent / "models" / "transformer"
    from llmsentinel.models.transformer import TransformerScorer, torch_available

    if checkpoint.is_dir() and torch_available():
        transformer = TransformerScorer.load(checkpoint)
        systems["transformer"] = transformer
    from llmsentinel.models.fusion import FusionScorer

    fusion = FusionScorer(rules=rules, transformer=transformer)
    fusion.fit(splits["dev"])
    systems["hybrid"] = fusion
    return splits, systems


def _pr_points(y: list[int], scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-scores)
    y_sorted = np.asarray(y)[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / max(1, y_sorted.sum())
    return recall, precision


def fig_pr_and_calibration(splits, systems) -> None:
    test = splits["test"]
    y = [r.y for r in test]

    fig, ax = plt.subplots(figsize=(6, 5))
    for name in _SYSTEMS_ORDER:
        if name not in systems:
            continue
        scores = np.asarray(systems[name].score(test), dtype=float)
        recall, precision = _pr_points(y, scores)
        ax.plot(recall, precision, label=f"{name} (AP={average_precision(y, scores):.3f})")
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_ylim(0, 1.02)
    ax.set_title("Precision-recall on held-out test")
    ax.legend(loc="lower left", fontsize=8)
    _save(fig, "pr_curve.png")

    # Reliability diagram for the hybrid.
    if "hybrid" in systems:
        scores = np.asarray(systems["hybrid"].score(test), dtype=float)
        bins = np.linspace(0, 1, 11)
        idx = np.digitize(scores, bins) - 1
        xs, ys = [], []
        for b in range(10):
            mask = idx == b
            if mask.any():
                xs.append(scores[mask].mean())
                ys.append(np.asarray(y)[mask].mean())
        fig2, ax2 = plt.subplots(figsize=(5, 5))
        ax2.plot([0, 1], [0, 1], "--", color="grey", label="perfect")
        ax2.plot(xs, ys, "o-", color="#e45756", label="hybrid")
        ax2.set_xlabel("mean predicted probability")
        ax2.set_ylabel("observed frequency of injection")
        ax2.set_title("Reliability (hybrid, test) — descriptive, not calibrated")
        ax2.legend()
        _save(fig2, "calibration.png")


def _save(fig, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path.relative_to(FIGURES_DIR.parent.parent)}")


def main() -> int:
    fig_corpus_composition()
    fig_model_comparison()
    fig_per_channel()
    splits, systems = _scored_systems()
    fig_pr_and_calibration(splits, systems)
    print("figures written to", FIGURES_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
