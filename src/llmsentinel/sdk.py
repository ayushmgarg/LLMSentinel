"""Python SDK: scan untrusted context, gate proposed actions, keep an analyst history.

::

    from llmsentinel.sdk import Sentinel

    sentinel = Sentinel()                        # transformer if available, else rules
    page = sentinel.scan_text(html, source="https://docs.vendor.io/faq")
    tools = sentinel.scan_manifest(manifest["tools"], server="vendor-mcp")
    decision = sentinel.gate("send_email", context=page)
    if not decision.outcome.permits_action:
        ...                                      # do not call the tool

**This is not production enforcement.** The SDK is a library call inside your own
process: it advises and it records, but it cannot stop code that ignores its answer,
it has no authentication, and it inherits every limit reported in ``docs/report.md``
(notably, dev thresholds do not transfer to unseen sources). Keep least privilege,
human approval for sensitive actions and server-side authorisation in place.

Decision rule (the same one the Studio uses): with the transformer loaded, a unit is
flagged when the model reaches its dev 1%-FPR threshold or the rules reach their dev
0.1%-FPR band; without it, when the rules reach their dev 1%-FPR threshold.
Thresholds are read from ``artifacts/results/results_dev.json``; nothing is hard-coded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import __version__
from .analyst.families import families_from_trace
from .analyst.review import review_reasons_for
from .analyst.store import Alert, ScanRecord, ScanStore
from .models.segment import segments
from .normalize.units import NormalizedUnit
from .paths import MODELS_DIR, RESULTS_DIR, relative
from .policy import CapabilityPolicy, Outcome, PolicyDecision, ProposedAction
from .rules import RuleEngine
from .schema import Channel, CorpusRecord, Label
from .verdict import RiskBand, Verdict, build_verdict

__all__ = [
    "ManifestScan",
    "ScanResult",
    "Sentinel",
    "ToolScan",
    "UnitResult",
    "load_dev_thresholds",
    "tool_fields",
]

_ORDER = {RiskBand.LOW: 0, RiskBand.ELEVATED: 1, RiskBand.HIGH: 2}


def load_segment_thresholds(path: str | Path | None = None) -> dict[str, float]:
    """Dev thresholds for segment scoring (``scripts/select_segment_thresholds.py``)."""

    source = Path(path) if path else RESULTS_DIR / "segment_thresholds.json"
    if not source.is_file():
        return {}
    data = json.loads(source.read_text(encoding="utf-8"))
    return {key: float(value) for key, value in (data.get("dev") or {}).get("thresholds", {}).items()}


def load_dev_thresholds(system: str, path: str | Path | None = None) -> dict[str, float]:
    """Dev-selected operating points for ``system``; empty when unavailable."""

    source = Path(path) if path else RESULTS_DIR / "results_dev.json"
    if not source.is_file():
        return {}
    for entry in json.loads(source.read_text(encoding="utf-8")):
        if entry.get("name") == system and entry.get("dev"):
            return {key: float(value) for key, value in entry["dev"]["thresholds"].items()}
    return {}


def _max_band(*bands: str | None) -> str:
    present = [band for band in bands if band]
    return max(present, key=lambda band: _ORDER.get(band, 0)) if present else RiskBand.LOW


def tool_fields(tool: dict[str, Any]) -> list[tuple[str, str]]:
    """Description and parameter descriptions: the prose an agent reads from a manifest."""

    fields = [("$.description", str(tool.get("description") or ""))]
    schema = tool.get("parameters", tool.get("inputSchema", {})) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if isinstance(properties, dict):
        for key, spec in properties.items():
            if isinstance(spec, dict) and str(spec.get("description") or "").strip():
                fields.append((f"$.parameters.properties.{key}.description", str(spec["description"])))
    return [(path, text) for path, text in fields if text.strip()]


# ------------------------------------------------------------------ results
@dataclass(slots=True)
class UnitResult:
    """One normalised unit (a document, a JSON leaf, a decoded payload) and its call."""

    verdict: Verdict
    text: str
    risk: float
    band: str
    flagged: bool
    decided_by: str
    model_score: float | None = None
    families: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    scan_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "risk": round(self.risk, 4),
            "band": self.band,
            "flagged": self.flagged,
            "decided_by": self.decided_by,
            "model_score": None if self.model_score is None else round(self.model_score, 4),
            "families": self.families,
            "review_reasons": self.review_reasons,
            "verdict": self.verdict.to_dict(),
        }


@dataclass(slots=True)
class ScanResult:
    source: str | None
    channel: str
    units: list[UnitResult]

    @property
    def flagged(self) -> bool:
        return any(unit.flagged for unit in self.units)

    @property
    def worst(self) -> UnitResult | None:
        return max(self.units, key=lambda unit: unit.risk, default=None)

    @property
    def risk(self) -> float:
        return self.worst.risk if self.worst else 0.0

    @property
    def band(self) -> str:
        return _max_band(RiskBand.LOW, *(unit.band for unit in self.units))

    @property
    def degraded(self) -> bool:
        return any(unit.verdict.degraded for unit in self.units)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "channel": self.channel,
            "flagged": self.flagged,
            "risk": round(self.risk, 4),
            "band": self.band,
            "units": [unit.to_dict() for unit in self.units],
        }


@dataclass(slots=True)
class ToolScan:
    name: str
    fields: ScanResult
    drift: str | None
    quarantined: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ManifestScan:
    server: str
    tools: list[ToolScan]
    alerts: list[Alert] = field(default_factory=list)

    @property
    def quarantined(self) -> set[str]:
        return {tool.name for tool in self.tools if tool.quarantined}

    @property
    def risk(self) -> float:
        return max((tool.fields.risk for tool in self.tools), default=0.0)

    @property
    def band(self) -> str:
        return _max_band(RiskBand.LOW, *(tool.fields.band for tool in self.tools))

    @property
    def degraded(self) -> bool:
        return any(tool.fields.degraded for tool in self.tools)


# ------------------------------------------------------------------- facade
class Sentinel:
    """Detector + capability policy + optional analyst history, behind one object."""

    def __init__(
        self,
        *,
        detector: str = "auto",
        checkpoint: str | Path | None = None,
        results_path: str | Path | None = None,
        store: ScanStore | None = None,
        policy: CapabilityPolicy | None = None,
        engine: RuleEngine | None = None,
        segment_scoring: bool = True,
        segment_thresholds_path: str | Path | None = None,
    ) -> None:
        if detector not in ("auto", "rules", "transformer"):
            raise ValueError("detector must be 'auto', 'rules' or 'transformer'")
        self.results_path = Path(results_path) if results_path else RESULTS_DIR / "results_dev.json"
        self.engine = engine or RuleEngine()
        self.normalizer = self.engine.normalizer
        self.policy = policy or CapabilityPolicy()
        self.store = store
        self.rule_thresholds = load_dev_thresholds("rules-only", self.results_path)
        self.model_thresholds: dict[str, float] = {}
        self.transformer: Any = None
        self.notes: list[str] = []
        #: "segment": the transformer scores the passage and each sentence and keeps the
        #: maximum (the deployed default since the fresh-v2 confirmation); "passage" otherwise.
        self.scoring = "passage"
        self.segment_scoring = segment_scoring
        self.segment_thresholds_path = (
            Path(segment_thresholds_path) if segment_thresholds_path else RESULTS_DIR / "segment_thresholds.json"
        )
        if not self.rule_thresholds:
            self.notes.append(f"no rules-only dev thresholds in {relative(self.results_path)}; every rule band reads low")
        if detector != "rules":
            target = Path(checkpoint) if checkpoint else MODELS_DIR / "transformer"
            self._load_transformer(target, required=detector == "transformer")

    def _load_transformer(self, checkpoint: Path, *, required: bool) -> None:
        from .models.transformer import TransformerScorer, torch_available

        thresholds = load_dev_thresholds("transformer", self.results_path)
        problem = None
        if not torch_available():
            problem = "PyTorch is not installed"
        elif not checkpoint.is_dir():
            problem = f"no transformer checkpoint at {relative(checkpoint)}"
        elif not thresholds:
            problem = "no transformer dev thresholds"
        if problem:
            if required:
                raise RuntimeError(f"transformer detector requested but {problem}")
            self.notes.append(f"{problem}: using the rules-only detector")
            return
        self.transformer = TransformerScorer.load(checkpoint)
        self.model_thresholds = thresholds
        if self.segment_scoring:
            segment = load_segment_thresholds(self.segment_thresholds_path)
            if segment:
                self.model_thresholds = segment
                self.scoring = "segment"
            else:
                self.notes.append("no segment thresholds: the transformer scores whole passages")

    @property
    def detector(self) -> str:
        return "transformer + rules" if self.transformer is not None else "rules-only"

    def versions(self) -> dict[str, Any]:
        return {
            "llmsentinel": __version__,
            "detector": self.detector,
            "normalisation": getattr(self.normalizer, "version", None),
            "rules": sorted(rule.rule_id for rule in self.engine.rules),
            "policy": self.policy.config.version,
            "thresholds_source": relative(self.results_path),
            "scoring": self.scoring if self.transformer is not None else "rules",
        }

    # ------------------------------------------------------------ scoring
    def _model_scores(self, units: Sequence[NormalizedUnit]) -> list[float | None]:
        if self.transformer is None or not units:
            return [None] * len(units)
        records = []
        for index, unit in enumerate(units):
            digest = hashlib.sha1(f"{index}:{unit.raw_text}".encode()).hexdigest()[:12]
            records.append(
                CorpusRecord(
                    record_id=f"sdk-{digest}",
                    source_dataset="sdk",
                    source_document_id=f"sdk-{digest}",
                    source_license="n/a",
                    raw_text=unit.raw_text,
                    normalized_text=unit.normalized_text or unit.raw_text,
                    normalisation_version=unit.normalisation_version,
                    label=Label.BENIGN,
                    channel=unit.channel,
                    json_path=unit.json_path,
                )
            )
        scores = [float(detail.risk) for detail in self.transformer.score_details(records)]
        if self.scoring == "segment":
            owner: list[int] = []
            pieces: list[str] = []
            for index, unit in enumerate(units):
                for piece in segments(unit.normalized_text or unit.raw_text):
                    owner.append(index)
                    pieces.append(piece)
            if pieces:
                for index, value in zip(owner, self.transformer.score_texts(pieces), strict=True):
                    scores[index] = max(scores[index], float(value))
        return scores

    def _decide(self, verdict: Verdict, model_score: float | None) -> tuple[float, str, bool, str, dict[str, float]]:
        rule_band = verdict.band
        if model_score is None:
            return verdict.rule_score, rule_band, rule_band != RiskBand.LOW, "rules", self.rule_thresholds
        model_band = RiskBand.of(model_score, self.model_thresholds)
        rules_high = rule_band == RiskBand.HIGH
        flagged = model_band != RiskBand.LOW or rules_high
        band = _max_band(model_band, RiskBand.HIGH if rules_high else None)
        risk = max(model_score, verdict.rule_score) if rules_high else model_score
        decided_by = "rules (0.1%-FPR band)" if rules_high and model_band == RiskBand.LOW else "transformer"
        return risk, band, flagged, decided_by, self.model_thresholds

    def _score(self, units: Sequence[NormalizedUnit], host_task: str | None) -> list[UnitResult]:
        expanded: list[NormalizedUnit] = []
        for unit in units:
            if host_task:
                unit.metadata["host_task"] = host_task
            expanded.append(unit)
            expanded.extend(self.normalizer.derived_units(unit))
        results = []
        for unit, model_score in zip(expanded, self._model_scores(expanded), strict=True):
            verdict = build_verdict(unit, self.engine.analyse(unit), thresholds=self.rule_thresholds, model_score=model_score)
            risk, band, flagged, decided_by, thresholds = self._decide(verdict, model_score)
            results.append(
                UnitResult(
                    verdict=verdict,
                    text=unit.raw_text,
                    risk=float(risk),
                    band=band,
                    flagged=flagged,
                    decided_by=decided_by,
                    model_score=model_score,
                    families=families_from_trace(verdict.rule_trace, flagged=flagged),
                    review_reasons=review_reasons_for(
                        risk=float(risk),
                        band=band,
                        thresholds=thresholds,
                        flagged=flagged,
                        explained=verdict.explained,
                        rule_score=verdict.rule_score,
                        model_score=model_score,
                        degraded=verdict.degraded,
                    ),
                )
            )
        return results

    def _record(
        self,
        result: ScanResult,
        *,
        kind: str,
        server: str | None = None,
        tool: str | None = None,
        host_task: str | None = None,
        drift: str | None = None,
    ) -> None:
        if self.store is None:
            return
        for unit in result.units:
            verdict = unit.verdict
            saved = self.store.add(
                ScanRecord(
                    kind=kind,
                    source=result.source,
                    server=server,
                    tool=tool,
                    channel=verdict.channel.value,
                    json_path=verdict.json_path,
                    host_task=host_task,
                    text=unit.text,
                    risk=unit.risk,
                    band=unit.band,
                    rule_score=verdict.rule_score,
                    model_score=unit.model_score,
                    detector=self.detector,
                    decided_by=unit.decided_by,
                    thresholds=self.model_thresholds if unit.model_score is not None else self.rule_thresholds,
                    flagged=unit.flagged,
                    rule_trace=verdict.rule_trace[:12],
                    spans=[span.to_dict() for span in verdict.flagged_spans],
                    evidence=sorted({item.kind for item in verdict.normalisation_evidence}),
                    families=unit.families,
                    degraded=verdict.degraded,
                    drift=drift,
                    review_reasons=unit.review_reasons,
                    versions={**self.versions(), "normalisation": verdict.normalisation_version},
                )
            )
            unit.scan_id = saved.scan_id

    # ----------------------------------------------------------- scanning
    def scan_text(
        self,
        text: str,
        *,
        channel: str = "rag_document",
        source: str | None = None,
        host_task: str | None = None,
        record: bool = True,
    ) -> ScanResult:
        """Scan a document or any other untrusted prose, plus any payload decoded from it."""

        resolved = Channel.coerce(channel)
        unit = self.normalizer.normalize_text(text, channel=resolved)
        result = ScanResult(source=source, channel=resolved.value, units=self._score([unit], host_task))
        if record:
            self._record(result, kind="content", host_task=host_task)
        return result

    def scan_json(
        self,
        document: Any,
        *,
        tool: str | None = None,
        server: str | None = None,
        source: str | None = None,
        host_task: str | None = None,
        record: bool = True,
    ) -> ScanResult:
        """Scan a tool result: every string leaf, with its JSON path kept as provenance."""

        if isinstance(document, str):
            units, error = self.normalizer.normalize_json_text(document, channel=Channel.TOOL_RESPONSE)
            if error:
                units = [self.normalizer.normalize_text(document, channel=Channel.TOOL_RESPONSE)]
        else:
            units = self.normalizer.normalize_json(document, channel=Channel.TOOL_RESPONSE)
        result = ScanResult(
            source=source or (f"tool:{tool}" if tool else None),
            channel=Channel.TOOL_RESPONSE.value,
            units=self._score(list(units), host_task),
        )
        if record:
            self._record(result, kind="content", server=server, tool=tool, host_task=host_task)
        return result

    def scan_manifest(
        self,
        tools: Sequence[dict[str, Any]],
        *,
        server: str,
        source: str | None = None,
        record: bool = True,
    ) -> ManifestScan:
        """Scan every tool's description fields and, with a store, compare against approved pins.

        A tool is quarantined when a field is flagged, or when the store shows it changed
        or appeared after the server was approved. A server that was never approved
        raises ``unapproved`` alerts but is judged on content alone, because there is
        no approved state to have drifted from.
        """

        alerts: list[Alert] = []
        drift_by_tool: dict[str, str] = {}
        if self.store is not None:
            if record:
                alerts = self.store.check_manifest(server, tools)
            for alert in self.store.open_alerts(server):
                drift_by_tool.setdefault(alert.tool, alert.kind)
        scans: list[ToolScan] = []
        for tool in tools:
            name = str(tool.get("name"))
            units = [
                self.normalizer.normalize_text(text, channel=Channel.TOOL_METADATA, json_path=path)
                for path, text in tool_fields(tool)
            ]
            fields = ScanResult(source=source or f"mcp:{server}", channel=Channel.TOOL_METADATA.value, units=self._score(units, None))
            drift = drift_by_tool.get(name)
            reasons = [f"{u.verdict.json_path}: flagged by {u.decided_by} (risk {u.risk:.3f})" for u in fields.units if u.flagged]
            if drift in ("changed", "added"):
                reasons.append(f"declaration {drift} since the server was approved")
            if record:
                self._record(fields, kind="manifest", server=server, tool=name, drift=drift)
            scans.append(
                ToolScan(
                    name=name,
                    fields=fields,
                    drift=drift,
                    quarantined=fields.flagged or drift in ("changed", "added"),
                    reasons=reasons,
                )
            )
        return ManifestScan(server=server, tools=scans, alerts=alerts)

    # -------------------------------------------------------------- gating
    def gate(
        self,
        tool_name: str,
        *,
        context: ScanResult | ManifestScan | None = None,
        arguments: dict[str, Any] | None = None,
        record: bool = True,
    ) -> PolicyDecision:
        """Decide whether ``tool_name`` may run in ``context``; nothing is executed.

        With no context the policy treats the situation as high risk (absence of
        evidence is not evidence of safety). A tool quarantined by a manifest scan is
        blocked whatever the table says.
        """

        action = ProposedAction(tool_name=tool_name, arguments=dict(arguments or {}), description="proposed by the agent")
        if context is None:
            decision = self.policy.decide(action)
        else:
            decision = self.policy.decide(action, risk_band=context.band, risk=context.risk, degraded=context.degraded)
            if isinstance(context, ManifestScan) and tool_name in context.quarantined:
                tool = next(t for t in context.tools if t.name == tool_name)
                decision = replace(
                    decision,
                    outcome=Outcome.BLOCK,
                    reasons=("tool is quarantined by the manifest scan", *tool.reasons, *decision.reasons),
                )
        if record and self.store is not None:
            if isinstance(context, ScanResult):
                source, server = context.source, None
                parent = context.worst.scan_id if context.worst else None
            elif isinstance(context, ManifestScan):
                source, server, parent = f"mcp:{context.server}", context.server, None
            else:
                source = server = parent = None
            self.store.add(
                ScanRecord(
                    kind="action",
                    source=source,
                    server=server,
                    tool=tool_name,
                    risk=decision.risk,
                    band=decision.risk_band,
                    detector=self.detector,
                    flagged=not decision.outcome.permits_action,
                    action_tool=tool_name,
                    action_class=decision.category.value,
                    decision=decision.outcome.value,
                    decision_reasons=list(decision.reasons),
                    degraded=decision.detector_degraded,
                    parent_scan_id=parent,
                    versions=self.versions(),
                )
            )
        return decision
