"""Recursive extraction of string leaves from tool responses, with JSON paths.

An MCP tool result is a JSON document.  The injected instruction is never the
whole document -- it sits in one string field, often several levels deep, and
often inside a string that itself contains serialised JSON.  Scoring the
``json.dumps`` of the whole response would bury a 20-word payload in 4 KB of
punctuation, so the guard scores leaves and reports the path it flagged.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["JsonLeaf", "extract_string_leaves", "parse_json_safely"]

#: Guard against pathological or hostile nesting depth.
_MAX_DEPTH: Final[int] = 24

#: A string leaf shorter than this cannot carry an instruction and only adds noise.
_MIN_LEAF_CHARS: Final[int] = 12

_IDENTIFIER_CHARS: Final[str] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


@dataclass(frozen=True, slots=True)
class JsonLeaf:
    """One string value with the path that locates it in the original document."""

    path: str
    value: str
    #: True when the leaf was recovered by parsing a *string* that contained JSON.
    from_embedded_json: bool = False
    #: Depth of the leaf, used only for display.
    depth: int = 0


def _join(path: str, key: str) -> str:
    if all(char in _IDENTIFIER_CHARS for char in key) and key and not key[0].isdigit():
        return f"{path}.{key}"
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'


def parse_json_safely(text: str) -> tuple[Any | None, str | None]:
    """Parse ``text`` as JSON, returning ``(value, error_message)``."""

    try:
        return json.loads(text), None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, str(exc)


def _looks_like_embedded_json(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) < 2:
        return False
    return (stripped[0], stripped[-1]) in {("{", "}"), ("[", "]")}


def extract_string_leaves(
    document: Any,
    *,
    root: str = "$",
    include_keys: bool = False,
    min_chars: int = _MIN_LEAF_CHARS,
    follow_embedded_json: bool = True,
) -> list[JsonLeaf]:
    """Walk ``document`` and return every string leaf worth scanning.

    Parameters
    ----------
    include_keys:
        Also emit object *keys* as leaves.  Used for tool-metadata scanning,
        where a poisoned parameter name is itself the payload.
    follow_embedded_json:
        When a string leaf parses as a JSON object or array, recurse into it and
        mark the resulting leaves with ``from_embedded_json=True``.  The
        containing string is still emitted, so nothing is silently dropped.
    """

    leaves = list(
        _walk(
            document,
            root,
            0,
            include_keys=include_keys,
            min_chars=min_chars,
            follow_embedded_json=follow_embedded_json,
        )
    )
    seen: set[tuple[str, str]] = set()
    unique: list[JsonLeaf] = []
    for leaf in leaves:
        key = (leaf.path, leaf.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(leaf)
    return unique


def _walk(
    node: Any,
    path: str,
    depth: int,
    *,
    include_keys: bool,
    min_chars: int,
    follow_embedded_json: bool,
) -> Iterator[JsonLeaf]:
    if depth > _MAX_DEPTH:
        return

    if isinstance(node, str):
        if len(node.strip()) >= min_chars:
            yield JsonLeaf(path=path, value=node, depth=depth)
        if follow_embedded_json and _looks_like_embedded_json(node):
            inner, error = parse_json_safely(node)
            if error is None and isinstance(inner, dict | list):
                for leaf in _walk(
                    inner,
                    f"{path}~json",
                    depth + 1,
                    include_keys=include_keys,
                    min_chars=min_chars,
                    follow_embedded_json=follow_embedded_json,
                ):
                    yield JsonLeaf(
                        path=leaf.path,
                        value=leaf.value,
                        from_embedded_json=True,
                        depth=leaf.depth,
                    )
        return

    if isinstance(node, dict):
        for key, value in node.items():
            key_text = str(key)
            child_path = _join(path, key_text)
            if include_keys and len(key_text) >= min_chars:
                yield JsonLeaf(path=f"{child_path}~key", value=key_text, depth=depth + 1)
            yield from _walk(
                value,
                child_path,
                depth + 1,
                include_keys=include_keys,
                min_chars=min_chars,
                follow_embedded_json=follow_embedded_json,
            )
        return

    if isinstance(node, list | tuple):
        for index, value in enumerate(node):
            yield from _walk(
                value,
                f"{path}[{index}]",
                depth + 1,
                include_keys=include_keys,
                min_chars=min_chars,
                follow_embedded_json=follow_embedded_json,
            )
        return

    # int / float / bool / None carry no instruction text.
    return
