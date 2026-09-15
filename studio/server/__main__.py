"""Run the Studio: ``python -m studio.server`` then open http://127.0.0.1:8700."""

from __future__ import annotations

import argparse

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
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        print("warning: binding beyond localhost makes the Studio reachable from your network")
    settings = StudioSettings(use_transformer=not args.rules_only)
    if args.max_tokens:
        settings.max_tokens = max(MIN_ANSWER_TOKENS, min(MAX_ANSWER_TOKENS, args.max_tokens))
    app = create_app(settings)
    print(f"LLMSentinel Studio -> http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
