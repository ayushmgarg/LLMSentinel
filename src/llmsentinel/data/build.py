"""Corpus build: load every available source, deduplicate, split, normalise, write.

One command owns the whole pipeline so that the corpus digest recorded in the
experiment log identifies the data exactly:

    llmsentinel corpus build

External benchmarks are optional.  When BIPIA, InjecAgent or an MCPTox release
is not present, the build proceeds with the sources that are and records the
omission in the corpus card, instead of failing and leaving the project without
a dataset.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..normalize.pipeline import Normalizer
from ..paths import CORPUS_CARD_PATH, CORPUS_PATH, SPLIT_MANIFEST_PATH, ensure_dirs
from ..schema import CorpusRecord, write_jsonl
from .corpus_card import write_corpus_card
from .leakage import LeakageReport, check_leakage, normalised_text_key
from .loaders.base import Loader, SourceSpec
from .loaders.bipia import BipiaLoader
from .loaders.builtin import BuiltinSeedLoader
from .loaders.injecagent import InjecAgentLoader
from .loaders.mcptox import McpToxLoader
from .splits import SplitConfig, SplitManifest, apply_splits

__all__ = ["BuildResult", "build_corpus", "default_loaders"]


def default_loaders() -> list[Loader]:
    """The full source list, in the order their records are emitted."""

    return [BuiltinSeedLoader(), BipiaLoader(), InjecAgentLoader(), McpToxLoader()]


#: A (split, channel) cell with fewer positives than this cannot support a
#: per-channel claim, and cannot be used to calibrate a per-channel threshold.
MIN_POSITIVES_PER_CELL: int = 5


@dataclass(slots=True)
class BuildResult:
    records: list[CorpusRecord]
    manifest: SplitManifest
    leakage: LeakageReport
    sources_used: list[SourceSpec] = field(default_factory=list)
    sources_skipped: list[str] = field(default_factory=list)
    duplicates_removed: int = 0
    corpus_path: Path | None = None
    card_path: Path | None = None
    #: Conditions that limit what this corpus can support. Every one of these is
    #: reproduced in the corpus card, because they constrain the claims a report
    #: is allowed to make.
    warnings: list[str] = field(default_factory=list)

    @property
    def synthetic_only(self) -> bool:
        """True when no third-party benchmark contributed a single record."""

        return all(spec.name == "llmsentinel-builtin" for spec in self.sources_used)

    def summary(self) -> str:
        positives = sum(record.y for record in self.records)
        line = (
            f"{len(self.records)} records ({positives} injection, "
            f"{len(self.records) - positives} benign) from "
            f"{len(self.sources_used)} source(s); "
            f"{self.duplicates_removed} exact duplicates removed; "
            f"{self.manifest.dropped_cross_group} cross-group records dropped; "
            f"digest {self.manifest.corpus_digest}"
        )
        if self.warnings:
            line += f"\n{len(self.warnings)} warning(s):\n  - " + "\n  - ".join(self.warnings)
        return line


def build_corpus(
    loaders: Sequence[Loader] | None = None,
    *,
    split_config: SplitConfig | None = None,
    normalise: bool = True,
    write: bool = True,
    corpus_path: Path | None = None,
) -> BuildResult:
    """Build the corpus end to end."""

    ensure_dirs()
    loaders = list(loaders) if loaders is not None else default_loaders()
    split_config = split_config or SplitConfig()

    collected: list[CorpusRecord] = []
    used: list[SourceSpec] = []
    skipped: list[str] = []

    for loader in loaders:
        if not loader.available():
            skipped.append(loader.unavailable_reason())
            continue
        before = len(collected)
        collected.extend(loader.load())
        if len(collected) == before:
            skipped.append(f"{loader.spec.name}: present but produced no usable record")
            continue
        used.append(loader.spec)

    if not collected:
        raise RuntimeError(
            "no source produced records. The built-in seed corpus should always be "
            "available -- check that data/seed/*.yaml exist."
        )

    deduped, duplicates_removed = _deduplicate(collected)
    split_records, manifest = apply_splits(deduped, split_config)

    if normalise:
        normalizer = Normalizer()
        for record in split_records:
            normalizer.normalize_record(record)

    leakage = check_leakage(split_records)

    result = BuildResult(
        records=split_records,
        manifest=manifest,
        leakage=leakage,
        sources_used=used,
        sources_skipped=skipped,
        duplicates_removed=duplicates_removed,
    )
    result.warnings = corpus_warnings(result)

    if write:
        target = Path(corpus_path) if corpus_path else CORPUS_PATH
        write_jsonl(split_records, target)
        manifest.save(SPLIT_MANIFEST_PATH)
        write_corpus_card(
            CORPUS_CARD_PATH,
            split_records,
            manifest,
            used,
            skipped=skipped,
            warnings=result.warnings,
        )
        result.corpus_path = target
        result.card_path = CORPUS_CARD_PATH

    return result


def corpus_warnings(result: BuildResult) -> list[str]:
    """Conditions that constrain what may be claimed from this corpus.

    These are produced from the built corpus itself rather than asserted by
    hand, so they cannot go stale: if a benchmark is added later the synthetic
    warning disappears on the next build, and if a channel becomes thin the
    warning appears without anyone remembering to add it.
    """

    warnings: list[str] = []

    if result.synthetic_only:
        warnings.append(
            "SYNTHETIC ONLY: every record comes from the authored built-in seed "
            "corpus; no third-party benchmark contributed data. Results are "
            "bounded by the templates in data/seed/payloads.yaml and must not be "
            "reported as benchmark performance, nor as evidence of "
            "generalisation to real attacks."
        )

    cells: dict[tuple[str, str], list[int]] = {}
    for record in result.records:
        if record.split is None:
            continue
        cells.setdefault((record.split.value, record.channel.value), []).append(record.y)

    for (split, channel), labels in sorted(cells.items()):
        positives = sum(labels)
        if positives == 0:
            warnings.append(
                f"NO POSITIVES: {split}/{channel} has {len(labels)} records and no "
                f"injection examples. Per-channel metrics, threshold calibration "
                f"and any {channel} claim are unsupported on this split."
            )
        elif positives < MIN_POSITIVES_PER_CELL:
            warnings.append(
                f"THIN CELL: {split}/{channel} has only {positives} injection "
                f"example(s). Treat its per-channel numbers as indicative, not as "
                f"a measurement."
            )

    missing_channels = {"rag_document", "tool_response", "tool_metadata"} - {
        channel for _split, channel in cells
    }
    for channel in sorted(missing_channels):
        warnings.append(f"CHANNEL ABSENT: no records at all for {channel}.")

    return warnings


def _deduplicate(records: Sequence[CorpusRecord]) -> tuple[list[CorpusRecord], int]:
    """Drop exact text duplicates before splitting.

    Order is the loader emission order, so the surviving copy is deterministic.
    A duplicate that carries a *different* label is kept and flagged in ``extra``
    rather than silently resolved: disagreeing labels are an annotation problem,
    not a deduplication problem.
    """

    seen: dict[str, CorpusRecord] = {}
    kept: list[CorpusRecord] = []
    removed = 0
    for record in records:
        key = normalised_text_key(record.raw_text)
        previous = seen.get(key)
        if previous is None:
            seen[key] = record
            kept.append(record)
            continue
        if previous.label is record.label:
            removed += 1
            continue
        previous.extra["label_conflict_with"] = record.record_id
        record.extra["label_conflict_with"] = previous.record_id
        kept.append(record)
    return kept, removed
