"""Tolerant readers for third-party benchmark dumps.

External benchmarks ship as a mixture of ``.json`` (a list, or an object keyed by
split) and ``.jsonl``.  Their field names also drift between releases.  These
helpers keep that variability in one place so the loaders stay readable, and so
a schema surprise produces a clear message rather than a stack trace.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

__all__ = ["first_present", "iter_records", "read_any", "walk_data_files"]


def read_any(path: Path) -> Any:
    """Read a ``.json`` or ``.jsonl`` file into Python objects."""

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def iter_records(payload: Any) -> Iterator[dict[str, Any]]:
    """Yield dict records from any of the shapes benchmarks actually use."""

    if isinstance(payload, dict):
        # Either a single record, or a mapping of split -> records.
        if any(isinstance(value, list | dict) for value in payload.values()):
            for value in payload.values():
                if isinstance(value, list | dict):
                    yield from iter_records(value)
                    continue
            if all(not isinstance(value, list | dict) for value in payload.values()):
                yield payload
            return
        yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
            elif isinstance(item, list | dict):
                yield from iter_records(item)


def walk_data_files(root: Path, suffixes: tuple[str, ...] = (".json", ".jsonl")) -> list[Path]:
    """Every data file under ``root``, sorted for deterministic iteration."""

    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes and not path.name.startswith(".")
    )


def first_present(record: dict[str, Any], *names: str) -> Any | None:
    """Return the first non-empty value among ``names``, case-insensitively."""

    lowered = {str(key).strip().lower().replace(" ", "_"): value for key, value in record.items()}
    for name in names:
        key = name.strip().lower().replace(" ", "_")
        value = lowered.get(key)
        if value not in (None, "", [], {}):
            return value
    return None
