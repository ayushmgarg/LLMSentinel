"""Command-line entry point.

    llmsentinel corpus build            build the corpus, card and split manifest
    llmsentinel corpus check            re-audit the built corpus for leakage
    llmsentinel corpus inspect          print random records for manual review
    llmsentinel evaluate                run every available system
    llmsentinel export                  write fusion inputs (features, probabilities)
    llmsentinel scan                    score one document, JSON blob or file
    llmsentinel history ...             analyst history, review queue, overrides, stats
    llmsentinel manifests ...           MCP manifest approval and change alerts

Every command that produces a number prints the corpus digest it used, so a
result pasted into the report can be traced back to the data that produced it.
The ``--test`` flag is deliberately explicit: without it, no command touches the
test split.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from .constants import DEFAULT_SEED
from .data.build import build_corpus
from .data.leakage import check_leakage
from .data.splits import SplitConfig
from .paths import CORPUS_PATH, RESULTS_DIR, relative
from .schema import read_jsonl

__all__ = ["main"]


def _console_safe(text: str) -> str:
    """Escape characters a legacy console encoding cannot represent.

    Corpus records contain zero-width and homoglyph characters by design, and a
    Windows console encoded as cp1252 raises on them -- which silently truncated
    `corpus inspect` after the first such record.
    """

    return text.encode("ascii", "backslashreplace").decode("ascii")


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"  ! {warning}")


# ------------------------------------------------------------------- corpus
def cmd_corpus_build(args: argparse.Namespace) -> int:
    result = build_corpus(
        split_config=SplitConfig(seed=args.seed, stratify_by_source=not args.no_stratify_source)
    )
    print(result.summary())
    print(f"leakage: {result.leakage.summary()}")
    print(f"corpus:  {relative(result.corpus_path)}")
    print(f"card:    {relative(result.card_path)}")
    return 0 if result.leakage.ok else 1


def cmd_corpus_check(args: argparse.Namespace) -> int:
    records = read_jsonl(args.corpus)
    report = check_leakage(records)
    print(report.summary())
    for name in ("group_violations", "host_violations", "duplicate_texts", "near_duplicate_pairs"):
        findings = getattr(report, name)
        for finding in findings[:10]:
            print(f"  {name}: {finding}")
    return 0 if report.ok else 1


def cmd_corpus_inspect(args: argparse.Namespace) -> int:
    """Print records for the manual review the protocol requires."""

    records = read_jsonl(args.corpus)
    pool = [record for record in records if record.split.value == args.split] if args.split else records
    if args.hard_negatives:
        pool = [record for record in pool if record.is_hard_negative]
    if args.positives:
        pool = [record for record in pool if record.y == 1]
    if not pool:
        print("no records match the filter")
        return 1

    sample = random.Random(args.seed).sample(pool, min(args.n, len(pool)))
    for index, record in enumerate(sample, start=1):
        print(f"--- [{index}/{len(sample)}] {record.record_id}")
        print(
            f"    label={record.label.name} attack={record.attack_type.value} "
            f"channel={record.channel.value} split={record.split.value} "
            f"hard_negative={record.is_hard_negative}"
        )
        print(f"    group={record.group_id} host={record.extra.get('host_group')}")
        if record.json_path:
            print(f"    json_path={record.json_path}")
        if record.host_task:
            print(f"    host_task={record.host_task}")
        text = _console_safe(" ".join(record.raw_text.split()))
        print(f"    text: {text[: args.chars]}")
        for span in record.injected_spans:
            excerpt = _console_safe(span.slice(record.raw_text))[:120]
            print(f"    injected span [{span.start}:{span.end}]: {excerpt}")
    return 0


# ----------------------------------------------------------------- evaluate
def cmd_evaluate(args: argparse.Namespace) -> int:
    from .evaluation import (
        load_splits,
        per_dataset_table,
        results_table,
        run_system,
        save_results,
    )
    from .models import (
        KeywordBaseline,
        MajorityBaseline,
        RulesScorer,
        TfidfBaseline,
        TfidfCharBaseline,
    )
    from .models.fusion import FusionScorer
    from .models.transformer import TransformerScorer, torch_available

    splits = load_splits(args.corpus)
    digest = _digest(args.corpus)
    print(f"corpus {relative(Path(args.corpus))} digest={digest} "
          f"train={len(splits['train'])} dev={len(splits['dev'])} test={len(splits['test'])}")

    # Enforce "score test once": the held-out test split may be scored only once
    # per corpus digest. A repeat needs --force-test and is recorded, so an
    # accidental second peek cannot pass unnoticed.
    if args.test and not _test_run_allowed(digest, force=args.force_test):
        print(
            f"refusing: the test split was already scored for corpus digest {digest} "
            f"(see {relative(RESULTS_DIR / 'test_runs.json')}). "
            f"Re-run with --force-test only if you understand this breaks the "
            f"score-test-once protocol; rebuild the corpus for a fresh digest otherwise."
        )
        return 1

    rules = RulesScorer()
    systems: list[Any] = [
        MajorityBaseline(),
        KeywordBaseline(),
        TfidfBaseline(),
        TfidfCharBaseline(),
        rules,
    ]

    transformer = None
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    if checkpoint and checkpoint.is_dir() and torch_available():
        transformer = TransformerScorer.load(checkpoint)
        systems.append(transformer)
    elif args.require_transformer:
        print("transformer checkpoint not found; run scripts/train_transformer.py first")
        return 1

    results = []
    for system in systems:
        # Baselines and the transformer are fitted (or already trained) on
        # train; thresholds always come from dev.
        fit = system is not transformer
        results.append(
            run_system(
                system,
                splits,
                fit=fit,
                include_test=args.test,
                bootstrap=args.bootstrap,
                data_version=digest,
            )
        )

    fusion = FusionScorer(rules=rules, transformer=transformer)
    fusion.fit(splits["dev"])
    results.append(
        run_system(
            fusion,
            splits,
            fit=False,
            include_test=args.test,
            bootstrap=args.bootstrap,
            data_version=digest,
        )
    )

    print()
    print(results_table(results, split="dev"))
    print()
    print(per_dataset_table(results, split="dev"))
    if args.test:
        print()
        print(results_table(results, split="test"))
        print()
        print(per_dataset_table(results, split="test"))

    warnings = sorted({warning for result in results for warning in result.warnings})
    if warnings:
        print("\nwarnings:")
        _print_warnings(warnings)

    # results_dev.json is always written: it carries the dev-selected thresholds
    # that `llmsentinel scan` needs to turn a score into a risk band.
    written = [save_results(results, RESULTS_DIR / "results_dev.json")]
    if args.test:
        written.append(save_results(results, RESULTS_DIR / "results_test.json"))
        _record_test_run(digest, forced=args.force_test)
    print("\nsaved " + ", ".join(relative(path) for path in written))
    return 0


def _test_run_allowed(digest: str, *, force: bool) -> bool:
    """True when the test split may be scored for this corpus digest."""

    if force:
        return True
    log = RESULTS_DIR / "test_runs.json"
    if not log.is_file():
        return True
    entries = json.loads(log.read_text(encoding="utf-8"))
    return not any(entry.get("digest") == digest for entry in entries)


def _record_test_run(digest: str, *, forced: bool) -> None:
    import datetime

    log = RESULTS_DIR / "test_runs.json"
    entries = json.loads(log.read_text(encoding="utf-8")) if log.is_file() else []
    entries.append(
        {
            "digest": digest,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "forced": forced,
        }
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ------------------------------------------------------------------- export
def cmd_export(args: argparse.Namespace) -> int:
    """Write the fusion layer's inputs to disk so they can be inspected.

    The fusion model consumes rule features and a transformer probability. Until
    those are on disk they cannot be plotted, correlated, or checked by anyone
    who is not running the trainer, and a claim about which signal carried a
    decision cannot be verified.
    """

    import csv

    from .evaluation import load_splits
    from .models import RulesScorer
    from .models.transformer import TransformerScorer, torch_available

    splits = load_splits(args.corpus)
    records = splits[args.split]
    if not records:
        print(f"split {args.split!r} is empty")
        return 1

    rules = RulesScorer()
    feature_names = list(rules.feature_names)
    features = rules.features(records)
    rule_scores = rules.score(records)

    probabilities = None
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    if checkpoint and checkpoint.is_dir() and torch_available():
        probabilities = TransformerScorer.load(checkpoint).score(records)
    else:
        print(f"note: no transformer checkpoint at {args.checkpoint}; probabilities omitted")

    target = Path(args.out) if args.out else RESULTS_DIR / f"features_{args.split}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        ["record_id", "label", "channel", "attack_type", "is_hard_negative", "rule_score"]
        + (["transformer_probability"] if probabilities is not None else [])
        + feature_names
    )
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index, record in enumerate(records):
            row = [
                record.record_id,
                record.y,
                record.channel.value,
                record.attack_type.value,
                int(record.is_hard_negative),
                round(float(rule_scores[index]), 6),
            ]
            if probabilities is not None:
                row.append(round(float(probabilities[index]), 6))
            row.extend(round(float(value), 6) for value in features[index])
            writer.writerow(row)

    print(
        f"exported {len(records)} {args.split} records x {len(header)} columns "
        f"({len(feature_names)} rule features"
        + (", transformer probability" if probabilities is not None else "")
        + f") -> {relative(target)}"
    )
    return 0


# --------------------------------------------------------------------- scan
def cmd_scan(args: argparse.Namespace) -> int:
    from .normalize import Normalizer
    from .rules import RuleEngine
    from .schema import Channel
    from .verdict import build_verdict

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    engine = RuleEngine()
    normalizer: Normalizer = engine.normalizer
    thresholds = _load_thresholds(args.thresholds, args.system)
    if thresholds:
        print(f"note: risk bands use {args.system} thresholds selected on dev")
    metadata = {"host_task": args.host_task} if args.host_task else None

    if args.json:
        units, error = normalizer.normalize_json_text(text, channel=Channel.coerce(args.channel))
        if error:
            print(f"warning: input did not parse as JSON ({error}); scanned as plain text")
    else:
        units = [normalizer.normalize_text(text, channel=Channel.coerce(args.channel), metadata=metadata)]

    verdicts = []
    for unit in units:
        if metadata:
            unit.metadata.update(metadata)
        verdicts.append(build_verdict(unit, engine.analyse(unit), thresholds=thresholds))
        for child in normalizer.derived_units(unit):
            verdicts.append(build_verdict(child, engine.analyse(child), thresholds=thresholds))

    verdicts.sort(key=lambda verdict: verdict.risk, reverse=True)
    if args.record:
        _record_scan(args, text)
    if args.output_json:
        print(json.dumps([verdict.to_dict() for verdict in verdicts], indent=2))
        return 0

    decision = None
    if args.action:
        from .policy import CapabilityPolicy, ProposedAction

        worst = verdicts[0] if verdicts else None
        decision = CapabilityPolicy().decide(
            ProposedAction(tool_name=args.action, description="proposed by the agent"),
            verdict=worst,
        )

    for verdict in verdicts[: args.top]:
        print(verdict.summary())
        for reason in verdict.rule_trace[:4]:
            print(f"    {_console_safe(reason)}")
        for span in verdict.flagged_spans[:3]:
            excerpt = _console_safe(" ".join(span.slice(text).split()))[:140]
            print(f"    span [{span.start}:{span.end}] {excerpt}")

    if decision is not None:
        print()
        print(f"policy: {decision.summary()}")
        for reason in decision.reasons:
            print(f"    {reason}")
        print("    (advisory detector, deterministic policy; nothing is executed)")
    return 0


def _record_scan(args: argparse.Namespace, text: str) -> None:
    """Record the same rules-only scan in the analyst history, plus the gated action if any."""

    from .analyst import ScanStore
    from .sdk import Sentinel

    store = ScanStore(args.history) if args.history else ScanStore()
    sentinel = Sentinel(detector="rules", results_path=args.thresholds, store=store)
    if args.json:
        result = sentinel.scan_json(text, tool=args.tool, source=args.source, host_task=args.host_task)
    else:
        result = sentinel.scan_text(text, channel=args.channel, source=args.source, host_task=args.host_task)
    if args.action:
        sentinel.gate(args.action, context=result)
    ids = ", ".join(unit.scan_id[:12] for unit in result.units if unit.scan_id)
    print(f"recorded in {relative(store.path)}: {ids}")


def _load_thresholds(path: str | None, system: str) -> dict[str, float]:
    """Operating points chosen on dev, so a risk band means something.

    Without them every verdict would be reported in the lowest band, which is
    exactly the kind of quietly wrong display this project is meant to avoid.
    """

    source = Path(path) if path else RESULTS_DIR / "results_dev.json"
    if not source.is_file():
        print(f"note: no dev thresholds at {relative(source)}; bands are not meaningful "
              f"(run `llmsentinel evaluate` first)")
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))
    for entry in payload:
        if entry.get("name") == system:
            return {k: float(v) for k, v in entry["dev"]["thresholds"].items()}
    print(f"note: no thresholds for system {system!r} in {relative(source)}")
    return {}


def _digest(corpus: str | Path) -> str:
    from .data.splits import corpus_digest

    return corpus_digest(read_jsonl(corpus))


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llmsentinel", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("corpus", help="build and audit the corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)

    build = corpus_sub.add_parser("build", help="build corpus, card and split manifest")
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    build.add_argument(
        "--no-stratify-source",
        action="store_true",
        help="disable per-source stratified splitting (revert to global per-key hash; "
        "stratification is on by default and fixes the per-source split confound)",
    )
    build.set_defaults(func=cmd_corpus_build)

    check = corpus_sub.add_parser("check", help="re-audit a built corpus for leakage")
    check.add_argument("--corpus", default=str(CORPUS_PATH))
    check.set_defaults(func=cmd_corpus_check)

    inspect = corpus_sub.add_parser("inspect", help="print records for manual review")
    inspect.add_argument("--corpus", default=str(CORPUS_PATH))
    inspect.add_argument("-n", type=int, default=20)
    inspect.add_argument("--split", default=None, choices=["train", "dev", "test"])
    inspect.add_argument("--hard-negatives", action="store_true")
    inspect.add_argument("--positives", action="store_true")
    inspect.add_argument("--chars", type=int, default=300)
    inspect.add_argument("--seed", type=int, default=DEFAULT_SEED)
    inspect.set_defaults(func=cmd_corpus_inspect)

    evaluate = sub.add_parser("evaluate", help="run every available system")
    evaluate.add_argument("--corpus", default=str(CORPUS_PATH))
    evaluate.add_argument("--checkpoint", default="artifacts/models/transformer")
    evaluate.add_argument("--require-transformer", action="store_true")
    evaluate.add_argument("--bootstrap", type=int, default=0)
    evaluate.add_argument(
        "--test",
        action="store_true",
        help="also score the held-out test split, once, with dev thresholds",
    )
    evaluate.add_argument(
        "--force-test",
        action="store_true",
        help="score the test split even if it was already scored for this corpus "
        "digest; breaks the score-test-once protocol and is recorded as forced",
    )
    evaluate.set_defaults(func=cmd_evaluate)

    export = sub.add_parser(
        "export", help="write rule features and transformer probabilities to CSV"
    )
    export.add_argument("--corpus", default=str(CORPUS_PATH))
    export.add_argument("--split", default="dev", choices=["train", "dev", "test"])
    export.add_argument("--checkpoint", default="artifacts/models/transformer")
    export.add_argument("--out", default=None)
    export.set_defaults(func=cmd_export)

    scan = sub.add_parser("scan", help="score one document or tool response")
    scan.add_argument("--text", default=None)
    scan.add_argument("--file", default=None)
    scan.add_argument("--json", action="store_true", help="treat the input as a JSON tool response")
    scan.add_argument("--channel", default="rag_document")
    scan.add_argument("--host-task", default=None)
    scan.add_argument("--top", type=int, default=5)
    scan.add_argument(
        "--action",
        default=None,
        help="tool name the agent proposes to call; prints the capability-policy outcome",
    )
    scan.add_argument("--output-json", action="store_true")
    scan.add_argument(
        "--thresholds",
        default=None,
        help="results JSON holding dev-selected operating points (default: artifacts/results/results_dev.json)",
    )
    scan.add_argument(
        "--system",
        default="rules-only",
        choices=["rules-only"],
        help=(
            "which system's dev thresholds set the risk band. Restricted to "
            "rules-only because scan scores with the rule engine alone; using "
            "another system's thresholds would band a rules score against a "
            "scale it was not measured on"
        ),
    )
    scan.add_argument("--record", action="store_true", help="also record the scan in the analyst history")
    scan.add_argument("--source", default=None, help="where the text came from (file, URL, tool), for the history")
    scan.add_argument("--tool", default=None, help="tool that returned the text, for the history")
    scan.add_argument("--history", default=None, help="history database (default: artifacts/analyst/history.sqlite3)")
    scan.set_defaults(func=cmd_scan)

    from .analyst.cli import register_analyst_commands

    register_analyst_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
