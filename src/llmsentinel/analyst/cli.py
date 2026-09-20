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
    llmsentinel rules propose                   mine candidate rules from reviewed/unexplained cases
    llmsentinel rules proposals                 list candidates and their review state
    llmsentinel rules approve ID ... | reject   decide a candidate (advisory only, never auto-enabled)
    llmsentinel rules check --text ...          run the approved candidates as a second opinion
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..paths import CORPUS_PATH, relative
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


# ------------------------------------------------------- candidate rules
def cmd_rules_propose(args: argparse.Namespace) -> int:
    from .proposals import evaluate_candidates, mine_candidates, write_proposals

    candidates = mine_candidates(
        _store(args),
        limit=args.limit,
        min_support=args.min_support,
        max_candidates=args.max_candidates,
    )
    if not candidates:
        print("no candidates: nothing in the history is both unexplained by the rules and repeated")
        return 0
    candidates = evaluate_candidates(candidates, corpus_path=args.corpus)
    for candidate in candidates:
        dev = candidate.dev
        summary = (
            f"dev: {dev.get('injections_matched')} injections / {dev.get('benign_matched')} benign"
            f", {dev.get('injections_missed_by_rules_now')} the rules miss now"
            if dev.get("available")
            else f"dev: {dev.get('reason')}"
        )
        print(_safe(f"{candidate.candidate_id}  support {candidate.support}  [{candidate.family}] "
                    f"\"{candidate.phrase}\"  {summary}"))
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    added, skipped = write_proposals(candidates, path=args.path)
    print(f"{len(added)} proposal(s) appended to {relative(args.path)}"
          f"{f', {len(skipped)} already known' if skipped else ''}")
    print("proposals are advisory: no score changes until a candidate is added to the rule set and re-evaluated")
    return 0


def cmd_rules_proposals(args: argparse.Namespace) -> int:
    from .proposals import load_proposals

    entries = [e for e in load_proposals(args.path) if not args.status or e.get("status") == args.status]
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    if not entries:
        print("(no proposals)")
    for entry in entries:
        dev = entry.get("dev") or {}
        print(_safe(f"{entry['candidate_id']}  {entry.get('status')!s:<9} support {entry.get('support')}  "
                    f"[{entry.get('family')} {entry.get('weight')}]  \"{entry.get('phrase')}\"  "
                    f"dev +{dev.get('injections_missed_by_rules_now')} / -{dev.get('benign_matched')}"))
    return 0


def cmd_rules_decide(args: argparse.Namespace) -> int:
    from .proposals import decide_proposal

    try:
        entry = decide_proposal(
            args.candidate_id,
            status=args.status,
            reviewer=args.by,
            rationale=args.why,
            weight=args.weight,
            family=args.family,
            path=args.path,
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    print(_safe(f"{entry['candidate_id']} is now {entry['status']} ({entry['family']} {entry['weight']})"))
    if args.status == "approved":
        print("it runs in the advisory engine only (llmsentinel rules check); the scored detector is unchanged")
    return 0


def cmd_rules_check(args: argparse.Namespace) -> int:
    from .proposals import advisory_hits

    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    hits = advisory_hits(text, channel=args.channel, host_task=args.host_task, path=args.path)
    if not hits:
        print("no approved candidate matched (this says nothing about the detector's own verdict)")
        return 0
    for hit in hits:
        print(_safe(f"{hit['rule_id']}  {hit['score']:.3f}  {hit['explanation']}"))
    print("advisory only: run `llmsentinel scan` for the verdict that counts")
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

    from .proposals import PROPOSALS_PATH

    proposals_path = argparse.ArgumentParser(add_help=False)
    proposals_path.add_argument("--path", default=str(PROPOSALS_PATH), help="proposals file (append-only)")

    rules = sub.add_parser("rules", help="candidate rules mined from reviewed cases (advisory, never auto-enabled)")
    rsub = rules.add_subparsers(dest="rules_command", required=True)

    propose = rsub.add_parser("propose", parents=[history_path, proposals_path], help="mine candidates from history")
    propose.add_argument("--limit", type=int, default=500, help="how many recent scans to mine")
    propose.add_argument("--min-support", type=int, default=2, help="distinct texts a phrase must appear in")
    propose.add_argument("--max-candidates", type=int, default=20)
    propose.add_argument("--corpus", default=str(CORPUS_PATH), help="corpus for the dev-split report")
    propose.add_argument("--dry-run", action="store_true", help="print candidates without writing them")
    propose.set_defaults(func=cmd_rules_propose)

    listing_p = rsub.add_parser("proposals", parents=[proposals_path], help="list candidates and their state")
    listing_p.add_argument("--status", choices=["proposed", "approved", "rejected"])
    listing_p.add_argument("--json", action="store_true")
    listing_p.set_defaults(func=cmd_rules_proposals)

    for name, status in (("approve", "approved"), ("reject", "rejected")):
        decide = rsub.add_parser(name, parents=[proposals_path], help=f"mark a candidate {status}")
        decide.add_argument("candidate_id")
        decide.add_argument("--by", required=True, help="who decided")
        decide.add_argument("--why", required=True, help="rationale, at least 15 characters")
        decide.add_argument("--weight", type=float, default=None, help="override the proposed weight")
        decide.add_argument("--family", default=None, help="override the proposed family")
        decide.set_defaults(func=cmd_rules_decide, status=status)

    check_rules = rsub.add_parser("check", parents=[proposals_path], help="run approved candidates over text")
    group = check_rules.add_mutually_exclusive_group(required=True)
    group.add_argument("--text")
    group.add_argument("--file")
    check_rules.add_argument("--channel", default="rag_document")
    check_rules.add_argument("--host-task", default=None)
    check_rules.set_defaults(func=cmd_rules_check)
