"""SentinelGuard: LLMSentinel applied to each retrieved chunk before the model sees it.

Detector
    When the span-aware transformer checkpoint and its dev thresholds are present,
    the transformer is the headline detector (test AUPRC 0.984 in docs/report.md):
    a chunk is flagged when its risk reaches the transformer's **dev 1%-FPR**
    threshold. The rule engine always runs as well -- it supplies the highlighted
    spans and reasons, decodes embedded payloads (base64 etc.) through the
    normaliser's derived units, and also flags a chunk on its own when it reaches
    the rules' **0.1%-FPR** band. Without a checkpoint the Studio falls back to
    rules-only at the rules' 1%-FPR threshold and says so.

Isolation (the capability policy's "isolate" outcome)
    Rule spans are segment-level, so cutting every span can remove legitimate
    sentences (an "invite teammates by email" sentence trips the exfiltration
    rule). A flagged chunk is therefore split into sentences, with a hidden HTML
    comment kept whole. Candidates are the segments that are flagged on their own
    or overlap a rule span. They are removed most-suspicious first (own flag, then
    own risk), and the passage is re-scanned after each removal; isolation stops at
    the first remainder that re-scans clean. If it never does, or nothing would be
    left, the whole chunk is withheld. Every cut is localised by the same detector.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from llmsentinel.models.segment import segments
from llmsentinel.normalize.units import NormalizedUnit
from llmsentinel.rules import RuleEngine
from llmsentinel.schema import Channel, CorpusRecord, Label
from llmsentinel.verdict import RiskBand, build_verdict

from .config import StudioSettings
from .context import Chunk

__all__ = ["REMOVED_MARKER", "ChunkAssessment", "SentinelGuard", "load_segment_thresholds", "load_thresholds", "max_band"]

REMOVED_MARKER = "[removed by LLMSentinel]"
MAX_SEGMENTS = 80
_ORDER = {RiskBand.LOW: 0, RiskBand.ELEVATED: 1, RiskBand.HIGH: 2}
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n")
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)


def load_thresholds(path: Path, system: str) -> dict[str, float]:
    path = Path(path)
    if not path.is_file():
        return {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        if entry.get("name") == system and entry.get("dev"):
            return {key: float(value) for key, value in entry["dev"]["thresholds"].items()}
    return {}


def load_segment_thresholds(path: Path) -> dict[str, float]:
    """Dev thresholds for segment scoring, from ``scripts/select_segment_thresholds.py``."""

    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: float(value) for key, value in (data.get("dev") or {}).get("thresholds", {}).items()}


def max_band(*bands: str | None) -> str:
    present = [b for b in bands if b]
    return max(present, key=lambda b: _ORDER.get(b, 0)) if present else RiskBand.LOW


@dataclass(slots=True)
class ChunkAssessment:
    chunk_id: str
    doc_id: str
    source: str
    label: str
    channel: str
    json_path: str | None
    rank: int
    retrieval_score: float
    text: str
    rule_risk: float
    rule_band: str
    model_risk: float | None
    model_band: str | None
    risk: float
    band: str
    flagged: bool
    decided_by: str
    spans: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    decoded: list[str] = field(default_factory=list)
    top_window: str | None = None
    action: str = "keep"  # keep | strip | withhold
    sanitized_text: str = ""
    removed: list[str] = field(default_factory=list)
    cuts: list[dict[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(ranges: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    clipped = sorted((max(0, s), min(length, e)) for s, e in ranges if min(length, e) > max(0, s))
    merged: list[list[int]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    piece = text[start:end]
    return start + len(piece) - len(piece.lstrip()), start + len(piece.rstrip())


def _sentence_segments(text: str, start: int, end: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE_END.finditer(text, start, end):
        out.append((cursor, match.end()))
        cursor = match.end()
    if cursor < end:
        out.append((cursor, end))
    return out


def _segments(text: str) -> list[tuple[int, int]]:
    """Sentences and lines, with each hidden HTML comment kept as one segment."""

    raw: list[tuple[int, int]] = []
    cursor = 0
    for match in _COMMENT.finditer(text):
        raw.extend(_sentence_segments(text, cursor, match.start()))
        raw.append((match.start(), match.end()))
        cursor = match.end()
    raw.extend(_sentence_segments(text, cursor, len(text)))
    trimmed = (_trim(text, s, e) for s, e in raw)
    return [(s, e) for s, e in trimmed if e > s]


def _tidy(text: str) -> str:
    text = re.sub(rf"{re.escape(REMOVED_MARKER)}(?:[ \t]*{re.escape(REMOVED_MARKER)})+", REMOVED_MARKER, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _remove(text: str, cuts: list[tuple[int, int]], marker: str = REMOVED_MARKER) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(cuts):
        pieces.extend([text[cursor:start], marker or " "])
        cursor = end
    pieces.append(text[cursor:])
    return _tidy("".join(pieces))


class SentinelGuard:
    def __init__(self, settings: StudioSettings | None = None) -> None:
        self.settings = settings or StudioSettings()
        self.engine = RuleEngine()
        self.normalizer = self.engine.normalizer
        self.rule_thresholds = load_thresholds(self.settings.results_path, "rules-only")
        self.model_thresholds = load_thresholds(self.settings.results_path, "transformer")
        self.transformer: Any = None
        self.notes: list[str] = []
        if not self.rule_thresholds:
            self.notes.append("No rules-only dev thresholds found in results_dev.json; every rule band reads low.")
        #: "segment" (max over passage and sentences) or "passage".
        self.scoring = "passage"
        if self.settings.use_transformer:
            self._load_transformer()
        else:
            self.notes.append("Transformer disabled for this session: using the rules-only detector.")
        if self.transformer is not None and self.settings.segment_scoring:
            segment = load_segment_thresholds(self.settings.segment_thresholds_path)
            if segment:
                self.model_thresholds = segment
                self.scoring = "segment"
            else:
                self.notes.append(
                    "No segment thresholds (run scripts/select_segment_thresholds.py): the transformer "
                    "scores whole passages, which misses injections embedded in benign prose."
                )

    # ----------------------------------------------------------------- setup
    def _load_transformer(self) -> None:
        from llmsentinel.models.transformer import TransformerScorer, torch_available

        checkpoint = Path(self.settings.checkpoint)
        if not torch_available():
            self.notes.append("PyTorch is not installed: using the rules-only detector.")
        elif not checkpoint.is_dir():
            self.notes.append(f"No transformer checkpoint at {checkpoint}: using the rules-only detector.")
        elif not self.model_thresholds:
            self.notes.append("No transformer dev thresholds in results_dev.json: using the rules-only detector.")
        else:
            self.transformer = TransformerScorer.load(checkpoint)

    @property
    def detector(self) -> str:
        return "transformer + rules" if self.transformer is not None else "rules-only"

    def status(self) -> dict[str, Any]:
        scope = "its riskiest sentence or the whole passage" if self.scoring == "segment" else "the passage"
        rule = (
            f"Flag when the transformer, scoring {scope}, reaches its dev 1%-FPR threshold, or the "
            "rule engine reaches its dev 0.1%-FPR band."
            if self.transformer is not None
            else "Flag when the rule engine reaches its dev 1%-FPR threshold."
        )
        return {
            "detector": self.detector,
            "transformer_loaded": self.transformer is not None,
            "scoring": self.scoring if self.transformer is not None else "rules",
            "decision_rule": rule,
            "rule_thresholds": self.rule_thresholds,
            "model_thresholds": self.model_thresholds if self.transformer is not None else {},
            "notes": list(self.notes),
        }

    # -------------------------------------------------------------- analysis
    def _unit(self, text: str, channel: str, json_path: str | None, host_task: str) -> NormalizedUnit:
        return self.normalizer.normalize_text(
            text,
            channel=channel,
            json_path=json_path,
            metadata={"host_task": host_task} if host_task else None,
        )

    def _rules(self, unit: NormalizedUnit) -> tuple[float, str, list[tuple[int, int, str]], list[str], list[str], list[str]]:
        verdict = build_verdict(unit, self.engine.analyse(unit), thresholds=self.rule_thresholds)
        risk, band = verdict.risk, verdict.band
        ranges = [(s.start, s.end, s.note or "") for s in verdict.flagged_spans if s.field == "raw_text"]
        reasons = list(verdict.rule_trace)
        evidence = sorted({item.kind for item in verdict.normalisation_evidence})
        decoded: list[str] = []
        for child in self.normalizer.derived_units(unit):
            child_verdict = build_verdict(child, self.engine.analyse(child), thresholds=self.rule_thresholds)
            decoded.append(child.normalized_text[:300])
            if child_verdict.risk > risk:
                risk, band = child_verdict.risk, child_verdict.band
            if child_verdict.band != RiskBand.LOW and child.parent_span is not None:
                ranges.append((child.parent_span.start, child.parent_span.end, "decoded payload"))
                reasons.extend(f"(decoded) {reason}" for reason in child_verdict.rule_trace)
        return risk, band, ranges, reasons, evidence, decoded

    def _model(self, texts: list[tuple[str, str, str | None, NormalizedUnit]]) -> list[Any]:
        if self.transformer is None or not texts:
            return [None] * len(texts)
        records = []
        for index, (text, channel, json_path, unit) in enumerate(texts):
            digest = hashlib.sha1(f"{index}:{text}".encode()).hexdigest()[:12]
            records.append(
                CorpusRecord(
                    record_id=f"studio-{digest}",
                    source_dataset="studio",
                    source_document_id=f"studio-{digest}",
                    source_license="n/a",
                    raw_text=text,
                    normalized_text=unit.normalized_text or text,
                    normalisation_version=unit.normalisation_version,
                    label=Label.BENIGN,
                    channel=Channel.coerce(channel),
                    json_path=json_path,
                )
            )
        details = list(self.transformer.score_details(records))
        if self.scoring != "segment":
            return details
        # Segment scoring: a sentence can carry the passage's risk on its own, so a
        # payload inside benign prose is not masked by the text around it.
        owner: list[int] = []
        pieces: list[str] = []
        for index, (text, _channel, _path, unit) in enumerate(texts):
            for piece in segments(unit.normalized_text or text):
                owner.append(index)
                pieces.append(piece)
        if pieces:
            for index, piece, value in zip(owner, pieces, self.transformer.score_texts(pieces), strict=True):
                if float(value) > float(details[index].risk):
                    details[index] = replace(details[index], risk=float(value), top_window_text=piece[:200])
        return details

    def _decide(self, rule_band: str, model_detail: Any) -> tuple[bool, str, str | None, float | None, str]:
        if model_detail is None:
            return rule_band != RiskBand.LOW, rule_band, None, None, "rules"
        model_risk = float(model_detail.risk)
        model_band = RiskBand.of(model_risk, self.model_thresholds)
        rules_high = rule_band == RiskBand.HIGH
        flagged = model_band != RiskBand.LOW or rules_high
        band = max_band(model_band, RiskBand.HIGH if rules_high else None)
        if model_band != RiskBand.LOW:
            decided_by = "transformer"
        elif rules_high:
            decided_by = "rules (0.1%-FPR band)"
        else:
            decided_by = "transformer"
        return flagged, band, model_band, model_risk, decided_by

    def assess(
        self, retrieved: list[tuple[Chunk, float]], host_task: str = "", *, isolate: bool = True
    ) -> list[ChunkAssessment]:
        units = [self._unit(c.text, c.channel, c.json_path, host_task) for c, _ in retrieved]
        details = self._model([(c.text, c.channel, c.json_path, u) for (c, _), u in zip(retrieved, units, strict=True)])
        out: list[ChunkAssessment] = []
        for rank, ((chunk, score), unit, detail) in enumerate(zip(retrieved, units, details, strict=True), 1):
            rule_risk, rule_band, ranges, reasons, evidence, decoded = self._rules(unit)
            flagged, band, model_band, model_risk, decided_by = self._decide(rule_band, detail)
            risk = model_risk if model_risk is not None else rule_risk
            if model_risk is not None and rule_band == RiskBand.HIGH:
                risk = max(model_risk, rule_risk)
            spans = _merge([(s, e) for s, e, _ in ranges], len(chunk.text))
            assessment = ChunkAssessment(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                source=chunk.source,
                label=chunk.label,
                channel=chunk.channel,
                json_path=chunk.json_path,
                rank=rank,
                retrieval_score=score,
                text=chunk.text,
                rule_risk=round(float(rule_risk), 4),
                rule_band=rule_band,
                model_risk=None if model_risk is None else round(model_risk, 4),
                model_band=model_band,
                risk=round(float(risk), 4),
                band=band,
                flagged=flagged,
                decided_by=decided_by,
                spans=[{"start": s, "end": e} for s, e in spans],
                reasons=reasons[:8],
                evidence=evidence,
                decoded=decoded,
                top_window=getattr(detail, "top_window_text", None),
            )
            if isolate:
                self._isolate(assessment, ranges, host_task)
            else:  # scored only (tool metadata is quarantined per tool, not stripped)
                assessment.sanitized_text = chunk.text
            out.append(assessment)
        return out

    # ------------------------------------------------------------- isolation
    def _score_texts(
        self, texts: list[str], assessment: ChunkAssessment, host_task: str
    ) -> list[tuple[bool, float, float]]:
        """(suspicious, transformer risk or 0, rule risk) for each text, under the chunk's provenance.

        Isolation is stricter than detection. Detection decides whether a passage is
        poisoned at all, so with the transformer loaded the rules count only at their
        0.1%-FPR band. Once a passage is known to be poisoned, a segment or remainder
        is treated as suspicious if *either* component reaches its dev 1%-FPR point.
        Without this, removing the highest-transformer-risk sentence could leave an
        exfiltration sentence that the rules rate elevated, and the remainder would be
        forwarded as "clean" (seen on the sample pack's sharing guide).
        """

        units = [self._unit(t, assessment.channel, assessment.json_path, host_task) for t in texts]
        details = self._model(
            [(t, assessment.channel, assessment.json_path, u) for t, u in zip(texts, units, strict=True)]
        )
        scores: list[tuple[bool, float, float]] = []
        for unit, detail in zip(units, details, strict=True):
            rule_risk, rule_band, _, _, _, _ = self._rules(unit)
            _, _, model_band, model_risk, _ = self._decide(rule_band, detail)
            suspicious = rule_band != RiskBand.LOW or (model_band is not None and model_band != RiskBand.LOW)
            scores.append((suspicious, 0.0 if model_risk is None else model_risk, float(rule_risk)))
        return scores

    def _still_flagged(self, content: str, assessment: ChunkAssessment, host_task: str) -> bool:
        # ``content`` is the untrusted text that remains, *without* our marker: the
        # marker is Studio's own annotation, and on the sample pack the transformer
        # scores "[removed by LLMSentinel]" itself as instruction-like (plans FAQ
        # remainder 0.9988 with it, 0.7153 without), which would withhold clean text.
        if not content.strip():
            return False
        return self._score_texts([content], assessment, host_task)[0][0]

    def _withhold(self, assessment: ChunkAssessment) -> None:
        assessment.action, assessment.sanitized_text = "withhold", ""
        assessment.removed, assessment.cuts = [assessment.text], []

    def _isolate(self, assessment: ChunkAssessment, ranges: list[tuple[int, int, str]], host_task: str) -> None:
        text = assessment.text
        if not assessment.flagged:
            assessment.action, assessment.sanitized_text = "keep", text
            return
        segments = _segments(text)
        if len(segments) > MAX_SEGMENTS:
            self._withhold(assessment)
            return
        scores = self._score_texts([text[s:e] for s, e in segments], assessment, host_task)
        candidates = [
            (score, segment)
            for segment, score in zip(segments, scores, strict=True)
            if score[0] or any(s < segment[1] and segment[0] < e for s, e, _ in ranges)
        ]
        # Most suspicious first: flagged on its own, then transformer risk, then rule risk.
        candidates.sort(key=lambda item: (not item[0][0], -item[0][1], -item[0][2], item[1][0]))

        chosen: list[tuple[int, int]] = []
        for _, segment in candidates:
            chosen.append(segment)
            content = _remove(text, chosen, marker="")
            if not content.strip():
                break
            if not self._still_flagged(content, assessment, host_task):
                cuts = sorted(chosen)
                assessment.action, assessment.sanitized_text = "strip", _remove(text, chosen)
                assessment.removed = [text[s:e] for s, e in cuts]
                assessment.cuts = [{"start": s, "end": e} for s, e in cuts]
                return
        self._withhold(assessment)
