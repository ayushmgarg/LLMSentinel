"""``llmsentinel history ...`` and ``llmsentinel manifests ...`` commands.

    llmsentinel history list [filters]          scans, newest first
    llmsentinel history queue                   uncertain scans nobody has reviewed yet
    llmsentinel history show SCAN_ID            one scan, its overrides and effective label
    llmsentinel history override SCAN_ID ...    record a reviewer label with a rationale
    llmsentinel history stats --by KEY          aggregate by tool, server, source domain, family, ...
    llmsentinel history promote SCAN_ID ...     turn a reviewed case into a regression fixture
    llmsentinel manifests check FILE --server   scan a manifest and raise drift alerts
    llmsentinel manifests approve FILE ...      pin the current declarations as approved
    llmsentinel manifests alerts                open manifest alerts
    llmsentinel manifests ack ALERT_ID ...      acknowledge an alert (it stays in the history)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..paths import relative
from .fixtures import DISCOVERED_PATH, promote_to_fixture
from .store import LABELS, STATS_KEYS, ScanFilter, ScanRecord, ScanStore

__all__ = ["register_analyst_commands"]


def _safe(text: Any) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _yes_no(value: str | None) -> bool | None:
    return None if value is None else value == "yes"


def _store(args: argparse.Namespace) -> ScanStore:
    return ScanStore(args.history) if args.history else ScanStore()


def _filters(args: argparse.Namespace) -> ScanFilter:
    return ScanFilter(
        kind=args.kind,
        channel=args.channel,
        tool=args.tool,
        server=args.server,
        source_domain=args.source_domain,
        family=args.family,
        action_class=args.action_class,
        decision=args.decision,
        band=args.band,
        flagged=_yes_no(args.flagged),
        reviewed=_yes_no(args.reviewed),
        since=args.since,
    )


def _row(record: ScanRecord) -> str:
    where = record.tool or record.source or record.channel or "-"
    call = "FLAG" if record.flagged else "ok  "
    what = record.decision or record.band or "-"
    families = ",".join(record.families) or "-"
    return _safe(f"{record.scan_id[:12]}  {record.created_at}  {record.kind:<8} {call} risk {record.risk:.3f} {what:<9} {families:<28} {where}")


def _print_records(records: list[ScanRecord], as_json: bool) -> None:
    if as_json:
        print(json.dumps([record.to_dict() for record in records], indent=2))
        return
    if not records:
        print("(no scans)")
    for record in records:
        print(_row(record))
        for reason in record.review_reasons[:3]:
            print(_safe(f"    review: {reason}"))


def _resolve(store: ScanStore, scan_id: str) -> str:
    if store.get(scan_id):
        return scan_id
    matches = [r.scan_id for r in store.list(limit=1000) if r.scan_id.startswith(scan_id)]
    if len(matches) != 1:
        raise SystemExit(f"error: {'no' if not matches else 'ambiguous'} scan id {scan_id!r}")
    return matches[0]


# -------------------------------------------------------------- history
def cmd_history_list(args: argparse.Namespace) -> int:
    _print_records(_store(args).list(_filters(args), limit=args.limit), args.json)
    return 0


def cmd_history_queue(args: argparse.Namespace) -> int:
    _print_records(_store(args).queue(_filters(args), limit=args.limit), args.json)
    return 0


def cmd_history_show(args: argparse.Namespace) -> int:
    store = _store(args)
    scan_id = _resolve(store, args.scan_id)
    record = store.get(scan_id)
    payload = {
        "scan": record.to_dict(),
        "overrides": [item.to_dict() for item in store.overrides(scan_id)],
        "effective_label": store.effective_label(scan_id),
    }
    print(_safe(json.dumps(payload, indent=2)))
    return 0


def cmd_history_override(args: argparse.Namespace) -> int:
    store = _store(args)
    scan_id = _resolve(store, args.scan_id)
    try:
        item = store.override(scan_id, label=args.label, reviewer=args.reviewer, rationale=args.rationale)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    record = store.get(scan_id)
    print(f"override {item.override_id[:12]}: {scan_id[:12]} detector said "
          f"{'injection' if record.flagged else 'benign'}, reviewer {item.reviewer} says {item.label}")
    print("the original verdict is kept unchanged in the history")
    return 0


def cmd_history_stats(args: argparse.Namespace) -> int:
    rows = _store(args).stats(args.by, _filters(args), limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{args.by:<32} {'scans':>6} {'flagged':>8} {'rate':>6} {'mean':>6} {'max':>6} {'reviewed':>9}")
    for row in rows:
        print(_safe(f"{str(row['key'])[:32]:<32} {row['scans']:>6} {row['flagged']:>8} {row['flagged_rate']:>6.2f} "
                    f"{row['mean_risk']:>6.3f} {row['max_risk']:>6.3f} {row['reviewed']:>9}"))
    return 0


def cmd_history_promote(args: argparse.Namespace) -> int:
    store = _store(args)
    scan_id = _resolve(store, args.scan_id)
    try:
        fixture = promote_to_fixture(store, scan_id, promoted_by=args.by, path=Path(args.path))
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}")
        return 2
    print(f"fixture {fixture['id']} ({fixture['label']}) appended to {relative(args.path)}")
    for change in fixture["sanitisation"]:
        print(_safe(f"    sanitised: {change}"))
    return 0


# ------------------------------------------------------------ manifests
def _load_tools(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tools = data.get("tools") if isinstance(data, dict) else data
    if not isinstance(tools, list) or not all(isinstance(t, dict) and t.get("name") for t in tools):
        raise SystemExit(f"error: {path} must hold a list of tools, or an object with a 'tools' list")
    return tools


def cmd_manifests_check(args: argparse.Namespace) -> int:
    from ..sdk import Sentinel

    store = _store(args)
    sentinel = Sentinel(detector=args.detector, store=store)
    scan = sentinel.scan_manifest(_load_tools(args.file), server=args.server, source=args.file)
    print(f"detector: {sentinel.detector}")
    for tool in scan.tools:
        state = "QUARANTINED" if tool.quarantined else "trusted"
        print(_safe(f"  {tool.name:<28} {state:<12} risk {tool.fields.risk:.3f} drift {tool.drift or '-'}"))
        for reason in tool.reasons:
            print(_safe(f"      {reason}"))
    for alert in scan.alerts:
        print(_safe(f"  alert {alert.alert_id[:12]}: {alert.describe()}"))
    return 1 if scan.quarantined else 0


def cmd_manifests_approve(args: argparse.Namespace) -> int:
    pinned = _store(args).approve_manifest(args.server, _load_tools(args.file), approved_by=args.by)
    print(f"approved {len(pinned)} tool(s) on {args.server} as reviewed by {args.by}")
    return 0


def cmd_manifests_alerts(args: argparse.Namespace) -> int:
    alerts = _store(args).open_alerts(args.server)
    if args.json:
        print(json.dumps([alert.to_dict() for alert in alerts], indent=2))
        return 0
    if not alerts:
        print("(no open alerts)")
    for alert in alerts:
        print(_safe(f"{alert.alert_id[:12]}  {alert.created_at}  {alert.kind:<10} {alert.describe()}"))
    return 0


def cmd_manifests_ack(args: argparse.Namespace) -> int:
    store = _store(args)
    matches = [a.alert_id for a in store.open_alerts() if a.alert_id.startswith(args.alert_id)]
    if len(matches) != 1:
        print(f"error: {'no open' if not matches else 'ambiguous'} alert {args.alert_id!r}")
        return 2
    store.acknowledge(matches[0], acknowledged_by=args.by, note=args.note)
    print(f"acknowledged {matches[0][:12]}; the alert stays in the history")
    return 0


# ------------------------------------------------------------- register
def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", choices=["content", "manifest", "action"])
    parser.add_argument("--channel")
    parser.add_argument("--tool")
    parser.add_argument("--server")
    parser.add_argument("--source-domain")
    parser.add_argument("--family", help="predicted attack family, e.g. exfiltration")
    parser.add_argument("--action-class", help="e.g. external_send, destructive")
    parser.add_argument("--decision", choices=["allow", "isolate", "confirm", "block"])
    parser.add_argument("--band", choices=["low", "elevated", "high"])
    parser.add_argument("--flagged", choices=["yes", "no"])
    parser.add_argument("--reviewed", choices=["yes", "no"])
    parser.add_argument("--since", help="ISO timestamp, e.g. 2026-09-01")


def register_analyst_commands(sub: Any) -> None:
    history_path = argparse.ArgumentParser(add_help=False)
    history_path.add_argument("--history", default=None, help="history database (default: artifacts/analyst/history.sqlite3)")

    history = sub.add_parser("history", help="analyst scan history, review queue and overrides")
    hsub = history.add_subparsers(dest="history_command", required=True)

    listing = hsub.add_parser("list", parents=[history_path], help="scans, newest first")
    _add_filters(listing)
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_history_list)

    queue = hsub.add_parser("queue", parents=[history_path], help="uncertain scans awaiting review")
    _add_filters(queue)
    queue.add_argument("--limit", type=int, default=50)
    queue.add_argument("--json", action="store_true")
    queue.set_defaults(func=cmd_history_queue)

    show = hsub.add_parser("show", parents=[history_path], help="one scan with its overrides")
    show.add_argument("scan_id")
    show.set_defaults(func=cmd_history_show)

    override = hsub.add_parser("override", parents=[history_path], help="record a reviewer label (append-only)")
    override.add_argument("scan_id")
    override.add_argument("--label", required=True, choices=list(LABELS))
    override.add_argument("--reviewer", required=True)
    override.add_argument("--rationale", required=True)
    override.set_defaults(func=cmd_history_override)

    stats = hsub.add_parser("stats", parents=[history_path], help="aggregate scans")
    stats.add_argument("--by", required=True, choices=sorted(STATS_KEYS))
    _add_filters(stats)
    stats.add_argument("--limit", type=int, default=50)
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=cmd_history_stats)

    promote = hsub.add_parser("promote", parents=[history_path], help="reviewed scan -> regression fixture")
    promote.add_argument("scan_id")
    promote.add_argument("--by", required=True)
    promote.add_argument("--path", default=str(DISCOVERED_PATH))
    promote.set_defaults(func=cmd_history_promote)

    manifests = sub.add_parser("manifests", help="MCP manifest approval and change alerts")
    msub = manifests.add_subparsers(dest="manifests_command", required=True)

    check = msub.add_parser("check", parents=[history_path], help="scan a manifest and raise alerts")
    check.add_argument("file")
    check.add_argument("--server", required=True)
    check.add_argument("--detector", default="rules", choices=["auto", "rules", "transformer"])
    check.set_defaults(func=cmd_manifests_check)

    approve = msub.add_parser("approve", parents=[history_path], help="pin current declarations as approved")
    approve.add_argument("file")
    approve.add_argument("--server", required=True)
    approve.add_argument("--by", required=True)
    approve.set_defaults(func=cmd_manifests_approve)

    alerts = msub.add_parser("alerts", parents=[history_path], help="open manifest alerts")
    alerts.add_argument("--server", default=None)
    alerts.add_argument("--json", action="store_true")
    alerts.set_defaults(func=cmd_manifests_alerts)

    ack = msub.add_parser("ack", parents=[history_path], help="acknowledge an alert")
    ack.add_argument("alert_id")
    ack.add_argument("--by", required=True)
    ack.add_argument("--note", default="")
    ack.set_defaults(func=cmd_manifests_ack)
