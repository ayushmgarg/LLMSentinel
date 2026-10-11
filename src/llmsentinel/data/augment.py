"""Embedded-injection augmentation of the TRAIN split (REMAINING_THINGS B4).

Why: in the canonical train split, 277 of 315 document injections sit at the *end* of
their document (all 250 from BIPIA) and only 14 in the middle, while tool-result
injections are mostly mid-JSON. The transformer learned "a document injection is
appended at the end": on the fresh sets it scored a payload ~1.0 on its own and ~0
once a benign paragraph surrounded it (docs/EXPERIMENTS.md, 2026-09-27 and
2026-10-11). This module adds training examples that break that shortcut.

What: each new record is a benign **train** host with the injected span of a **train**
positive inserted at the start, the middle or the end -- positions in equal shares,
channels balanced. Tool-result hosts in the canonical corpus are single string fields
(one JSON leaf per record), so they are treated as prose; a host that is a whole JSON
document would get the payload in its longest string field. The
span is recorded exactly, so span-aware window labelling applies. Nothing outside the
train split is read: the function refuses records from any other split, so dev
thresholds and every evaluation set stay untouched.

Not a fix for paraphrase: the payloads are the train split's own wordings.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..normalize.pipeline import Normalizer
from ..normalize.segment import segment_sentences
from ..schema import Channel, CorpusRecord, Span, Split, make_record_id

__all__ = ["POSITIONS", "AugmentationReport", "embed_payloads", "payload_position"]

POSITIONS = ("start", "middle", "end")
SOURCE = "augmented-embedded"
CHANNELS = (Channel.RAG_DOCUMENT, Channel.TOOL_RESPONSE)


@dataclass
class AugmentationReport:
    requested: int
    produced: int
    seed: int
    hosts_available: dict[str, int] = field(default_factory=dict)
    payloads_available: int = 0
    distinct_payload_texts_available: int = 0
    distinct_payload_texts_used: int = 0
    max_uses_of_one_payload: int = 0
    by_cell: dict[str, int] = field(default_factory=dict)
    train_positions_before: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "produced": self.produced,
            "seed": self.seed,
            "hosts_available": self.hosts_available,
            "payloads_available": self.payloads_available,
            "distinct_payload_texts_available": self.distinct_payload_texts_available,
            "distinct_payload_texts_used": self.distinct_payload_texts_used,
            "max_uses_of_one_payload": self.max_uses_of_one_payload,
            "by_cell": self.by_cell,
            "train_positions_before": self.train_positions_before,
        }


def payload_position(record: CorpusRecord) -> str:
    """Where a positive's first injected span sits: start, middle, end or whole."""

    span = record.injected_spans[0]
    text = record.text_for_field(span.field) or ""
    before, after = text[: span.start].strip(), text[span.end :].strip()
    if not before and not after:
        return "whole"
    if not before:
        return "start"
    if not after:
        return "end"
    return "middle"


def _payload_text(record: CorpusRecord) -> str:
    span = record.injected_spans[0]
    return (record.text_for_field(span.field) or "")[span.start : span.end].strip()


def _insert(text: str, payload: str, position: str) -> tuple[str, int]:
    """Text with ``payload`` inserted at a sentence boundary; returns (text, start)."""

    if position == "start":
        return f"{payload} {text}", 0
    if position == "end":
        joined = f"{text.rstrip()} {payload}"
        return joined, len(text.rstrip()) + 1
    sentences = segment_sentences(text)
    if len(sentences) < 2:
        # No interior boundary: split at the middle word instead of faking "middle".
        words = text.split(" ")
        cut = len(" ".join(words[: max(1, len(words) // 2)]))
    else:
        cut = sentences[len(sentences) // 2].start
    head, tail = text[:cut].rstrip(), text[cut:].lstrip()
    return f"{head} {payload} {tail}", len(head) + 1


def _longest_leaf(node: Any, path: tuple[Any, ...] = ()) -> tuple[tuple[Any, ...], str] | None:
    best: tuple[tuple[Any, ...], str] | None = None
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    if isinstance(node, str):
        return path, node
    for key, value in items:
        found = _longest_leaf(value, (*path, key))
        if found and (best is None or len(found[1]) > len(best[1])):
            best = found
    return best


def _set(node: Any, path: tuple[Any, ...], value: str) -> None:
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _embed(host: CorpusRecord, payload: str, position: str) -> tuple[str, Span] | None:
    text = host.raw_text
    if host.channel is Channel.TOOL_RESPONSE and text.strip()[:1] in "{[":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            leaf = _longest_leaf(data)
            if leaf is None or not leaf[0]:
                return None
            path, value = leaf
            new_value, _ = _insert(value, payload, position)
            _set(data, path, new_value)
            rendered = json.dumps(data, ensure_ascii=False)
            escaped = json.dumps(payload, ensure_ascii=False)[1:-1]
            start = rendered.find(escaped)
            if start < 0:
                return None
            return rendered, Span(start, start + len(escaped), field="raw_text", note=f"augmented@{position}")
    new_text, start = _insert(text, payload, position)
    return new_text, Span(start, start + len(payload), field="raw_text", note=f"augmented@{position}")


def embed_payloads(
    train: Sequence[CorpusRecord],
    *,
    n: int,
    seed: int,
    normalise: bool = True,
) -> tuple[list[CorpusRecord], AugmentationReport]:
    """``n`` new positives from train hosts and train payloads, balanced over cells."""

    if any(record.split is not Split.TRAIN for record in train):
        raise ValueError("embed_payloads reads the train split only; got records from another split")

    hosts = {
        channel: [r for r in train if not r.y and r.channel is channel and len(r.raw_text.split()) >= 12]
        for channel in CHANNELS
    }
    payloads = [
        r for r in train
        if r.y and r.injected_spans and r.channel in CHANNELS and 3 <= len(_payload_text(r).split()) <= 80
    ]
    report = AugmentationReport(
        requested=n,
        produced=0,
        seed=seed,
        hosts_available={c.value: len(v) for c, v in hosts.items()},
        payloads_available=len(payloads),
        distinct_payload_texts_available=len({_payload_text(r) for r in payloads}),
        train_positions_before=dict(Counter(
            f"{r.channel.value}:{payload_position(r)}" for r in train if r.y and r.injected_spans
        )),
    )
    if not payloads or not all(hosts.values()):
        raise ValueError("not enough train hosts or payloads to augment")

    rng = random.Random(seed)
    cells = [(channel, position) for channel in CHANNELS for position in POSITIONS]
    out: list[CorpusRecord] = []
    counts: Counter[str] = Counter()
    used: Counter[str] = Counter()
    seen: set[str] = set()
    attempts = 0
    # Corpus record ids are not unique, so a pairing is keyed on the texts themselves.
    def text_hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

    while len(out) < n and attempts < n * 50:
        attempts += 1
        channel, position = cells[len(out) % len(cells)]
        host = rng.choice(hosts[channel])
        source = rng.choice(payloads)
        if host.group_id == source.group_id:
            continue
        payload = _payload_text(source)
        key = hashlib.sha1(f"{text_hash(host.raw_text)}|{text_hash(payload)}|{position}".encode()).hexdigest()[:16]
        if key in seen:
            continue
        embedded = _embed(host, payload, position)
        if embedded is None:
            continue
        seen.add(key)
        used[payload] += 1
        text, span = embedded
        record = CorpusRecord(
            record_id=make_record_id(SOURCE, key),
            source_dataset=SOURCE,
            source_document_id=host.source_document_id,
            source_license=f"{host.source_license} + {source.source_license}",
            raw_text=text,
            label=source.label,
            channel=channel,
            attack_type=source.attack_type,
            injected_spans=[span],
            host_task=host.host_task,
            json_path=host.json_path,
            group_id=f"augment:{host.group_id}|{source.group_id}",
            split=Split.TRAIN,
            extra={
                "augmentation": "embedded",
                "position": position,
                "host_record": host.record_id,
                "host_text_sha1": text_hash(host.raw_text),
                "payload_record": source.record_id,
                "payload_text_sha1": text_hash(payload),
            },
        )
        out.append(record)
        counts[f"{channel.value}:{position}"] += 1
    if normalise:
        normalizer = Normalizer()
        for record in out:
            normalizer.normalize_record(record)
    report.produced = len(out)
    report.by_cell = dict(counts)
    report.distinct_payload_texts_used = len(used)
    report.max_uses_of_one_payload = max(used.values(), default=0)
    return out, report
