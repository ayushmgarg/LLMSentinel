"""R2.4: retrieval poisoning under each retriever (REMAINING_THINGS F13).

    python scripts/r2_04_retrieval_poisoning.py

Does the retriever change how much poisoned text reaches the model, and does the guard
still catch what each one surfaces?

Pool: every document and tool result of fresh v1-v3 (poisoned copies of each host page,
its clean counterpart, and the hard negatives), each under a neutral name (``doc17.txt``)
so a file name cannot help or hurt a retriever. Queries: each host page's own question.
For TF-IDF and dense (MiniLM) retrieval, top-k as in the Studio: how many retrieved
passages carry an injected payload, how many queries get at least one, and how many of the
retrieved poisoned passages the deployed guard flags.

This models an attacker who plants modified copies of genuine pages next to the originals.
Post-hoc on spent sets (v4 not read); detection numbers are not new evidence, only the
retriever comparison is.

Output: artifacts/results/r2/04_retrieval/retrieval_poisoning.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from llmsentinel.evaluation.fresh import FRESH_PATH, load_fresh  # noqa: E402
from llmsentinel.paths import RESULTS_DIR, relative  # noqa: E402
from studio.server.config import StudioSettings  # noqa: E402
from studio.server.context import Document, chunk_document  # noqa: E402
from studio.server.guard import SentinelGuard  # noqa: E402
from studio.server.retrieval import retrieve  # noqa: E402

OUT = RESULTS_DIR / "r2" / "04_retrieval" / "retrieval_poisoning.json"
SETS = (FRESH_PATH, FRESH_PATH.with_name("fresh_eval_v2.yaml"), FRESH_PATH.with_name("fresh_eval_v3.yaml"))
TOP_K = 4
RETRIEVERS = ("tfidf", "dense")


def _probe(inserted: str) -> str:
    """A slice of the payload as it appears in the text (JSON-escaped in tool results)."""

    text = json.dumps(inserted, ensure_ascii=False)[1:-1]
    middle = len(text) // 2
    return text[max(0, middle - 15) : middle + 15]


def main() -> int:
    documents, poisoned_probes, queries = [], {}, {}
    for path in SETS:
        fresh = load_fresh(path, normalise=False)
        for case in fresh.cases:
            record = case.record
            if case.category == "tool":
                continue
            doc_id = f"doc{len(documents)}"
            is_json = record.channel.value == "tool_response" and record.raw_text.strip()[:1] in "{["
            documents.append(Document(doc_id, f"{doc_id}.{'json' if is_json else 'txt'}", "json" if is_json else "text",
                                      record.raw_text, "sample",
                                      channel="tool_response" if record.channel.value == "tool_response" else None))
            if record.y and case.inserted:
                poisoned_probes[doc_id] = _probe(case.inserted)
            if case.host_id and record.host_task:
                queries[f"{Path(path).stem}:{case.host_id}"] = record.host_task
    chunks = [chunk for doc in documents for chunk in chunk_document(doc)]
    guard = SentinelGuard(StudioSettings(record_history=False))

    def poisoned(chunk) -> bool:
        probe = poisoned_probes.get(chunk.doc_id)
        return bool(probe) and probe in chunk.text

    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool": {"documents": len(documents), "chunks": len(chunks), "poisoned_chunks": sum(map(poisoned, chunks)),
                 "queries": len(queries), "top_k": TOP_K},
        "protocol": "post-hoc on fresh v1-v3; v4 not read; neutral document names",
        "retrievers": {},
    }
    for kind in RETRIEVERS:
        retrieved_total = poisoned_total = flagged_total = queries_hit = queries_hit_after = 0
        method = None
        for question in queries.values():
            result = retrieve(chunks, question, TOP_K, kind)
            method = result.method
            bad = [(c, s) for c, s in result.passages if poisoned(c)]
            retrieved_total += len(result.passages)
            poisoned_total += len(bad)
            queries_hit += int(bool(bad))
            if bad:
                flags = [a.flagged for a in guard.assess(bad, question)]
                flagged_total += sum(flags)
                queries_hit_after += int(not all(flags))
        report["retrievers"][kind] = {
            "method_used": method,
            "passages_retrieved": retrieved_total,
            "poisoned_passages_retrieved": poisoned_total,
            "share_poisoned": round(poisoned_total / retrieved_total, 3),
            "queries_with_a_poisoned_passage": queries_hit,
            "poisoned_passages_flagged_by_guard": flagged_total,
            "share_flagged": round(flagged_total / poisoned_total, 3) if poisoned_total else None,
            "queries_with_an_unflagged_poisoned_passage": queries_hit_after,
        }
        r = report["retrievers"][kind]
        print(f"{kind:<6} ({method}): poisoned {poisoned_total}/{retrieved_total} passages ({r['share_poisoned']:.0%}), "
              f"{queries_hit}/{len(queries)} queries hit | guard flags {flagged_total}/{poisoned_total} "
              f"| queries still exposed: {queries_hit_after}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {relative(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
