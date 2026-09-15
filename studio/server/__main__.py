"""Run the Studio: ``python -m studio.server`` then open http://127.0.0.1:8700."""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .config import DEFAULT_HOST, DEFAULT_PORT, StudioSettings


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m studio.server", description="LLMSentinel Studio")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--rules-only", action="store_true", help="do not load the transformer checkpoint")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        print("warning: binding beyond localhost makes the Studio reachable from your network")
    app = create_app(StudioSettings(use_transformer=not args.rules_only))
    print(f"LLMSentinel Studio -> http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
