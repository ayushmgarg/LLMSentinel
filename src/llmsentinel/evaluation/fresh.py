"""The fresh evaluation set (``data/fresh/fresh_eval.yaml``).

The canonical test split and the out-of-distribution sets were each scored once
and are spent: nothing new may be tuned or re-scored on them. This set is the
place to measure what came later -- the deployed OR decision rule, isolation
quality, the output-side check, the manifest scanner -- without touching them.

The YAML stores a host document with a ``{{PAYLOAD}}`` slot and each payload
separately, so the loader knows the exact injected span, and every host also
yields a benign *counterpart* (the same text, slot removed). A detector that flags
a counterpart is flagging the host, not the attack.

Like the canonical test split, the set is scored once per digest
(``scripts/fresh_eval.py`` keeps the ledger).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..normalize.pipeline import Normalizer
from ..paths import DATA_DIR
from ..schema import AttackType, Channel, CorpusRecord, Label, Span

__all__ = ["FRESH_PATH", "SLOT", "DriftCase", "FreshCase", "FreshSet", "load_fresh"]

FRESH_PATH = DATA_DIR / "fresh" / "fresh_eval.yaml"
SLOT = "{{PAYLOAD}}"
SOURCE = "fresh"
LICENSE = "CC0-1.0"
_ZW = "​"


@dataclass(slots=True)
class FreshCase:
    """One scored record plus what the evaluation needs to know about it."""

    record: CorpusRecord
    #: blatant | paraphrase | soft_claim | hidden | counterpart | hard_negative | tool
    category: str
    host_id: str | None = None
    #: The payload as written, and the exact text inserted for it (after wrapping).
    payload: str | None = None
    inserted: str | None = None
    wrap: str | None = None
    #: Tool cases only.
    server: str | None = None
    tool: dict[str, Any] | None = None


@dataclass(slots=True)
class DriftCase:
    case_id: str
    expect: str
    approved: dict[str, Any] | None
    current: dict[str, Any]


@dataclass(slots=True)
class FreshSet:
    cases: list[FreshCase]
    drift: list[DriftCase]
    digest: str
    path: Path
    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def records(self) -> list[CorpusRecord]:
        return [case.record for case in self.cases]

    def by_category(self, *categories: str) -> list[FreshCase]:
        return [case for case in self.cases if case.category in categories]


def _zero_width(text: str) -> str:
    """Hide words from a keyword match: a zero-width space inside every long word."""

    def split(match: re.Match[str]) -> str:
        word = match.group(0)
        middle = len(word) // 2
        return word[:middle] + _ZW + word[middle:]

    return re.sub(r"[A-Za-z]{4,}", split, text)


def _wrap(payload: str, wrap: str | None) -> str:
    if wrap in (None, ""):
        return payload
    if wrap == "html_comment":
        return f"<!-- {payload} -->"
    if wrap == "zero_width":
        return _zero_width(payload)
    if wrap == "base64":
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return f"Reference data: {encoded}"
    raise ValueError(f"unknown wrap {wrap!r}")


def _fill(host: dict[str, Any], inserted: str | None) -> tuple[str, Span | None]:
    """Host text with the slot filled (or removed), and the inserted span."""

    template = str(host["text"])
    if SLOT not in template:
        raise ValueError(f"host {host['id']!r} has no {SLOT} slot")
    is_json = bool(host.get("json"))
    if inserted is None:
        # Counterpart: drop the slot and the space before it.
        return re.sub(r"\s*" + re.escape(SLOT), "", template).strip(), None
    piece = json.dumps(inserted, ensure_ascii=False)[1:-1] if is_json else inserted
    start = template.index(SLOT)
    text = template[:start] + piece + template[start + len(SLOT) :]
    return text, Span(start, start + len(piece), field="raw_text", note="fresh payload")


def _record(
    local_id: str,
    *,
    text: str,
    label: Label,
    channel: str,
    attack_type: str = "none",
    spans: list[Span] | None = None,
    host_task: str | None = None,
    json_path: str | None = None,
    group: str,
    hard_negative: bool = False,
    extra: dict[str, Any] | None = None,
) -> CorpusRecord:
    return CorpusRecord(
        record_id=f"{SOURCE}-{local_id}",
        source_dataset=SOURCE,
        source_document_id=group,
        source_license=LICENSE,
        raw_text=text,
        label=label,
        channel=Channel.coerce(channel),
        attack_type=AttackType.coerce(attack_type),
        injected_spans=spans or [],
        host_task=host_task,
        json_path=json_path,
        group_id=f"{SOURCE}:{group}",
        is_hard_negative=hard_negative,
        extra=extra or {},
    )


def load_fresh(path: str | Path = FRESH_PATH, *, normalise: bool = True) -> FreshSet:
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8")) or {}
    digest = hashlib.sha256(raw).hexdigest()
    hosts = {str(host["id"]): host for host in data.get("hosts") or []}
    cases: list[FreshCase] = []

    for host_id, host in hosts.items():
        text, _ = _fill(host, None)
        cases.append(
            FreshCase(
                record=_record(
                    f"counterpart-{host_id}",
                    text=text,
                    label=Label.BENIGN,
                    channel=host["channel"],
                    host_task=host.get("host_task"),
                    group=host_id,
                    extra={"category": "counterpart"},
                ),
                category="counterpart",
                host_id=host_id,
            )
        )

    for item in data.get("injections") or []:
        host = hosts[str(item["host"])]
        inserted = _wrap(str(item["payload"]), item.get("wrap"))
        text, span = _fill(host, inserted)
        cases.append(
            FreshCase(
                record=_record(
                    str(item["id"]),
                    text=text,
                    label=Label.INJECTION,
                    channel=host["channel"],
                    attack_type=str(item["attack_type"]),
                    spans=[span] if span else [],
                    host_task=host.get("host_task"),
                    group=str(host["id"]),
                    extra={"category": item["category"], "wrap": item.get("wrap")},
                ),
                category=str(item["category"]),
                host_id=str(host["id"]),
                payload=str(item["payload"]),
                inserted=inserted,
                wrap=item.get("wrap"),
            )
        )

    for item in data.get("hard_negatives") or []:
        cases.append(
            FreshCase(
                record=_record(
                    str(item["id"]),
                    text=str(item["text"]),
                    label=Label.BENIGN,
                    channel=item["channel"],
                    group=str(item["id"]),
                    hard_negative=True,
                    extra={"category": "hard_negative"},
                ),
                category="hard_negative",
            )
        )

    for item in data.get("tools") or []:
        injection = item.get("label") == "injection"
        tool = {"name": item["name"], "description": item["description"]}
        cases.append(
            FreshCase(
                record=_record(
                    str(item["id"]),
                    text=str(item["description"]),
                    label=Label.INJECTION if injection else Label.BENIGN,
                    channel="tool_metadata",
                    attack_type=str(item.get("attack_type") or "none") if injection else "none",
                    spans=[Span(0, len(str(item["description"])), note="whole description")] if injection else [],
                    json_path="$.description",
                    group=str(item["server"]),
                    extra={"category": "tool", "tool": item["name"]},
                ),
                category="tool",
                server=str(item["server"]),
                tool=tool,
            )
        )

    drift = [
        DriftCase(str(item["id"]), str(item["expect"]), item.get("approved"), dict(item["current"]))
        for item in data.get("drift") or []
    ]

    if normalise:
        normalizer = Normalizer()
        for case in cases:
            normalizer.normalize_record(case.record)
    return FreshSet(cases=cases, drift=drift, digest=digest, path=path, hosts=hosts)
