"""Turn a reviewed scan into a regression fixture, safely.

A case an analyst has confirmed is the most valuable test data the project can get:
it is real traffic, labelled by a human. It is also the most dangerous to commit,
because it may carry a working destination or a live credential. Promotion is
therefore gated and sanitised:

* only a scan with a reviewer override can be promoted, and the fixture's label is
  that reviewer's label, never the detector's own call;
* every non-reserved host in a URL or e-mail address is rewritten to a reserved
  ``.invalid`` name (RFC 6761), and secret-shaped tokens are replaced by a marker;
* the rules-only score of the *sanitised* text is recorded, and
  ``tests/test_regression_fixtures.py`` fails if a later change makes an injection
  score lower, or a benign case score higher, than it did when it was promoted.

Fixtures are appended; an existing fixture is never rewritten or removed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import __version__
from ..paths import DATA_DIR
from ..rules import RuleEngine
from .store import ScanStore

__all__ = ["DISCOVERED_PATH", "SCORE_TOLERANCE", "load_fixtures", "promote_to_fixture", "sanitise_for_fixture"]

DISCOVERED_PATH = DATA_DIR / "regression" / "discovered.yaml"
#: How far a fixture's rules-only score may move before the regression test fails.
SCORE_TOLERANCE = 0.05
SECRET_MARKER = "[REDACTED-SECRET]"

_RESERVED_SUFFIXES = (".invalid", ".test", ".example", ".localhost")
_RESERVED_HOSTS = ("example.com", "example.net", "example.org", "localhost")
_URL_HOST = re.compile(r"(?P<scheme>\bhttps?://)(?P<host>[A-Za-z0-9.-]+)", re.IGNORECASE)
_EMAIL = re.compile(r"\b(?P<user>[\w.+-]+)@(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b")
_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,})\b"
)
#: Secret-shaped tokens; shared with the output-side check.
SECRET_PATTERN = _SECRET


def _reserved(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host in _RESERVED_HOSTS or host.endswith(_RESERVED_SUFFIXES) or any(
        host.endswith("." + reserved) for reserved in _RESERVED_HOSTS
    )


def _neutral_host(host: str) -> str:
    label = re.sub(r"[^a-z0-9-]", "-", host.lower().split(".")[0]) or "host"
    return f"{label}.attacker.invalid"


def sanitise_for_fixture(text: str) -> tuple[str, list[str]]:
    """Return sanitised text and a list of what was changed."""

    changes: list[str] = []

    def secret(match: re.Match[str]) -> str:
        changes.append("redacted a secret-shaped token")
        return SECRET_MARKER

    def url(match: re.Match[str]) -> str:
        host = match.group("host")
        if _reserved(host):
            return match.group(0)
        replacement = _neutral_host(host)
        changes.append(f"rewrote URL host {host} -> {replacement}")
        return match.group("scheme") + replacement

    def email(match: re.Match[str]) -> str:
        host = match.group("host")
        if _reserved(host):
            return match.group(0)
        replacement = _neutral_host(host)
        changes.append(f"rewrote e-mail host {host} -> {replacement}")
        return f"{match.group('user')}@{replacement}"

    cleaned = _SECRET.sub(secret, text)
    cleaned = _URL_HOST.sub(url, cleaned)
    cleaned = _EMAIL.sub(email, cleaned)
    return cleaned, changes


def load_fixtures(path: str | Path = DISCOVERED_PATH) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fixtures = data.get("fixtures") or []
    if not isinstance(fixtures, list):
        raise ValueError(f"{path}: 'fixtures' must be a list")
    return fixtures


def promote_to_fixture(
    store: ScanStore,
    scan_id: str,
    *,
    promoted_by: str,
    path: str | Path = DISCOVERED_PATH,
    engine: RuleEngine | None = None,
) -> dict[str, Any]:
    """Append a sanitised, reviewer-labelled fixture for ``scan_id`` and return it."""

    record = store.get(scan_id)
    if record is None:
        raise KeyError(f"no scan {scan_id!r}")
    if record.kind != "content":
        raise ValueError("only content scans (documents, tool results, tool metadata) can become fixtures")
    if not record.text:
        raise ValueError("this scan was stored without its text (store_text=False), so it cannot become a fixture")
    history = store.overrides(scan_id)
    if not history:
        raise ValueError("promote only reviewed cases: add an override with a label and rationale first")
    if not promoted_by.strip():
        raise ValueError("promoted_by is required")

    path = Path(path)
    existing = load_fixtures(path)
    fixture_id = f"discovered-{scan_id[:12]}"
    if any(item.get("id") == fixture_id for item in existing):
        raise ValueError(f"{fixture_id} is already a fixture; fixtures are never rewritten")

    text, changes = sanitise_for_fixture(record.text)
    channel = record.channel or "rag_document"
    engine = engine or RuleEngine()
    _, report = engine.analyse_text(text, channel=channel)
    latest = history[-1]
    fixture = {
        "id": fixture_id,
        "label": latest.label,
        "channel": channel,
        "json_path": record.json_path,
        "text": text,
        "rule_score": round(float(report.score), 4),
        "tolerance": SCORE_TOLERANCE,
        "detector_flagged": record.flagged,
        "reviewer": latest.reviewer,
        "rationale": latest.rationale,
        "promoted_by": promoted_by.strip(),
        "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_scan_id": scan_id,
        "sanitisation": changes,
        "versions": {"llmsentinel": __version__, "rules": sorted(rule.rule_id for rule in engine.rules)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Regression fixtures promoted from reviewed analyst cases (append-only).\n"
        "# Written by llmsentinel.analyst.fixtures.promote_to_fixture; text is sanitised\n"
        "# (reserved .invalid hosts, secrets redacted). Checked by\n"
        "# tests/test_regression_fixtures.py.\n"
    )
    body = yaml.safe_dump({"fixtures": [*existing, fixture]}, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body, encoding="utf-8")
    return fixture
