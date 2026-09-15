"""Skip the Studio tests cleanly when the optional Studio dependencies are missing."""

from __future__ import annotations

import importlib.util

_REQUIRED = ("starlette", "uvicorn", "httpx")

if any(importlib.util.find_spec(name) is None for name in _REQUIRED):
    collect_ignore_glob = ["test_*.py"]
