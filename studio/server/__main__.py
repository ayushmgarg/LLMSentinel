"""Run the Studio: ``python -m studio.server`` then open http://127.0.0.1:8700."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app
from .config import DEFAULT_HOST, DEFAULT_PORT, MAX_ANSWER_TOKENS, MIN_ANSWER_TOKENS, StudioSettings


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m studio.server", description="LLMSentinel Studio")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--rules-only", action="store_true", help="do not load the transformer checkpoint")
    parser.add_argument(
        "--max-tokens", type=int, default=None,
        help="default answer-token cap for models without a profile in studio/model_profiles.yaml",
    )
    parser.add_argument(
        "--retriever", choices=["dense", "tfidf"], default="dense",
        help="passage retrieval: sentence embeddings (default) or TF-IDF (reproducible, no model)",
    )
    parser.add_argument(
        "--passage-scoring", action="store_true",
        help="score whole passages only (the pre-2026-09-27 behaviour); default scores each sentence too",
    )
    parser.add_argument("--no-history", action="store_true", help="do not record comparisons in the analyst history")
    parser.add_argument("--history", default=None, help="analyst history database (default: artifacts/analyst/history.sqlite3)")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        print("warning: binding beyond localhost makes the Studio reachable from your network")
    settings = StudioSettings(
        use_transformer=not args.rules_only,
        record_history=not args.no_history,
        history_path=Path(args.history) if args.history else None,
        retriever=args.retriever,
        segment_scoring=not args.passage_scoring,
    )
    if args.max_tokens:
        settings.max_tokens = max(MIN_ANSWER_TOKENS, min(MAX_ANSWER_TOKENS, args.max_tokens))
    app = create_app(settings)
    print(f"LLMSentinel Studio -> http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
