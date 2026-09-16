"""Local scan history: what was scanned, what the guard concluded, what a reviewer decided.

Design rules, each tied to a checklist section 17 requirement:

* **The original verdict is never rewritten.** Scan rows are insert-only, enforced by
  SQLite triggers rather than by convention. A reviewer's disagreement is a separate,
  append-only override with a mandatory rationale, and the effective label is read
  from the latest override. The detector's call stays auditable beside the human one.
* **Nothing is deleted.** The same triggers refuse deletes on scans, overrides, pins,
  alerts and acknowledgements. History only grows.
* **Every row names the system that produced it** (package, normalisation, rule set,
  policy and threshold source), so a verdict can be traced to its versions.
* **Local only.** A SQLite file under ``artifacts/analyst/`` (gitignored) or wherever
  ``LLMSENTINEL_HISTORY`` points. Full text is kept by default so reviewed cases can
  become regression fixtures; ``store_text=False`` keeps only a digest and an excerpt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..paths import ARTIFACTS_DIR
from ..rules.metadata import manifest_hash

__all__ = [
    "DEFAULT_HISTORY_PATH",
    "LABELS",
    "MIN_RATIONALE_CHARS",
    "STATS_KEYS",
    "Alert",
    "Override",
    "ScanFilter",
    "ScanRecord",
    "ScanStore",
    "source_domain_of",
]

DEFAULT_HISTORY_PATH = ARTIFACTS_DIR / "analyst" / "history.sqlite3"
SCHEMA_VERSION = 1
LABELS = ("injection", "benign")
KINDS = ("content", "manifest", "action")
ALERT_KINDS = ("unapproved", "changed", "added", "removed")
#: A rationale shorter than this is a label, not a reason; the audit trail needs a reason.
MIN_RATIONALE_CHARS = 15
EXCERPT_CHARS = 400

#: Aggregation keys and the column each groups by.
STATS_KEYS: dict[str, str] = {
    "tool": "s.tool",
    "server": "s.server",
    "source": "s.source",
    "source_domain": "s.source_domain",
    "channel": "s.channel",
    "family": "f.family",
    "action_class": "s.action_class",
    "decision": "s.decision",
    "band": "s.band",
    "kind": "s.kind",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('content', 'manifest', 'action')),
    parent_scan_id TEXT,
    source TEXT,
    source_domain TEXT,
    server TEXT,
    tool TEXT,
    channel TEXT,
    json_path TEXT,
    host_task TEXT,
    text TEXT,
    text_sha256 TEXT,
    excerpt TEXT,
    risk REAL NOT NULL DEFAULT 0,
    band TEXT,
    rule_score REAL,
    model_score REAL,
    detector TEXT,
    decided_by TEXT,
    thresholds TEXT NOT NULL DEFAULT '{}',
    flagged INTEGER NOT NULL DEFAULT 0,
    rule_trace TEXT NOT NULL DEFAULT '[]',
    spans TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    degraded INTEGER NOT NULL DEFAULT 0,
    drift TEXT,
    action_tool TEXT,
    action_class TEXT,
    decision TEXT,
    decision_reasons TEXT NOT NULL DEFAULT '[]',
    review_reasons TEXT NOT NULL DEFAULT '[]',
    versions TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS scans_created ON scans (created_at);
CREATE INDEX IF NOT EXISTS scans_tool ON scans (tool);
CREATE INDEX IF NOT EXISTS scans_server ON scans (server);

CREATE TABLE IF NOT EXISTS scan_families (
    scan_id TEXT NOT NULL REFERENCES scans (scan_id),
    family TEXT NOT NULL,
    PRIMARY KEY (scan_id, family)
);

CREATE TABLE IF NOT EXISTS overrides (
    override_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans (scan_id),
    created_at TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('injection', 'benign')),
    rationale TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS overrides_scan ON overrides (scan_id);

CREATE TABLE IF NOT EXISTS pins (
    pin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    digest TEXT,
    declaration TEXT,
    approved_at TEXT NOT NULL,
    approved_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('unapproved', 'changed', 'added', 'removed')),
    approved_digest TEXT,
    live_digest TEXT,
    scan_id TEXT
);

CREATE TABLE IF NOT EXISTS alert_acks (
    alert_id TEXT NOT NULL REFERENCES alerts (alert_id),
    created_at TEXT NOT NULL,
    acknowledged_by TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
"""

_IMMUTABLE_TABLES = ("scans", "scan_families", "overrides", "pins", "alerts", "alert_acks")


def _triggers() -> str:
    statements = []
    for table in _IMMUTABLE_TABLES:
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'analyst history is append-only: {table} rows cannot be deleted'); END;"
        )
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'analyst history is append-only: {table} rows cannot be changed'); END;"
        )
    return "\n".join(statements)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_domain_of(source: str | None) -> str | None:
    """Host of a URL or e-mail source; ``None`` for file names and tool labels."""

    if not source:
        return None
    text = source.strip()
    if "://" in text:
        host = urlparse(text).hostname
        return host.lower() if host else None
    if "@" in text and " " not in text:
        return text.rsplit("@", 1)[1].lower() or None
    return None


# ------------------------------------------------------------------ records
@dataclass(slots=True)
class ScanRecord:
    """One scanned unit (or one gated action) as it was decided at the time."""

    kind: str = "content"
    source: str | None = None
    server: str | None = None
    tool: str | None = None
    channel: str | None = None
    json_path: str | None = None
    host_task: str | None = None
    text: str | None = None
    risk: float = 0.0
    band: str | None = None
    rule_score: float | None = None
    model_score: float | None = None
    detector: str | None = None
    decided_by: str | None = None
    thresholds: dict[str, float] = field(default_factory=dict)
    flagged: bool = False
    rule_trace: list[str] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    degraded: bool = False
    drift: str | None = None
    action_tool: str | None = None
    action_class: str | None = None
    decision: str | None = None
    decision_reasons: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    versions: dict[str, Any] = field(default_factory=dict)
    parent_scan_id: str | None = None
    # Filled in by the store.
    scan_id: str | None = None
    created_at: str | None = None
    source_domain: str | None = None
    text_sha256: str | None = None
    excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Override:
    override_id: str
    scan_id: str
    created_at: str
    reviewer: str
    label: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Alert:
    alert_id: str
    created_at: str
    server: str
    tool: str
    kind: str
    approved_digest: str | None
    live_digest: str | None
    scan_id: str | None
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        return {
            "unapproved": f"{self.server}/{self.tool} has never been approved",
            "changed": f"{self.server}/{self.tool} changed after approval",
            "added": f"{self.server}/{self.tool} is new since the server was approved",
            "removed": f"{self.server}/{self.tool} was removed since approval",
        }[self.kind]


@dataclass(slots=True)
class ScanFilter:
    """Filters for history, queue and statistics. ``None`` means "any"."""

    kind: str | None = None
    channel: str | None = None
    tool: str | None = None
    server: str | None = None
    source: str | None = None
    source_domain: str | None = None
    family: str | None = None
    action_class: str | None = None
    decision: str | None = None
    band: str | None = None
    flagged: bool | None = None
    reviewed: bool | None = None
    since: str | None = None

    _COLUMNS = ("kind", "channel", "tool", "server", "source", "source_domain", "action_class", "decision", "band")

    def where(self) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for name in self._COLUMNS:
            value = getattr(self, name)
            if value not in (None, ""):
                clauses.append(f"s.{name} = ?")
                params.append(value)
        if self.family:
            clauses.append("EXISTS (SELECT 1 FROM scan_families f2 WHERE f2.scan_id = s.scan_id AND f2.family = ?)")
            params.append(self.family)
        if self.flagged is not None:
            clauses.append("s.flagged = ?")
            params.append(int(self.flagged))
        if self.reviewed is not None:
            clauses.append(("" if self.reviewed else "NOT ") + "EXISTS (SELECT 1 FROM overrides o WHERE o.scan_id = s.scan_id)")
        if self.since:
            clauses.append("s.created_at >= ?")
            params.append(self.since)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


# -------------------------------------------------------------------- store
class ScanStore:
    """SQLite-backed, append-only analyst history."""

    def __init__(self, path: str | Path | None = None, *, store_text: bool = True) -> None:
        env = os.environ.get("LLMSENTINEL_HISTORY")
        self.path = Path(path) if path else Path(env) if env else DEFAULT_HISTORY_PATH
        self.store_text = store_text
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.executescript(_triggers())
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- scans
    def add(self, record: ScanRecord) -> ScanRecord:
        if record.kind not in KINDS:
            raise ValueError(f"unknown scan kind {record.kind!r}")
        record.scan_id = record.scan_id or uuid.uuid4().hex
        record.created_at = record.created_at or _now()
        record.source_domain = record.source_domain or source_domain_of(record.source)
        if record.text is not None:
            record.text_sha256 = hashlib.sha256(record.text.encode("utf-8")).hexdigest()
            record.excerpt = " ".join(record.text.split())[:EXCERPT_CHARS]
        stored_text = record.text if self.store_text else None
        row = {
            "scan_id": record.scan_id,
            "created_at": record.created_at,
            "kind": record.kind,
            "parent_scan_id": record.parent_scan_id,
            "source": record.source,
            "source_domain": record.source_domain,
            "server": record.server,
            "tool": record.tool,
            "channel": record.channel,
            "json_path": record.json_path,
            "host_task": record.host_task,
            "text": stored_text,
            "text_sha256": record.text_sha256,
            "excerpt": record.excerpt,
            "risk": float(record.risk),
            "band": record.band,
            "rule_score": record.rule_score,
            "model_score": record.model_score,
            "detector": record.detector,
            "decided_by": record.decided_by,
            "thresholds": json.dumps(record.thresholds),
            "flagged": int(bool(record.flagged)),
            "rule_trace": json.dumps(record.rule_trace),
            "spans": json.dumps(record.spans),
            "evidence": json.dumps(record.evidence),
            "degraded": int(bool(record.degraded)),
            "drift": record.drift,
            "action_tool": record.action_tool,
            "action_class": record.action_class,
            "decision": record.decision,
            "decision_reasons": json.dumps(record.decision_reasons),
            "review_reasons": json.dumps(record.review_reasons),
            "versions": json.dumps(record.versions, sort_keys=True),
        }
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock, self._conn:
            self._conn.execute(f"INSERT INTO scans ({columns}) VALUES ({marks})", list(row.values()))
            self._conn.executemany(
                "INSERT INTO scan_families (scan_id, family) VALUES (?, ?)",
                [(record.scan_id, family) for family in sorted(set(record.families))],
            )
        if not self.store_text:
            record.text = None
        return record

    def add_many(self, records: Iterable[ScanRecord]) -> list[ScanRecord]:
        return [self.add(record) for record in records]

    def _families(self, scan_ids: Sequence[str]) -> dict[str, list[str]]:
        if not scan_ids:
            return {}
        marks = ", ".join("?" for _ in scan_ids)
        rows = self._conn.execute(
            f"SELECT scan_id, family FROM scan_families WHERE scan_id IN ({marks}) ORDER BY family", list(scan_ids)
        ).fetchall()
        out: dict[str, list[str]] = {}
        for row in rows:
            out.setdefault(row["scan_id"], []).append(row["family"])
        return out

    def _records(self, rows: Sequence[sqlite3.Row]) -> list[ScanRecord]:
        families = self._families([row["scan_id"] for row in rows])
        records = []
        for row in rows:
            data = dict(row)
            for key in ("thresholds", "rule_trace", "spans", "evidence", "decision_reasons", "review_reasons", "versions"):
                data[key] = json.loads(data[key]) if data.get(key) else ({} if key in ("thresholds", "versions") else [])
            data["flagged"] = bool(data["flagged"])
            data["degraded"] = bool(data["degraded"])
            data["families"] = families.get(row["scan_id"], [])
            records.append(ScanRecord(**data))
        return records

    def get(self, scan_id: str) -> ScanRecord | None:
        rows = self._conn.execute("SELECT * FROM scans s WHERE s.scan_id = ?", (scan_id,)).fetchall()
        return self._records(rows)[0] if rows else None

    def list(self, filters: ScanFilter | None = None, *, limit: int = 100, offset: int = 0) -> list[ScanRecord]:
        where, params = (filters or ScanFilter()).where()
        rows = self._conn.execute(
            f"SELECT * FROM scans s{where} ORDER BY s.created_at DESC, s.rowid DESC LIMIT ? OFFSET ?",
            [*params, max(1, min(int(limit), 1000)), max(0, int(offset))],
        ).fetchall()
        return self._records(rows)

    def count(self, filters: ScanFilter | None = None) -> int:
        where, params = (filters or ScanFilter()).where()
        return int(self._conn.execute(f"SELECT COUNT(*) FROM scans s{where}", params).fetchone()[0])

    def queue(self, filters: ScanFilter | None = None, *, limit: int = 100) -> list[ScanRecord]:
        """Scans with review reasons that no reviewer has resolved yet, riskiest first."""

        base = filters or ScanFilter()
        where, params = ScanFilter(**{**asdict(base), "reviewed": False}).where()
        joiner = " AND " if where else " WHERE "
        rows = self._conn.execute(
            f"SELECT * FROM scans s{where}{joiner}s.review_reasons != '[]' "
            "ORDER BY s.risk DESC, s.created_at DESC LIMIT ?",
            [*params, max(1, min(int(limit), 1000))],
        ).fetchall()
        return self._records(rows)

    # --------------------------------------------------------- overrides
    def override(self, scan_id: str, *, label: str, reviewer: str, rationale: str) -> Override:
        if self.get(scan_id) is None:
            raise KeyError(f"no scan {scan_id!r}")
        if label not in LABELS:
            raise ValueError(f"label must be one of {LABELS}")
        if not reviewer.strip():
            raise ValueError("a reviewer name is required")
        if len(rationale.strip()) < MIN_RATIONALE_CHARS:
            raise ValueError(f"a rationale of at least {MIN_RATIONALE_CHARS} characters is required")
        item = Override(uuid.uuid4().hex, scan_id, _now(), reviewer.strip(), label, rationale.strip())
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO overrides (override_id, scan_id, created_at, reviewer, label, rationale) VALUES (?, ?, ?, ?, ?, ?)",
                (item.override_id, item.scan_id, item.created_at, item.reviewer, item.label, item.rationale),
            )
        return item

    def overrides(self, scan_id: str) -> list[Override]:
        rows = self._conn.execute(
            "SELECT * FROM overrides WHERE scan_id = ? ORDER BY created_at, rowid", (scan_id,)
        ).fetchall()
        return [Override(**dict(row)) for row in rows]

    def effective_label(self, scan_id: str) -> str:
        """The latest reviewer label if there is one, else the detector's own call."""

        history = self.overrides(scan_id)
        if history:
            return history[-1].label
        record = self.get(scan_id)
        if record is None:
            raise KeyError(f"no scan {scan_id!r}")
        return "injection" if record.flagged else "benign"

    # -------------------------------------------------------- statistics
    def stats(self, by: str, filters: ScanFilter | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        if by not in STATS_KEYS:
            raise ValueError(f"cannot aggregate by {by!r}; choose from {sorted(STATS_KEYS)}")
        where, params = (filters or ScanFilter()).where()
        join = " JOIN scan_families f ON f.scan_id = s.scan_id" if by == "family" else ""
        rows = self._conn.execute(
            f"SELECT {STATS_KEYS[by]} AS key, COUNT(*) AS scans, SUM(s.flagged) AS flagged, "
            "AVG(s.risk) AS mean_risk, MAX(s.risk) AS max_risk, "
            "SUM(CASE WHEN EXISTS (SELECT 1 FROM overrides o WHERE o.scan_id = s.scan_id) THEN 1 ELSE 0 END) AS reviewed "
            f"FROM scans s{join}{where} GROUP BY key ORDER BY flagged DESC, scans DESC LIMIT ?",
            [*params, max(1, min(int(limit), 500))],
        ).fetchall()
        out = []
        for row in rows:
            scans = int(row["scans"])
            flagged = int(row["flagged"] or 0)
            out.append(
                {
                    "key": row["key"] if row["key"] is not None else "(none)",
                    "scans": scans,
                    "flagged": flagged,
                    "flagged_rate": round(flagged / scans, 4) if scans else 0.0,
                    "mean_risk": round(float(row["mean_risk"] or 0.0), 4),
                    "max_risk": round(float(row["max_risk"] or 0.0), 4),
                    "reviewed": int(row["reviewed"] or 0),
                }
            )
        return out

    def summary(self) -> dict[str, int]:
        return {
            "scans": self.count(),
            "flagged": self.count(ScanFilter(flagged=True)),
            "queued": len(self.queue(limit=1000)),
            "reviewed": self.count(ScanFilter(reviewed=True)),
            "open_alerts": len(self.open_alerts()),
        }

    # ----------------------------------------------- manifest pins/alerts
    def current_pins(self, server: str) -> dict[str, dict[str, Any]]:
        """The latest approval per tool for ``server`` (removed tools excluded)."""

        rows = self._conn.execute(
            "SELECT p.* FROM pins p JOIN (SELECT tool, MAX(pin_id) AS latest FROM pins WHERE server = ? GROUP BY tool) m "
            "ON p.pin_id = m.latest",
            (server,),
        ).fetchall()
        return {
            row["tool"]: {
                "digest": row["digest"],
                "declaration": json.loads(row["declaration"]) if row["declaration"] else None,
                "approved_at": row["approved_at"],
                "approved_by": row["approved_by"],
            }
            for row in rows
            if row["digest"] is not None
        }

    def is_pinned(self, server: str) -> bool:
        return bool(self._conn.execute("SELECT 1 FROM pins WHERE server = ? LIMIT 1", (server,)).fetchone())

    def approve_manifest(self, server: str, tools: Sequence[dict[str, Any]], *, approved_by: str) -> dict[str, str]:
        """Pin the current declaration of every tool; tools no longer present are recorded as removed."""

        if not approved_by.strip():
            raise ValueError("approved_by is required")
        now = _now()
        live = {str(tool["name"]): tool for tool in tools}
        previous = self.current_pins(server)
        pinned: dict[str, str] = {}
        with self._lock, self._conn:
            for name, tool in live.items():
                digest = manifest_hash(tool)
                pinned[name] = digest
                self._conn.execute(
                    "INSERT INTO pins (server, tool, digest, declaration, approved_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                    (server, name, digest, json.dumps(tool, sort_keys=True), now, approved_by.strip()),
                )
            for name in sorted(set(previous) - set(live)):
                self._conn.execute(
                    "INSERT INTO pins (server, tool, digest, declaration, approved_at, approved_by) VALUES (?, ?, NULL, NULL, ?, ?)",
                    (server, name, now, approved_by.strip()),
                )
        return pinned

    def check_manifest(self, server: str, tools: Sequence[dict[str, Any]], *, scan_id: str | None = None) -> list[Alert]:
        """Compare a live manifest with the pins; raise one alert per new discrepancy.

        An alert already open for the same tool, kind and live digest is not raised
        again, so repeated scans of an unchanged manifest do not flood the queue.
        """

        pins = self.current_pins(server)
        pinned_server = self.is_pinned(server)
        findings: list[tuple[str, str, str | None, str | None]] = []
        live = {str(tool["name"]): manifest_hash(tool) for tool in tools}
        for name, digest in live.items():
            if not pinned_server:
                findings.append((name, "unapproved", None, digest))
            elif name not in pins:
                findings.append((name, "added", None, digest))
            elif pins[name]["digest"] != digest:
                findings.append((name, "changed", pins[name]["digest"], digest))
        for name in sorted(set(pins) - set(live)):
            findings.append((name, "removed", pins[name]["digest"], None))

        open_keys = {(a.tool, a.kind, a.live_digest) for a in self.open_alerts(server)}
        raised: list[Alert] = []
        with self._lock, self._conn:
            for name, kind, approved, live_digest in findings:
                if (name, kind, live_digest) in open_keys:
                    continue
                alert = Alert(uuid.uuid4().hex, _now(), server, name, kind, approved, live_digest, scan_id)
                self._conn.execute(
                    "INSERT INTO alerts (alert_id, created_at, server, tool, kind, approved_digest, live_digest, scan_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (alert.alert_id, alert.created_at, server, name, kind, approved, live_digest, scan_id),
                )
                raised.append(alert)
        return raised

    def open_alerts(self, server: str | None = None) -> list[Alert]:
        where = "WHERE NOT EXISTS (SELECT 1 FROM alert_acks k WHERE k.alert_id = a.alert_id)"
        params: list[Any] = []
        if server:
            where += " AND a.server = ?"
            params.append(server)
        rows = self._conn.execute(f"SELECT a.* FROM alerts a {where} ORDER BY a.created_at DESC, a.rowid DESC", params).fetchall()
        return [Alert(**dict(row)) for row in rows]

    def acknowledge(self, alert_id: str, *, acknowledged_by: str, note: str = "") -> None:
        if not acknowledged_by.strip():
            raise ValueError("acknowledged_by is required")
        if not self._conn.execute("SELECT 1 FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone():
            raise KeyError(f"no alert {alert_id!r}")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO alert_acks (alert_id, created_at, acknowledged_by, note) VALUES (?, ?, ?, ?)",
                (alert_id, _now(), acknowledged_by.strip(), note.strip()),
            )
