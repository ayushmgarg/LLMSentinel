"""The built-in seed corpus: an offline, redistributable, matched-pair dataset.

Why this exists
---------------
BIPIA, InjecAgent and MCPTox are the right benchmarks for the final numbers, but
they must be downloaded, they carry their own licences, and none of them can be
committed to a student repository.  The project would then have no reproducible
starting point, and the Week 1 exit criterion ("a command builds the corpus")
would depend on a network.

This loader generates a corpus from the YAML files in ``data/seed`` that follows
the same construction as BIPIA -- payloads inserted into host documents at
controlled positions -- with two design rules that matter for validity:

**Matched pairs.**  Every host document appears with a payload *and* with a
harmless insertion at the same positions.  Structure therefore carries no label
information, so a model cannot win by detecting "this document has an extra
paragraph".

**Grouped identity.**  Every record declares the payload/distractor family it
came from *and* the host document it was inserted into.  The splitter keeps both
keys inside a single split, so no paraphrase of a test payload and no fragment
of a test host document can appear in training.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ...constants import DEFAULT_SEED
from ...paths import SEED_DIR
from ...schema import AttackType, Channel, CorpusRecord, Label, Span, make_record_id
from .base import Loader, SourceSpec

__all__ = ["BuiltinSeedLoader", "InsertionSpec", "insert_at"]

_SOURCE_NAME = "builtin"

#: Where an insertion is placed inside the host text.
POSITIONS: tuple[str, ...] = ("start", "middle", "end")

#: Hosts shorter than this never receive a mid-text insertion.
_MIN_CHARS_FOR_MIDDLE: int = 400

_ZERO_WIDTH = "​"
_HOMOGLYPH_MAP = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с"}


@dataclass(frozen=True, slots=True)
class InsertionSpec:
    """One piece of text to insert into a host document, with its identity."""

    content_id: str
    family: str
    text: str
    label: Label
    attack_type: AttackType = AttackType.NONE
    encode: str | None = None
    is_hard_negative: bool = False
    channels: tuple[str, ...] = ("rag_document", "tool_response", "tool_metadata")


@dataclass(slots=True)
class BuiltinConfig:
    """Generation budget.  Changing any value changes the corpus, so it is
    recorded in the corpus card and in the experiment log."""

    seed: int = DEFAULT_SEED
    #: Maximum host documents paired with each *payload*, per channel.
    hosts_per_insertion: int = 10
    #: Maximum host documents paired with each benign insertion (distractor or
    #: hard negative).  Higher than the payload budget because there are fewer
    #: benign insertion families and the negative class must not be the scarce
    #: side of the corpus.
    hosts_per_benign_insertion: int = 30
    #: Positions sampled per (insertion, host) pair.
    positions_per_pair: int = 3
    #: Benign records per injection record, held identical in every split so
    #: that average precision is comparable across splits.
    benign_to_injection_ratio: float = 2.0
    #: Hard cap on generated composed records, before split filtering.
    max_composed: int = 6000


class BuiltinSeedLoader(Loader):
    """Builds the offline seed corpus from ``data/seed/*.yaml``."""

    spec = SourceSpec(
        name="llmsentinel-builtin",
        homepage="local: data/seed/",
        license="CC0-1.0",
        citation=(
            "LLMSentinel built-in seed corpus (this project). Payload templates are "
            "re-implementations of publicly documented indirect prompt-injection "
            "patterns; no third-party text is copied."
        ),
        acquisition="Ships with the repository; no download required.",
        notes=(
            "Synthetic and matched-pair by construction. Results on this corpus are "
            "an upper bound on template diversity and must not be reported as "
            "benchmark numbers for BIPIA or InjecAgent."
        ),
    )

    def __init__(
        self, root: Path | None = None, config: BuiltinConfig | None = None
    ) -> None:
        super().__init__(root or SEED_DIR)
        self.config = config or BuiltinConfig()
        self._data: dict[str, Any] = {}

    # ------------------------------------------------------------ availability
    def available(self) -> bool:
        root = self.root or SEED_DIR
        return all(
            (root / name).is_file()
            for name in (
                "payloads.yaml",
                "host_documents.yaml",
                "hard_negatives.yaml",
                "benign_extra.yaml",
            )
        )

    def _host_data(self) -> dict[str, Any]:
        """Host documents, merged from the base file and any ``*_extra`` file.

        Splitting the host pool across files keeps each one reviewable by hand;
        the loader sees a single merged pool, so a document's file of origin
        never affects the corpus.
        """

        merged = dict(self._load_yaml("host_documents.yaml"))
        extra_path = (self.root or SEED_DIR) / "host_documents_extra.yaml"
        if extra_path.is_file():
            extra = self._load_yaml("host_documents_extra.yaml")
            for key in ("rag_documents", "tool_responses", "tool_manifests"):
                merged[key] = list(merged.get(key, [])) + list(extra.get(key, []))
        seen: set[str] = set()
        for key in ("rag_documents", "tool_responses", "tool_manifests"):
            unique = []
            for document in merged.get(key, []):
                if document["doc_id"] in seen:
                    continue
                seen.add(document["doc_id"])
                unique.append(document)
            merged[key] = unique
        return merged

    def _load_yaml(self, name: str) -> dict[str, Any]:
        if name not in self._data:
            path = (self.root or SEED_DIR) / name
            with path.open("r", encoding="utf-8") as handle:
                self._data[name] = yaml.safe_load(handle)
        return self._data[name]

    # ------------------------------------------------------------------- load
    def load(self) -> Iterator[CorpusRecord]:
        yield from self._standalone_records()
        yield from self._composed_records()

    # ---------------------------------------------------------- standalone set
    def _standalone_records(self) -> Iterator[CorpusRecord]:
        """Records that are used as-is: clean hosts, benign prose, hard negatives."""

        hosts = self._host_data()
        benign = self._load_yaml("benign_extra.yaml")
        hard = self._load_yaml("hard_negatives.yaml")

        for document in hosts.get("rag_documents", []):
            text = str(document["text"]).strip()
            yield self._record(
                local_key=f"clean/{document['doc_id']}",
                text=text,
                label=Label.BENIGN,
                channel=Channel.RAG_DOCUMENT,
                group_id=f"host:{document['doc_id']}",
                host_group=f"host:{document['doc_id']}",
                source_document_id=document["doc_id"],
                host_task=document.get("host_task"),
                license=hosts.get("license", "CC0-1.0"),
                extra={"variant": "clean_host"},
            )

        for document in hosts.get("tool_responses", []):
            for path, value in _injectable_leaves(document["json"]):
                yield self._record(
                    local_key=f"clean/{document['doc_id']}/{path}",
                    text=value,
                    label=Label.BENIGN,
                    channel=Channel.TOOL_RESPONSE,
                    group_id=f"host:{document['doc_id']}::{path}",
                    host_group=f"host:{document['doc_id']}::{path}",
                    source_document_id=document["doc_id"],
                    host_task=document.get("host_task"),
                    json_path=path,
                    license=hosts.get("license", "CC0-1.0"),
                    extra={"variant": "clean_host", "tool_name": document.get("tool_name", "")},
                )

        for document in hosts.get("tool_manifests", []):
            for path, value in _manifest_leaves(document["tool"]):
                yield self._record(
                    local_key=f"clean/{document['doc_id']}/{path}",
                    text=value,
                    label=Label.BENIGN,
                    channel=Channel.TOOL_METADATA,
                    group_id=f"host:{document['doc_id']}::{path}",
                    host_group=f"host:{document['doc_id']}::{path}",
                    source_document_id=document["doc_id"],
                    host_task=document.get("host_task"),
                    json_path=path,
                    license=hosts.get("license", "CC0-1.0"),
                    extra={"variant": "clean_host", "tool_name": document["tool"].get("name", "")},
                )

        for item in benign.get("items", []):
            yield self._record(
                local_key=f"benign/{item['id']}",
                text=str(item["text"]).strip(),
                label=Label.BENIGN,
                channel=Channel.coerce(item.get("channel", "rag_document")),
                group_id=f"benign:{item['id']}",
                host_group=f"benign:{item['id']}",
                source_document_id=item["id"],
                json_path=item.get("json_path"),
                license=benign.get("license", "CC0-1.0"),
                extra={"variant": "standalone_benign"},
            )

        for item in hard.get("items", []):
            yield self._record(
                local_key=f"hardneg/{item['id']}",
                text=str(item["text"]).strip(),
                label=Label.BENIGN,
                channel=Channel.coerce(item.get("channel", "rag_document")),
                group_id=f"hardneg:{item['id']}",
                host_group=f"hardneg:{item['id']}",
                source_document_id=item["id"],
                json_path=item.get("json_path"),
                license=hard.get("license", "CC0-1.0"),
                is_hard_negative=True,
                extra={"variant": "standalone_hard_negative", "category": item.get("category", "")},
            )

    # ------------------------------------------------------------ composed set
    def _composed_records(self) -> Iterator[CorpusRecord]:
        """Pair insertions with hosts *inside one split at a time*.

        Pairing across splits and dropping the mismatches afterwards would be
        simpler, but then a pair's survival probability is quadratic in the
        split ratio: dev and test collapse to a few per cent of the corpus, and
        the test split can end up with no positives at all.  Generating within a
        split keeps the requested ratios exactly and drops nothing, while both
        guarantees still hold -- a content family and a host document each live
        in exactly one split.  :func:`llmsentinel.data.splits.apply_splits`
        re-derives the same assignment independently, and the leakage audit
        verifies it against the written corpus.
        """

        insertions = list(self._insertions())
        hosts = self._hosts()
        assignments = self._assign(insertions, hosts)

        pairs: list[tuple[InsertionSpec, dict[str, Any], str]] = []
        for insertion in insertions:
            insertion_split = assignments[insertion.family]
            for channel in insertion.channels:
                candidates = [
                    host
                    for host in hosts.get(channel, [])
                    if assignments[f"host:{host['doc_id']}"] == insertion_split
                ]
                if not candidates:
                    continue
                budget = (
                    self.config.hosts_per_insertion
                    if insertion.label is Label.INJECTION
                    else self.config.hosts_per_benign_insertion
                )
                chosen = _deterministic_sample(
                    candidates,
                    budget,
                    key=f"{insertion.content_id}|{channel}",
                    seed=self.config.seed,
                )
                for host in chosen:
                    # A mid-sentence split of a short JSON leaf produces a
                    # visibly clipped host ("Exports above two million rows are
                    # split into several assistant: ..."), which no tool would
                    # ever return.  Short hosts get the payload at one end.
                    host_text = str(host.get("text") or host.get("leaf_value") or "")
                    allowed = (
                        POSITIONS
                        if len(host_text) >= _MIN_CHARS_FOR_MIDDLE
                        else tuple(p for p in POSITIONS if p != "middle")
                    )
                    positions = _deterministic_sample(
                        list(allowed),
                        self.config.positions_per_pair,
                        key=f"{insertion.content_id}|{host['doc_id']}",
                        seed=self.config.seed,
                    )
                    # Every generated combination is unique: one insertion, one
                    # host leaf, one position.
                    for position in positions:
                        pairs.append((insertion, host, position))

        grouped = _group_by_split_and_channel(pairs, assignments)
        for group in grouped.values():
            random.Random(self.config.seed).shuffle(group)
        for group in _allocate(grouped, self.config).values():
            for insertion, host, position in group:
                record = self._compose(insertion, host, position)
                if record is not None:
                    yield record

    def _assign(
        self, insertions: Sequence[InsertionSpec], hosts: dict[str, list[dict[str, Any]]]
    ) -> dict[str, str]:
        """Split assignment for every family and host key, as plain strings."""

        from ..splits import SplitConfig, assign_group_splits

        keys = {insertion.family for insertion in insertions}
        keys.update(f"host:{host['doc_id']}" for group in hosts.values() for host in group)
        config = SplitConfig(seed=self.config.seed)
        return {key: split.value for key, split in assign_group_splits(keys, config).items()}

    def _compose(
        self, insertion: InsertionSpec, host: dict[str, Any], position: str
    ) -> CorpusRecord | None:
        payload_text = _encode(insertion.text, insertion.encode)
        channel = Channel.coerce(host["channel"])

        if channel is Channel.RAG_DOCUMENT:
            base = str(host["text"]).strip()
            json_path = None
        else:
            base = str(host["leaf_value"])
            json_path = host["leaf_path"]

        composed, start, end = insert_at(base, payload_text, position)
        if not composed.strip():
            return None

        spans = (
            [Span(start, end, field="raw_text", note=f"{insertion.family}@{position}")]
            if insertion.label is Label.INJECTION
            else []
        )
        return self._record(
            local_key=f"mix/{host['doc_id']}/{insertion.content_id}/{position}",
            text=composed,
            label=insertion.label,
            channel=channel,
            group_id=insertion.family,
            host_group=f"host:{host['doc_id']}",
            source_document_id=host["doc_id"],
            host_task=host.get("host_task"),
            json_path=json_path,
            attack_type=insertion.attack_type,
            injected_spans=spans,
            is_hard_negative=insertion.is_hard_negative,
            license="CC0-1.0",
            extra={
                "variant": "composed",
                "insertion_id": insertion.content_id,
                "insertion_family": insertion.family,
                "position": position,
                "encoding": insertion.encode or "none",
                "tool_name": host.get("tool_name", ""),
            },
        )

    # ------------------------------------------------------------- ingredients
    def _insertions(self) -> Iterator[InsertionSpec]:
        payloads = self._load_yaml("payloads.yaml")
        benign = self._load_yaml("benign_extra.yaml")
        hard = self._load_yaml("hard_negatives.yaml")

        for family in payloads.get("families", []):
            channels = tuple(family.get("channels", ("rag_document",)))
            for index, variant in enumerate(family.get("variants", [])):
                yield InsertionSpec(
                    content_id=f"{family['family']}#{index}",
                    family=f"family:{family['family']}",
                    text=str(variant).strip(),
                    label=Label.INJECTION,
                    attack_type=AttackType.coerce(family["attack_type"]),
                    encode=family.get("encode"),
                    channels=channels,
                )

        for item in benign.get("distractors", []):
            yield InsertionSpec(
                content_id=f"dx/{item['id']}",
                family=f"distractor:{item['id']}",
                text=str(item["text"]).strip(),
                label=Label.BENIGN,
                # Page furniture ("see also", "last updated") belongs in a
                # document or a tool result. A tool *description* never carries
                # it, and pairing it there produced records no real system would
                # ever see.
                channels=("rag_document", "tool_response"),
            )

        for item in benign.get("metadata_distractors", []):
            yield InsertionSpec(
                content_id=f"mdx/{item['id']}",
                family=f"distractor:{item['id']}",
                text=str(item["text"]).strip(),
                label=Label.BENIGN,
                channels=("tool_metadata",),
            )

        # Hard negatives are inserted too: a quoted attack embedded in a real
        # document is the single most realistic false-positive source.
        for item in hard.get("items", []):
            # Each hard negative declares the channel it was written for.  An
            # exam rubric or a security blog post is realistic inside a
            # retrieved document, not inside a tool declaration, and the manual
            # audit found exactly those implausible pairings in the first build.
            channel = str(item.get("channel", "rag_document"))
            channels = (channel,) if channel != "rag_document" else ("rag_document", "tool_response")
            yield InsertionSpec(
                content_id=f"hn/{item['id']}",
                family=f"hardneg:{item['id']}",
                text=" ".join(str(item["text"]).split()),
                label=Label.BENIGN,
                is_hard_negative=True,
                channels=channels,
            )

    def _hosts(self) -> dict[str, list[dict[str, Any]]]:
        raw = self._host_data()
        hosts: dict[str, list[dict[str, Any]]] = {
            "rag_document": [],
            "tool_response": [],
            "tool_metadata": [],
        }

        for document in raw.get("rag_documents", []):
            hosts["rag_document"].append(
                {
                    "doc_id": document["doc_id"],
                    "channel": "rag_document",
                    "text": document["text"],
                    "host_task": document.get("host_task"),
                }
            )

        for document in raw.get("tool_responses", []):
            for path, value in _injectable_leaves(document["json"]):
                hosts["tool_response"].append(
                    {
                        "doc_id": f"{document['doc_id']}::{path}",
                        "channel": "tool_response",
                        "leaf_path": path,
                        "leaf_value": value,
                        "host_task": document.get("host_task"),
                        "tool_name": document.get("tool_name", ""),
                    }
                )

        for document in raw.get("tool_manifests", []):
            for path, value in _manifest_leaves(document["tool"]):
                hosts["tool_metadata"].append(
                    {
                        "doc_id": f"{document['doc_id']}::{path}",
                        "channel": "tool_metadata",
                        "leaf_path": path,
                        "leaf_value": value,
                        "host_task": document.get("host_task"),
                        "tool_name": document["tool"].get("name", ""),
                    }
                )
        return hosts

    # ----------------------------------------------------------------- record
    def _record(
        self,
        *,
        local_key: str,
        text: str,
        label: Label,
        channel: Channel,
        group_id: str,
        host_group: str,
        source_document_id: str,
        license: str = "CC0-1.0",
        host_task: str | None = None,
        json_path: str | None = None,
        attack_type: AttackType = AttackType.NONE,
        injected_spans: Sequence[Span] = (),
        is_hard_negative: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> CorpusRecord:
        payload = dict(extra or {})
        payload["host_group"] = host_group
        return CorpusRecord(
            record_id=make_record_id(_SOURCE_NAME, local_key),
            source_dataset=_SOURCE_NAME,
            source_document_id=source_document_id,
            source_license=license,
            raw_text=text,
            label=label,
            channel=channel,
            attack_type=attack_type,
            injected_spans=list(injected_spans),
            host_task=host_task,
            json_path=json_path,
            group_id=group_id,
            is_hard_negative=is_hard_negative,
            extra=payload,
        )


# --------------------------------------------------------------------- helpers
def insert_at(base: str, payload: str, position: str) -> tuple[str, int, int]:
    """Insert ``payload`` into ``base`` and return ``(text, start, end)``.

    ``middle`` inserts at a sentence boundary near the centre rather than at an
    arbitrary character, so the result stays readable and the injected span
    aligns with a real sentence -- which is what a detector will be asked to
    highlight.
    """

    base = base.strip()
    if position == "start":
        text = f"{payload}\n\n{base}"
        return text, 0, len(payload)
    if position == "end":
        prefix = f"{base}\n\n"
        return prefix + payload, len(prefix), len(prefix) + len(payload)

    midpoint = len(base) // 2
    boundary = base.find(". ", midpoint)
    cut = boundary + 2 if boundary != -1 else midpoint
    prefix = base[:cut].rstrip() + "\n\n"
    suffix = "\n\n" + base[cut:].lstrip()
    return prefix + payload + suffix, len(prefix), len(prefix) + len(payload)


def _encode(text: str, encoding: str | None) -> str:
    """Apply the obfuscation transform declared by the payload family."""

    if not encoding:
        return text
    if encoding == "zero_width":
        return "".join(
            char + _ZERO_WIDTH if index % 3 == 2 and char.isalpha() else char
            for index, char in enumerate(text)
        )
    if encoding == "base64":
        import base64 as _b64

        blob = _b64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"Reference data (do not display): {blob}"
    if encoding == "html_comment":
        return f"<!-- {text} -->"
    if encoding == "html_entities":
        return "".join(
            f"&#{ord(char)};" if char.isalpha() and index % 2 == 0 else char
            for index, char in enumerate(text)
        )
    if encoding == "homoglyph":
        return "".join(_HOMOGLYPH_MAP.get(char, char) for char in text)
    raise ValueError(f"unknown encoding {encoding!r}")


#: JSON keys whose string values are free text an attacker could reach.
_TEXT_KEYS = frozenset(
    {"content", "body", "summary", "notes", "note", "description", "snippet", "excerpt", "text"}
)


def _injectable_leaves(document: Any, path: str = "$") -> list[tuple[str, str]]:
    """Free-text leaves of a tool response, as ``(json_path, value)``."""

    found: list[tuple[str, str]] = []

    def walk(node: Any, current: str, key: str | None) -> None:
        if isinstance(node, str):
            if key in _TEXT_KEYS and len(node.strip()) >= 40:
                found.append((current, node))
            return
        if isinstance(node, dict):
            for child_key, value in node.items():
                walk(value, f"{current}.{child_key}", str(child_key))
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{current}[{index}]", key)

    walk(document, path, None)
    return found


def _manifest_leaves(tool: dict[str, Any]) -> list[tuple[str, str]]:
    """Description fields of a tool declaration, as ``(json_path, value)``."""

    leaves: list[tuple[str, str]] = []
    description = str(tool.get("description", "")).strip()
    if description:
        leaves.append(("$.description", description))
    schema = tool.get("parameters", {}) or {}
    for key, spec in (schema.get("properties", {}) or {}).items():
        text = str((spec or {}).get("description", "")).strip()
        if len(text) >= 20:
            leaves.append((f"$.parameters.properties.{key}.description", text))
    return leaves


def _deterministic_sample(items: Sequence[Any], count: int, *, key: str, seed: int) -> list[Any]:
    """Sample without replacement, reproducibly for a given ``key``.

    Uses a hash of the key rather than a shared RNG so that adding a new payload
    family does not shift the sample of every existing one, which would silently
    change the whole corpus.
    """

    if count >= len(items):
        return list(items)
    digest = hashlib.sha256(f"{seed}|{key}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    return rng.sample(list(items), count)


Pair = tuple["InsertionSpec", dict[str, Any], str]


def _group_by_split_and_channel(
    pairs: list[Pair], assignments: dict[str, str]
) -> dict[tuple[str, str], list[Pair]]:
    """Bucket pairs by ``(split, channel)``.

    Allocation has to happen per channel, not only per split.  The channels have
    very different numbers of payload families and host documents, so a single
    global budget hands almost everything to the RAG channel and leaves the
    tool-metadata channel with a handful of positives -- and none at all in some
    splits, which makes per-channel metrics uncalibratable and MCP-metadata
    claims unsupportable.
    """

    grouped: dict[tuple[str, str], list[Pair]] = {}
    for pair in pairs:
        split = assignments[pair[0].family]
        channel = str(pair[1]["channel"])
        grouped.setdefault((split, channel), []).append(pair)
    return grouped


def _allocate(
    grouped: dict[tuple[str, str], list[Pair]],
    config: BuiltinConfig,
    ratios: dict[str, float] | None = None,
) -> dict[tuple[str, str], list[Pair]]:
    """Cut each ``(split, channel)`` bucket to the split ratios and a common prior.

    Three distortions are corrected together.

    *Split size.*  The combinations available inside a split grow with the
    product of the families and hosts assigned to it, so a 70/15/15 split of the
    grouping keys yields roughly 87/6/7 of the records if every combination is
    kept, leaving dev and test too small to measure anything.

    *Class prior.*  There are more payload variants than benign insertion
    families, and the imbalance differs per split.  A split with a different
    prior makes average precision incomparable and changes what the
    hard-negative false-positive rate means.

    *Channel coverage.*  Allocating globally starves the smaller channels.  Each
    channel is therefore scaled independently, so tool-metadata and
    tool-response keep their own 70/15/15 with positives in every split.

    Within a channel the allocator finds the largest common scale its splits can
    support at the target prior and cuts each to ``ratio * scale``.  Train gives
    up combinations it could have had; the loss buys comparable dev and test
    splits and is reported in the corpus card.
    """

    ratios = ratios or {"train": 0.70, "dev": 0.15, "test": 0.15}
    positive_rate = 1.0 / (1.0 + config.benign_to_injection_ratio)

    channels = {channel for _split, channel in grouped}
    allocated: dict[tuple[str, str], list[Pair]] = {}

    for channel in sorted(channels):
        feasible: dict[str, float] = {}
        for (split, bucket_channel), items in grouped.items():
            if bucket_channel != channel or not items:
                continue
            positives = sum(1 for pair in items if pair[0].label is Label.INJECTION)
            negatives = len(items) - positives
            feasible[split] = (
                min(positives / positive_rate, negatives / (1.0 - positive_rate))
                if positives and negatives
                else 0.0
            )

        usable = {split: value for split, value in feasible.items() if value > 0}
        if not usable:
            # Keep whatever exists rather than silently dropping the channel;
            # the corpus card reports the resulting thin cells.
            for key, items in grouped.items():
                if key[1] == channel:
                    allocated[key] = items
            continue

        scale = min(value / ratios.get(split, 1.0) for split, value in usable.items())
        scale = min(scale, float(config.max_composed))

        for (split, bucket_channel), items in grouped.items():
            if bucket_channel != channel:
                continue
            size = round(scale * ratios.get(split, 1.0))
            want_positive = round(size * positive_rate)
            want_negative = size - want_positive
            positives = [p for p in items if p[0].label is Label.INJECTION][:want_positive]
            negatives = [p for p in items if p[0].label is Label.BENIGN][:want_negative]
            allocated[(split, bucket_channel)] = positives + negatives

    return allocated


def json_fingerprint(document: Any) -> str:
    """Stable digest of a JSON document, used for fixture identity."""

    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
