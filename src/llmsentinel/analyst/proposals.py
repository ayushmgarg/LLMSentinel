"""Propose new rules from cases the rules missed, without ever self-activating.

The rule engine is fixed by evaluation: its patterns, weights and feature layout
were chosen on train/dev and the test split was scored once against them. A rule
that appeared by itself between two runs would invalidate every number in the
report, and a pattern mined from text nobody checked would be an attacker's way of
writing his own detector. So this module does the useful half of "the engine learns
from what it sees" and refuses the dangerous half:

* it **mines** candidate phrases from cases a human confirmed as injections, or
  that the transformer flagged with no rule able to explain them (``model_only``);
* it **filters** them against the dev split -- a candidate that also matches benign
  dev text is dropped, and one an existing rule already covers is redundant;
* it **reports** what each candidate would add on dev: which dev injections it
  matches, how many of those the rule engine currently misses, and its dev
  precision;
* it **writes** them to ``data/rules/proposals.yaml`` as proposals with a status,
  appended and never rewritten.

Nothing here changes a score. An approved candidate becomes a rule in a *separate*
advisory engine (``approved_rules``), whose hits are shown to a reviewer and
recorded; it is not part of ``default_rules()``, its features never enter the
fusion model's fixed feature vector, and no reported result moves because of it.
Folding a candidate into the scored detector is a deliberate act: add it to
``lexicons.py``, rebuild the corpus, re-run the frozen protocol and log the run.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import __version__
from ..normalize.pipeline import Normalizer
from ..paths import CORPUS_PATH, DATA_DIR
from ..rules import RuleEngine
from ..rules.base import Rule, RuleFamily
from ..rules.pattern_rule import PatternRule
from ..schema import Label, Split, read_jsonl
from ..sdk import load_dev_thresholds
from .families import MODEL_ONLY
from .store import ScanFilter, ScanStore

__all__ = [
    "CANDIDATE_WEIGHT",
    "PROPOSALS_PATH",
    "Candidate",
    "advisory_hits",
    "approved_rules",
    "decide_proposal",
    "evaluate_candidates",
    "load_proposals",
    "mine_candidates",
    "write_proposals",
]

PROPOSALS_PATH = DATA_DIR / "rules" / "proposals.yaml"

#: Weight a proposal starts with. Deliberately below every retained pattern: with
#: the strongest family weight (meta_instruction, 0.95) a lone candidate hit
#: aggregates to ~0.57, under the rules-only 1%-FPR threshold (0.8340), so even if
#: a candidate were promoted it could not flag a document on its own -- it has to
#: corroborate another family. Approval may raise it, with a rationale.
CANDIDATE_WEIGHT = 0.60

MIN_TOKENS = 3
MAX_TOKENS = 7
#: A candidate has to carry at least one contentful token; "of the and" is not a rule.
MIN_LONG_TOKENS = 1
_LONG = 4

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'_-]*")
#: Function words. A phrase made only of these says nothing about an attack.
_STOPWORD_TEXT = (
    "a an and are as at be been by for from had has have i if in into is it its of on or "
    "our so that the their them then there these they this to was we were what when which who "
    "will with you your"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


@dataclass
class Candidate:
    """One mined phrase, with everything a reviewer needs to judge it."""

    candidate_id: str
    phrase: str
    pattern: str
    family: str
    weight: float
    support: int
    provenance: list[str] = field(default_factory=list)
    scan_ids: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    dev: dict[str, Any] = field(default_factory=dict)

    def to_entry(self) -> dict[str, Any]:
        """The YAML shape: the candidate plus its review state."""

        return {
            **asdict(self),
            "status": "proposed",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "versions": {"llmsentinel": __version__},
            "decisions": [],
        }


# --------------------------------------------------------------------- mining
def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _useful(tokens: Sequence[str]) -> bool:
    if all(token in _STOPWORDS for token in tokens):
        return False
    return sum(1 for token in tokens if len(token) >= _LONG and token not in _STOPWORDS) >= MIN_LONG_TOKENS


def _ngrams(tokens: Sequence[str]) -> set[tuple[str, ...]]:
    grams: set[tuple[str, ...]] = set()
    for size in range(MIN_TOKENS, MAX_TOKENS + 1):
        for start in range(0, max(0, len(tokens) - size + 1)):
            gram = tuple(tokens[start : start + size])
            if _useful(gram):
                grams.add(gram)
    return grams


def _pattern_for(gram: Sequence[str]) -> str:
    """Regex for a phrase, tolerant of the punctuation and spacing between words.

    ``[\\W_]+`` rather than ``\\s+`` because inserting a comma inside a phrase is
    the cheapest evasion there is, and the measured cost of not allowing it is in
    ``docs/robustness.md`` (punctuation transform, recall 0.79).
    """

    return r"\b" + r"[\W_]+".join(re.escape(token) for token in gram) + r"\b"


def _candidate_id(pattern: str) -> str:
    return "cand-" + hashlib.sha256(pattern.encode("utf-8")).hexdigest()[:10]


def _family_for(records: Sequence[Any]) -> str:
    """The family the source cases look like, defaulting to meta_instruction."""

    counts: dict[str, int] = {}
    for record in records:
        for family in record.families or []:
            if family == MODEL_ONLY:
                continue
            counts[family] = counts.get(family, 0) + 1
    if not counts:
        return RuleFamily.META_INSTRUCTION
    best = max(counts.items(), key=lambda item: item[1])[0]
    return best if best in RuleFamily.ALL else RuleFamily.META_INSTRUCTION


def _mineable(store: ScanStore, limit: int) -> list[tuple[Any, str]]:
    """Content scans worth mining, each with why it qualified."""

    cases: list[tuple[Any, str]] = []
    for record in store.list(ScanFilter(kind="content"), limit=limit):
        if not record.text or not record.scan_id:
            continue
        reviewed = store.overrides(record.scan_id)
        if reviewed:
            # A reviewer's label wins: "benign" or "unsure" means this text is not
            # evidence of an attack, and mining it would learn a false positive.
            if reviewed[-1].label == "injection":
                cases.append((record, "reviewer"))
        elif record.flagged and MODEL_ONLY in (record.families or []):
            cases.append((record, "model_only"))
    return cases


def mine_candidates(
    store: ScanStore,
    *,
    limit: int = 500,
    min_support: int = 2,
    max_candidates: int = 20,
    engine: RuleEngine | None = None,
    normalizer: Normalizer | None = None,
    benign_texts: Iterable[str] | None = None,
) -> list[Candidate]:
    """Candidate phrases shared by cases the current rules could not explain.

    ``min_support`` counts *distinct texts* (by content hash), so one document
    scanned ten times still supports a candidate once.
    """

    engine = engine or RuleEngine()
    normalizer = normalizer or Normalizer()
    cases = _mineable(store, limit)
    if not cases:
        return []

    grams: dict[tuple[str, ...], dict[str, Any]] = {}
    for record, why in cases:
        unit = normalizer.normalize_text(record.text or "", channel=record.channel or "rag_document")
        digest = record.text_sha256 or hashlib.sha256((record.text or "").encode("utf-8")).hexdigest()
        for gram in _ngrams(_tokens(unit.normalized_text or "")):
            slot = grams.setdefault(gram, {"texts": set(), "records": [], "why": set(), "channels": set()})
            if digest in slot["texts"]:
                continue
            slot["texts"].add(digest)
            slot["records"].append(record)
            slot["why"].add(why)
            if record.channel:
                slot["channels"].add(record.channel)

    supported = {gram: slot for gram, slot in grams.items() if len(slot["texts"]) >= min_support}
    # Keep the most specific phrase: drop a gram contained in a longer gram that
    # the same texts support, so one finding does not become five proposals.
    by_length = sorted(supported, key=len, reverse=True)
    kept: list[tuple[str, ...]] = []
    for gram in by_length:
        joined = " ".join(gram)
        if any(joined in " ".join(other) and supported[other]["texts"] >= supported[gram]["texts"] for other in kept):
            continue
        kept.append(gram)

    benign = [text.lower() for text in (benign_texts or [])]
    candidates: list[Candidate] = []
    for gram in kept:
        slot = supported[gram]
        phrase = " ".join(gram)
        if any(phrase in text for text in benign):
            continue
        pattern = _pattern_for(gram)
        # Redundant if an existing rule already fires on the phrase by itself.
        if engine.analyse_text(phrase)[1].hits:
            continue
        records = slot["records"]
        candidates.append(
            Candidate(
                candidate_id=_candidate_id(pattern),
                phrase=phrase,
                pattern=pattern,
                family=_family_for(records),
                weight=CANDIDATE_WEIGHT,
                support=len(slot["texts"]),
                provenance=sorted(slot["why"]),
                scan_ids=[r.scan_id for r in records if r.scan_id][:10],
                channels=sorted(slot["channels"]),
                examples=_examples(records, phrase),
            )
        )
    candidates.sort(key=lambda c: (c.support, len(c.phrase)), reverse=True)
    return candidates[:max_candidates]


def _examples(records: Sequence[Any], phrase: str, *, width: int = 160) -> list[str]:
    """Sanitised excerpts around the phrase, so a reviewer sees it in context."""

    from .fixtures import sanitise_for_fixture  # local import: fixtures imports the store too

    out: list[str] = []
    for record in records[:3]:
        text = " ".join((record.text or "").split())
        clean, _ = sanitise_for_fixture(text)
        lower = clean.lower()
        at = lower.find(phrase.split()[0])
        start = max(0, at - width // 3)
        out.append(clean[start : start + width])
    return out


# ----------------------------------------------------------- dev evaluation
def evaluate_candidates(
    candidates: Sequence[Candidate],
    *,
    corpus_path: str | Path = CORPUS_PATH,
    engine: RuleEngine | None = None,
    threshold: float | None = None,
) -> list[Candidate]:
    """Fill each candidate's ``dev`` block: what it would match on the dev split.

    Dev only. The test split is not read here and must not be: a candidate chosen
    against test would turn the held-out set into training data.
    """

    corpus_path = Path(corpus_path)
    if not corpus_path.is_file():
        for candidate in candidates:
            candidate.dev = {"available": False, "reason": f"no corpus at {corpus_path}"}
        return list(candidates)

    records = [record for record in read_jsonl(corpus_path) if record.split == Split.DEV]
    positives = [r for r in records if r.label == Label.INJECTION]
    negatives = [r for r in records if r.label != Label.INJECTION]
    engine = engine or RuleEngine()
    if threshold is None:
        threshold = load_dev_thresholds("rules-only").get("fpr=0.01")

    scores: dict[str, float] = {}

    def rules_score(record: Any) -> float:
        if record.record_id not in scores:
            text = record.normalized_text or record.raw_text
            scores[record.record_id] = float(engine.analyse_text(text, channel=record.channel)[1].score)
        return scores[record.record_id]

    for candidate in candidates:
        pattern = re.compile(candidate.pattern, re.IGNORECASE | re.MULTILINE)
        matched_pos = [r for r in positives if pattern.search(r.normalized_text or r.raw_text)]
        matched_neg = [r for r in negatives if pattern.search(r.normalized_text or r.raw_text)]
        matched = len(matched_pos) + len(matched_neg)
        new_positives = (
            None
            if threshold is None
            else sum(1 for record in matched_pos if rules_score(record) < threshold)
        )
        candidate.dev = {
            "available": True,
            "injections_matched": len(matched_pos),
            "benign_matched": len(matched_neg),
            "precision": round(len(matched_pos) / matched, 4) if matched else None,
            "injections_missed_by_rules_now": new_positives,
            "rules_threshold": round(threshold, 6) if threshold is not None else None,
            "dev_injections": len(positives),
            "dev_benign": len(negatives),
        }
    ordered = sorted(
        candidates,
        key=lambda c: (
            c.dev.get("injections_missed_by_rules_now") or 0,
            c.dev.get("injections_matched") or 0,
            c.support,
        ),
        reverse=True,
    )
    return ordered


# ----------------------------------------------------------------- proposals
def load_proposals(path: str | Path = PROPOSALS_PATH) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    proposals = data.get("proposals") or []
    if not isinstance(proposals, list):
        raise ValueError(f"{path}: 'proposals' must be a list")
    return proposals


_HEADER = (
    "# Candidate rules mined from reviewed analyst cases (append-only, advisory).\n"
    "# Written by llmsentinel.analyst.proposals; nothing here is part of the scored\n"
    "# detector. An approved candidate runs only in the advisory engine\n"
    "# (llmsentinel rules check). See docs/research_boundary.md.\n"
)


def _write(path: Path, proposals: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"version": 1, "proposals": proposals}, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(_HEADER + body, encoding="utf-8")


def write_proposals(
    candidates: Sequence[Candidate], *, path: str | Path = PROPOSALS_PATH
) -> tuple[list[str], list[str]]:
    """Append new candidates. Returns ``(added_ids, skipped_ids)``.

    An existing proposal is never rewritten, including one that was rejected:
    re-mining the same phrase must not quietly undo a reviewer's decision.
    """

    path = Path(path)
    existing = load_proposals(path)
    known = {str(item.get("candidate_id")) for item in existing}
    added, skipped = [], []
    for candidate in candidates:
        if candidate.candidate_id in known:
            skipped.append(candidate.candidate_id)
            continue
        existing.append(candidate.to_entry())
        known.add(candidate.candidate_id)
        added.append(candidate.candidate_id)
    if added:
        _write(path, existing)
    return added, skipped


def decide_proposal(
    candidate_id: str,
    *,
    status: str,
    reviewer: str,
    rationale: str,
    weight: float | None = None,
    family: str | None = None,
    path: str | Path = PROPOSALS_PATH,
) -> dict[str, Any]:
    """Approve or reject a proposal, keeping the decision trail."""

    if status not in ("approved", "rejected"):
        raise ValueError("status must be 'approved' or 'rejected'")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if len(rationale.strip()) < 15:
        raise ValueError("give a rationale of at least 15 characters: it is the record of why this rule exists")
    if family is not None and family not in RuleFamily.ALL:
        raise ValueError(f"unknown family {family!r}")
    if weight is not None and not 0.0 < weight <= 1.0:
        raise ValueError("weight must be in (0, 1]")

    path = Path(path)
    proposals = load_proposals(path)
    for entry in proposals:
        if str(entry.get("candidate_id")) != candidate_id:
            continue
        entry["status"] = status
        if weight is not None:
            entry["weight"] = weight
        if family is not None:
            entry["family"] = family
        entry.setdefault("decisions", []).append(
            {
                "status": status,
                "reviewer": reviewer.strip(),
                "rationale": rationale.strip(),
                "weight": entry["weight"],
                "family": entry["family"],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        _write(path, proposals)
        return entry
    raise KeyError(f"no proposal {candidate_id!r}")


# ----------------------------------------------------------- advisory engine
def approved_rules(path: str | Path = PROPOSALS_PATH) -> list[Rule]:
    """Approved candidates as rules, for the advisory engine only."""

    rules: list[Rule] = []
    for entry in load_proposals(path):
        if entry.get("status") != "approved":
            continue
        candidate_id = str(entry["candidate_id"])
        rules.append(
            PatternRule(
                rule_id=f"candidate.{candidate_id}",
                family=str(entry.get("family") or RuleFamily.META_INSTRUCTION),
                patterns=((candidate_id.replace("-", "_"), str(entry["pattern"]), float(entry["weight"])),),
                feature_prefix=f"rule.candidate.{candidate_id.replace('-', '_')}",
            )
        )
    return rules


def advisory_hits(
    text: str,
    *,
    channel: str = "rag_document",
    host_task: str | None = None,
    path: str | Path = PROPOSALS_PATH,
) -> list[dict[str, Any]]:
    """Run the approved candidates over ``text`` and return their hits.

    This is a second opinion for a reviewer, never a verdict: the score that
    decides anything still comes from the frozen detector.
    """

    rules = approved_rules(path)
    if not rules:
        return []
    engine = RuleEngine(rules=rules)
    _, report = engine.analyse_text(text, channel=channel, host_task=host_task)
    return [hit.to_dict() for hit in report.hits]
