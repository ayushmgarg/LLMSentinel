"""Source-stratified splitting: every benchmark source must put both labels in
dev and test, with no record dropped to a straddled boundary and no group
crossing a split (leakage-free)."""

from __future__ import annotations

from collections import Counter

from llmsentinel.data.splits import SplitConfig, apply_splits, host_group_of
from llmsentinel.schema import AttackType, Channel, CorpusRecord


def _rec(rid: str, source: str, family: str, host: str, label: int) -> CorpusRecord:
    return CorpusRecord(
        record_id=rid,
        source_dataset=source,
        source_document_id=host,
        source_license="CC0-1.0",
        raw_text=f"record {rid} with enough words to be a valid corpus entry",
        label=label,
        channel=Channel.RAG_DOCUMENT,
        attack_type=AttackType.META_INSTRUCTION if label else AttackType.NONE,
        group_id=family,
        extra={"host_group": host},
    )


def _corpus() -> list[CorpusRecord]:
    records: list[CorpusRecord] = []
    # A benchmark source with many independent (family, host) pairs so it can be
    # stratified into every split.
    for i in range(40):
        label = int(i % 2 == 0)
        fam = f"bench_fam:{i}" if label else f"bench_host:{i}"
        records.append(_rec(f"b{i}", "benchmark", fam, f"bench_host:{i}", label))
    # A builtin source (kept on the hash path).
    for i in range(40):
        label = int(i % 2 == 0)
        records.append(_rec(f"s{i}", "builtin", f"family:{i}", f"host:{i}", label))
    return records


def test_stratified_split_covers_both_labels_in_dev_and_test() -> None:
    corpus = _corpus()
    kept, _ = apply_splits(corpus, SplitConfig(stratify_by_source=True))
    by = Counter((r.source_dataset, r.split.value, r.y) for r in kept)
    for split in ("train", "dev", "test"):
        assert by[("benchmark", split, 1)] > 0, f"no benchmark positives in {split}"
        assert by[("benchmark", split, 0)] > 0, f"no benchmark benigns in {split}"
    # Component assignment drops no record from the stratified source (both keys
    # of a record share a component, hence a split). The builtin hash path may
    # still drop straddlers, so this is asserted per source.
    kept_bench = sum(1 for r in kept if r.source_dataset == "benchmark")
    all_bench = sum(1 for r in corpus if r.source_dataset == "benchmark")
    assert kept_bench == all_bench


def test_stratified_split_is_leakage_free() -> None:
    kept, _ = apply_splits(_corpus(), SplitConfig(stratify_by_source=True))
    split_of_group: dict[str, str] = {}
    for record in kept:
        for key in (record.group_id, host_group_of(record)):
            if key in split_of_group:
                assert split_of_group[key] == record.split.value, f"{key} crosses splits"
            split_of_group[key] = record.split.value


def test_non_stratified_split_still_works() -> None:
    kept, _ = apply_splits(_corpus(), SplitConfig(stratify_by_source=False))
    assert kept
    assert {r.split.value for r in kept} <= {"train", "dev", "test"}
