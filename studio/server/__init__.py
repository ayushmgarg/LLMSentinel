"""Backend for LLMSentinel Studio (Starlette + uvicorn, both already project deps)."""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
