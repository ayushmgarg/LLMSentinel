"""BIPIA loader (retrieval / document channel).

Expected layout (after cloning the official repository into ``data/raw/bipia``)::

    data/raw/bipia/
        benchmark/
            email/            test.jsonl, train.jsonl ...
            qa/               ...
            abstract/         ...
            table/            ...
            text_attack_test.json      # [[attack_name, attack_string], ...]
            text_attack_train.json

Each context file is a JSONL of host tasks with a ``context`` field (the
retrieved document) and a ``question``/``ideal`` pair.  The attack files hold the
payload strings and their names.  BIPIA composes the two at evaluation time, and
this loader reproduces that composition so that both classes come from the same
host documents.

Field names are read defensively through :func:`first_present`: the repository
has renamed fields between releases, and a rename must produce a clear message
rather than a silently empty corpus.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...constants import DEFAULT_SEED
from ...paths import RAW_DIR
from ...schema import AttackType, Channel, CorpusRecord, Label, Span, make_record_id
from ._io import first_present, iter_records, read_any, walk_data_files
from .base import Loader, SourceSpec

__all__ = ["BipiaLoader"]

_SOURCE = "bipia"

#: Maps BIPIA attack-name prefixes onto our attack taxonomy.  Anything else
#: becomes ``AttackType.UNKNOWN`` rather than being guessed.
_ATTACK_NAME_MAP: dict[str, AttackType] = {
    "task automation": AttackType.ACTION_HIJACK,
    "business intelligence": AttackType.EXFILTRATION,
    "conversational agent": AttackType.META_INSTRUCTION,
    "information dissemination": AttackType.CONTENT_MANIPULATION,
    "marketing": AttackType.CONTENT_MANIPULATION,
    "advertisement": AttackType.CONTENT_MANIPULATION,
    "scams": AttackType.EXFILTRATION,
    "phishing": AttackType.EXFILTRATION,
    "information gathering": AttackType.EXFILTRATION,
    "bias": AttackType.CONTENT_MANIPULATION,
    "toxic": AttackType.CONTENT_MANIPULATION,
    "substance": AttackType.CONTENT_MANIPULATION,
}


class BipiaLoader(Loader):
    spec = SourceSpec(
        name="BIPIA",
        homepage="https://github.com/microsoft/BIPIA",
        license="See the repository LICENSE; verify before redistributing any excerpt.",
        citation=(
            "Yi et al., Benchmarking and Defending Against Indirect Prompt Injection "
            "Attacks on Large Language Models."
        ),
        acquisition=(
            "git clone https://github.com/microsoft/BIPIA into data/raw/bipia "
            "(the loader reads data/raw/bipia/benchmark/)."
        ),
        notes="Text (document) channel only. Code-attack subsets are out of scope.",
    )

    def __init__(
        self,
        root: Path | None = None,
        *,
        seed: int = DEFAULT_SEED,
        max_hosts_per_attack: int = 4,
        max_records: int = 4000,
    ) -> None:
        super().__init__(root or (RAW_DIR / "bipia"))
        self.seed = seed
        self.max_hosts_per_attack = max_hosts_per_attack
        self.max_records = max_records

    # ------------------------------------------------------------ availability
    def available(self) -> bool:
        root = self.root
        return root is not None and root.is_dir() and bool(self._context_files() and self._attacks())

    def _benchmark_dir(self) -> Path:
        assert self.root is not None
        nested = self.root / "benchmark"
        return nested if nested.is_dir() else self.root

    def _context_files(self) -> list[Path]:
        return [
            path
            for path in walk_data_files(self._benchmark_dir())
            if "attack" not in path.name.lower()
        ]

    def _attacks(self) -> list[tuple[str, str]]:
        """Return ``(attack_name, attack_string)`` pairs from the attack files."""

        attacks: list[tuple[str, str]] = []
        for path in walk_data_files(self._benchmark_dir()):
            if "attack" not in path.name.lower():
                continue
            payload = read_any(path)
            if isinstance(payload, list):
                for entry in payload:
                    if isinstance(entry, list | tuple) and len(entry) >= 2:
                        attacks.append((str(entry[0]), str(entry[1])))
                    elif isinstance(entry, dict):
                        name = first_present(entry, "attack_name", "name", "type")
                        text = first_present(entry, "attack_str", "attack", "text", "instruction")
                        if name and text:
                            attacks.append((str(name), str(text)))
            elif isinstance(payload, dict):
                for name, text in payload.items():
                    if isinstance(text, str):
                        attacks.append((str(name), text))
        return attacks

    # -------------------------------------------------------------------- load
    def load(self) -> Iterator[CorpusRecord]:
        attacks = self._attacks()
        if not attacks:
            return
        emitted = 0
        hosts = list(self._hosts())
        rng = random.Random(self.seed)

        for host in hosts:
            if emitted >= self.max_records:
                return
            yield self._benign(host)
            emitted += 1

        for attack_name, attack_text in attacks:
            chosen = _sample(hosts, self.max_hosts_per_attack, f"{self.seed}|{attack_name}")
            for host in chosen:
                if emitted >= self.max_records:
                    return
                record = self._poisoned(host, attack_name, attack_text, rng)
                if record is not None:
                    yield record
                    emitted += 1

    # ---------------------------------------------------------------- internals
    def _hosts(self) -> Iterator[dict[str, Any]]:
        for path in self._context_files():
            try:
                payload = read_any(path)
            except (ValueError, UnicodeDecodeError):
                continue
            subset = path.parent.name
            for index, record in enumerate(iter_records(payload)):
                context = first_present(record, "context", "content", "document", "text", "passage")
                if not isinstance(context, str) or len(context.strip()) < 40:
                    continue
                question = first_present(record, "question", "instruction", "query", "task")
                yield {
                    "doc_id": f"{subset}/{path.stem}/{index}",
                    "subset": subset,
                    "context": context.strip(),
                    "question": str(question) if question else None,
                }

    def _benign(self, host: dict[str, Any]) -> CorpusRecord:
        return CorpusRecord(
            record_id=make_record_id(_SOURCE, f"clean/{host['doc_id']}"),
            source_dataset=_SOURCE,
            source_document_id=host["doc_id"],
            source_license=self.spec.license,
            raw_text=host["context"],
            label=Label.BENIGN,
            channel=Channel.RAG_DOCUMENT,
            host_task=host.get("question"),
            group_id=f"host:{_host_group(host)}",
            extra={
                "host_group": f"host:{_host_group(host)}",
                "subset": host["subset"],
                "variant": "clean_host",
            },
        )

    def _poisoned(
        self, host: dict[str, Any], attack_name: str, attack_text: str, rng: random.Random
    ) -> CorpusRecord | None:
        attack_text = attack_text.strip()
        if not attack_text:
            return None
        context = host["context"]
        # BIPIA appends the payload to the retrieved content; position variation
        # is evaluated separately in the Week 4 robustness suite.
        composed = f"{context}\n{attack_text}"
        start = len(context) + 1
        return CorpusRecord(
            record_id=make_record_id(_SOURCE, f"mix/{host['doc_id']}/{attack_name}"),
            source_dataset=_SOURCE,
            source_document_id=host["doc_id"],
            source_license=self.spec.license,
            raw_text=composed,
            label=Label.INJECTION,
            channel=Channel.RAG_DOCUMENT,
            attack_type=_map_attack(attack_name),
            injected_spans=[Span(start, start + len(attack_text), field="raw_text", note=attack_name)],
            host_task=host.get("question"),
            group_id=f"family:{_attack_family(attack_name)}",
            extra={
                "host_group": f"host:{_host_group(host)}",
                "subset": host["subset"],
                "attack_name": attack_name,
                "variant": "composed",
            },
        )


def _map_attack(name: str) -> AttackType:
    lowered = name.lower()
    for key, value in _ATTACK_NAME_MAP.items():
        if key in lowered:
            return value
    return AttackType.UNKNOWN


def _attack_family(name: str) -> str:
    """Collapse numbered variants ("Phishing-2") into one grouping family."""

    base = name.lower().split("-")[0].strip()
    return base.replace(" ", "_") or "unknown"


def _host_group(host: dict[str, Any]) -> str:
    return f"{host['subset']}/{hashlib.sha1(host['context'][:200].encode()).hexdigest()[:10]}"


def _sample(items: list[Any], count: int, key: str) -> list[Any]:
    if count >= len(items):
        return items
    digest = hashlib.sha256(key.encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big")).sample(items, count)
