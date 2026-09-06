"""Command-line entry point.

    llmsentinel corpus build            build the corpus, card and split manifest
    llmsentinel corpus check            re-audit the built corpus for leakage
    llmsentinel corpus inspect          print random records for manual review
    llmsentinel evaluate                run every available system
    llmsentinel scan                    score one document, JSON blob or file

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


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"  ! {warning}")


# ------------------------------------------------------------------- corpus
def cmd_corpus_build(args: argparse.Namespace) -> int:
    result = build_corpus(split_config=SplitConfig(seed=args.seed))
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
        text = " ".join(record.raw_text.split())
        print(f"    text: {text[: args.chars]}")
        for span in record.injected_spans:
            print(f"    injected span [{span.start}:{span.end}]: {span.slice(record.raw_text)[:120]}")
    return 0


# ----------------------------------------------------------------- evaluate
def cmd_evaluate(args: argparse.Namespace) -> int:
    from .evaluation import load_splits, results_table, run_system, save_results
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
    if args.test:
        print()
        print(results_table(results, split="test"))

    warnings = sorted({warning for result in results for warning in result.warnings})
    if warnings:
        print("\nwarnings:")
        _print_warnings(warnings)

    path = save_results(results, RESULTS_DIR / ("results_test.json" if args.test else "results_dev.json"))
    print(f"\nsaved {relative(path)}")
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
    if args.output_json:
        print(json.dumps([verdict.to_dict() for verdict in verdicts], indent=2))
        return 0

    for verdict in verdicts[: args.top]:
        print(verdict.summary())
        for reason in verdict.rule_trace[:4]:
            print(f"    {reason}")
        for span in verdict.flagged_spans[:3]:
            excerpt = " ".join(span.slice(text if not args.json else span.slice(text)).split())[:140]
            print(f"    span [{span.start}:{span.end}] {excerpt}")
    return 0


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
    evaluate.set_defaults(func=cmd_evaluate)

    scan = sub.add_parser("scan", help="score one document or tool response")
    scan.add_argument("--text", default=None)
    scan.add_argument("--file", default=None)
    scan.add_argument("--json", action="store_true", help="treat the input as a JSON tool response")
    scan.add_argument("--channel", default="rag_document")
    scan.add_argument("--host-task", default=None)
    scan.add_argument("--top", type=int, default=5)
    scan.add_argument("--output-json", action="store_true")
    scan.add_argument(
        "--thresholds",
        default=None,
        help="results JSON holding dev-selected operating points (default: artifacts/results/results_dev.json)",
    )
    scan.add_argument(
        "--system",
        default="rules-only",
        help="which system's dev thresholds to use for the risk band",
    )
    scan.set_defaults(func=cmd_scan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
