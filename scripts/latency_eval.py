"""Latency and overhead of the guard on this machine (REMAINING_THINGS F2).

    python scripts/latency_eval.py

Measures, on CPU, what LLMSentinel adds before and after a model call:

* one-off start-up: rule engine, transformer checkpoint, sentence encoder;
* per passage (fresh-set documents and tool results): detection with rules only,
  transformer passage scoring, transformer segment scoring (deployed), and detection +
  isolation as the Studio runs it;
* retrieval of the top 4 passages from the sample pack: TF-IDF vs dense;
* the output-side check on a typical answer.

Every timing is wall-clock with warm-up runs discarded; mean, p50 and p95 are
reported with the machine description. Run it on an otherwise idle machine; nothing
here is a benchmark against other systems, only the cost of this guard.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from llmsentinel.evaluation.fresh import FRESH_PATH, load_fresh  # noqa: E402
from llmsentinel.output_check import check_output  # noqa: E402
from llmsentinel.paths import RESULTS_DIR, relative  # noqa: E402
from studio.server.config import StudioSettings  # noqa: E402
from studio.server.context import Document, chunk_document, load_samples  # noqa: E402
from studio.server.guard import SentinelGuard  # noqa: E402
from studio.server.retrieval import retrieve  # noqa: E402

OUT = RESULTS_DIR / "latency.json"
WARMUP = 3


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 2),
        "p50_ms": round(statistics.median(values), 2),
        "p95_ms": round(p95, 2),
    }


def timed(fn: Any) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


def passages() -> list[tuple[Any, str]]:
    out = []
    for path in (FRESH_PATH, FRESH_PATH.with_name("fresh_eval_v2.yaml")):
        for case in load_fresh(path, normalise=False).cases:
            record = case.record
            if case.category == "tool":
                continue
            kind = "json" if record.channel.value == "tool_response" else "text"
            doc = Document("lat", "lat.json" if kind == "json" else "lat.txt", kind, record.raw_text, "upload",
                           channel="tool_response" if kind == "json" else None)
            out.extend((chunk, record.host_task or "") for chunk in chunk_document(doc))
    return out


def per_passage(guard: SentinelGuard, items: list[tuple[Any, str]], *, isolate: bool) -> dict[str, float]:
    for chunk, task in items[:WARMUP]:
        guard.assess([(chunk, 1.0)], task, isolate=isolate)
    return stats([timed(lambda c=chunk, t=task: guard.assess([(c, 1.0)], t, isolate=isolate)) for chunk, task in items])


def main() -> int:
    items = passages()
    result: dict[str, Any] = {
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "passages": len(items),
        "startup_ms": {},
        "per_passage": {},
        "retrieval_top4": {},
    }
    import torch

    result["machine"]["torch_threads"] = torch.get_num_threads()

    result["startup_ms"]["rules_only_guard"] = round(timed(lambda: SentinelGuard(StudioSettings(use_transformer=False))), 1)
    holder: dict[str, SentinelGuard] = {}
    result["startup_ms"]["transformer_guard"] = round(
        timed(lambda: holder.setdefault("g", SentinelGuard(StudioSettings(segment_scoring=True)))), 1
    )
    segment_guard = holder["g"]
    passage_guard = SentinelGuard(StudioSettings(segment_scoring=False))
    rules_guard = SentinelGuard(StudioSettings(use_transformer=False))

    result["per_passage"]["rules_only_detect"] = per_passage(rules_guard, items, isolate=False)
    result["per_passage"]["transformer_passage_detect"] = per_passage(passage_guard, items, isolate=False)
    result["per_passage"]["transformer_segment_detect"] = per_passage(segment_guard, items, isolate=False)
    result["per_passage"]["transformer_segment_detect_and_isolate"] = per_passage(segment_guard, items, isolate=True)

    samples, questions, _ = load_samples()
    chunks = [chunk for info in samples.values() for chunk in chunk_document(info.doc)]
    from studio.server.retrieval import load_encoder

    result["startup_ms"]["sentence_encoder"] = round(timed(load_encoder), 1)
    for kind in ("tfidf", "dense"):
        for question in questions[:WARMUP]:
            retrieve(chunks, question, 4, kind)
        result["retrieval_top4"][kind] = stats(
            [timed(lambda q=question, k=kind: retrieve(chunks, q, 4, k)) for question in questions * 3]
        )
    result["retrieval_top4"]["chunks"] = len(chunks)

    answer = "Deleted notes stay in Trash for thirty days, then they are removed permanently."
    context = [chunk.text for chunk in chunks[:4]]
    result["output_check"] = stats([timed(lambda: check_output(answer, context=context)) for _ in range(50)])

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
