"""Build the embedded-injection augmentation of the train split (REMAINING_THINGS B4).

    python scripts/augment_embedded.py            # writes data/processed/augmented/
    python scripts/augment_embedded.py --check    # rebuild and compare with the committed digest

Deterministic: the same corpus and seed give the same file, so the cluster run can
verify it trains on exactly the committed augmentation (``--check``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmsentinel.data.augment import embed_payloads  # noqa: E402
from llmsentinel.data.splits import corpus_digest  # noqa: E402
from llmsentinel.evaluation import load_splits  # noqa: E402
from llmsentinel.paths import CORPUS_PATH, PROCESSED_DIR, relative  # noqa: E402
from llmsentinel.schema import read_jsonl, write_jsonl  # noqa: E402

OUT_DIR = PROCESSED_DIR / "augmented"
OUT = OUT_DIR / "train_embedded.jsonl"
MANIFEST = OUT_DIR / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=900, help="augmented positives to create (default 900)")
    parser.add_argument("--seed", type=int, default=20250909)
    parser.add_argument("--check", action="store_true", help="verify the committed file instead of writing")
    args = parser.parse_args()

    splits = load_splits(CORPUS_PATH)
    records, report = embed_payloads(splits["train"], n=args.n, seed=args.seed)
    digest = corpus_digest(records)
    if args.check:
        committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
        existing = corpus_digest(read_jsonl(OUT))
        ok = committed["digest"] == digest == existing
        print(f"rebuilt {digest} | committed {committed['digest']} | file {existing} -> {'OK' if ok else 'MISMATCH'}")
        return 0 if ok else 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(records, OUT)
    manifest = {
        "digest": digest,
        "corpus": relative(CORPUS_PATH),
        "corpus_digest": corpus_digest(read_jsonl(CORPUS_PATH)),
        "train_records": len(splits["train"]),
        **report.to_dict(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print(f"wrote {relative(OUT)} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
