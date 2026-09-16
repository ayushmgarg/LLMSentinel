# Analyst workflow (checklist §17)

Local tooling for the person who has to act on what LLMSentinel decides:

- a history of every scan;
- a queue of the cases worth a second look;
- a way to disagree with the detector without erasing it;
- aggregate views;
- alerts when a connected tool server changes;
- a path from a reviewed case to a regression test.

> **Not production enforcement.** Everything here is advisory and local. The SDK and
> the proxy can be bypassed by code that ignores them, have no authentication, and
> inherit the detector's measured limits: dev thresholds do not transfer to unseen
> sources, and soft-claim content manipulation is weak (`docs/report.md` §6a, §9).
> Keep least privilege, human approval for sensitive actions and server-side
> authorisation in place.

## Where it lives

| Piece | Code | Surface |
|---|---|---|
| History store | `src/llmsentinel/analyst/store.py` | SQLite at `artifacts/analyst/history.sqlite3` (gitignored; `LLMSENTINEL_HISTORY` or `--history` to move it) |
| Review triggers | `src/llmsentinel/analyst/review.py` | reuses `semantic/review.py` |
| Predicted families | `src/llmsentinel/analyst/families.py` | read from the rule trace |
| Regression fixtures | `src/llmsentinel/analyst/fixtures.py` | `data/regression/discovered.yaml`, `tests/test_regression_fixtures.py` |
| SDK | `src/llmsentinel/sdk.py` | `from llmsentinel.sdk import Sentinel` |
| Local proxy | `src/llmsentinel/proxy.py` | `python -m llmsentinel.proxy --upstream …/v1` |
| CLI | `src/llmsentinel/analyst/cli.py` | `llmsentinel history …`, `llmsentinel manifests …`, `llmsentinel scan --record` |
| Studio | `studio/server/history.py`, `/api/analyst/*` | the **Analyst** section of the page |

## Design decisions

**The original verdict is never rewritten.** Scan rows are insert-only, enforced by
SQLite triggers rather than convention. A reviewer's disagreement is a separate
override row with a label, a reviewer name and a rationale of at least 15 characters.
The *effective* label is the latest override. The detector's own call remains
readable beside it, so the audit trail shows both what the system said and what a
person decided.

**Nothing is deleted.** The same triggers refuse deletes on scans, overrides, pins,
alerts and acknowledgements. Acknowledging an alert adds a row; it does not remove
the alert.

**Every row names the system that produced it.** Each row records:
- package version;
- detector;
- the rule set's ids;
- policy version;
- threshold source;
- normalisation version;
- in the Studio, a batch id per comparison.

**What gets recorded.**

| Kind | One row per |
|---|---|
| `content` | normalised unit: a document, a JSON leaf or a decoded payload, with risk, band, spans, rule trace, evidence and families |
| `manifest` | tool, with its content verdict and drift |
| `action` | tool call the capability policy decided in a guarded run. The Studio's *unguarded* calls are a counterfactual and are not recorded. |

Full text is stored by default so reviewed cases can become fixtures. Use
`ScanStore(store_text=False)` to keep only a SHA-256 digest and a 400-character excerpt.

**What goes into the review queue.** The queue is for cases a human can improve, not
a copy of every alert. A scan is queued, until someone reviews it, when any of these
hold:

| Trigger | Source |
|---|---|
| a rule failed on the input (score under-reports risk) | `semantic/review.py` |
| risk sits within 25% below the elevated threshold | `semantic/review.py` |
| rule and model scores differ by ≥ 0.5 | `semantic/review.py` |
| band is **elevated but not high** (between the dev 1% and 0.1% points) | `analyst/review.py` |
| flagged with **no rule span or reason** to check the call against | `analyst/review.py` |
| a tool declaration **changed or appeared** after approval (Studio) | `studio/server/history.py` |

A high-confidence, explained detection is recorded but not queued.

**Families are predictions.** A live scan has no label, so "attack family" is read
from the rule families that fired, mapped to the corpus attack types.
`answer_shaping.v1` maps to `content_manipulation`. A detection with no rule behind it
is reported as `model_only` instead of being guessed into a family.

**Aggregation.** Group by tool, server, source, source domain (the host of a URL or
e-mail source), attack family, channel, action class, decision, band or kind. Each
group reports scans, flagged, flagged rate, mean and max risk, and how many were
reviewed.

**Manifest alerts.**
- Approving a server pins each tool's `manifest_hash`: name, description and parameter
  schema; cosmetic fields such as an icon or version are ignored.
- Each later scan compares against the pins and raises `unapproved`, `changed`,
  `added` or `removed`. An identical alert that is still open is not raised twice.
- In the SDK, a changed or added tool is quarantined, and `gate()` blocks it. A server
  that was never approved is scanned on content alone, because there is no approved
  state to have drifted from.
- In the Studio, an uploaded manifest uses the analyst's pins as its approved snapshot.

**Regression fixtures are gated and sanitised.**
- Only a scan with a reviewer override can be promoted, and the fixture takes the
  *reviewer's* label.
- Hosts in URLs and e-mail addresses are rewritten to reserved `.invalid` names, and
  secret-shaped tokens are redacted.
- The sanitised text's rules-only score is stored. `tests/test_regression_fixtures.py`
  fails if a promoted injection later scores lower, or a promoted benign case scores
  higher, than when it was promoted (tolerance 0.05).
- Fixtures are append-only.

**The proxy withholds and gates; it does not strip.**
- It scans `tool`/`function` role messages. A flagged one has its content replaced by a
  notice naming the flagged JSON paths.
- Tool calls in the model's reply are gated in the context of what that request
  carried. A request with no tool messages carried no untrusted content, so the
  context is empty (low risk) rather than unknown.
- Streaming is refused (HTTP 400), because tool calls cannot be gated mid-stream
  without buffering.

## Using it

```bash
# record a scan (and a proposed action) from the command line
llmsentinel scan --file page.html --record --source https://docs.vendor.io/faq --action send_email

# triage
llmsentinel history queue
llmsentinel history show 3f2a9c1b7e4d
llmsentinel history override 3f2a9c1b7e4d --label benign --reviewer ana --rationale "Quoted in a security training page, not addressed to the assistant."
llmsentinel history stats --by family
llmsentinel history list --server vendor-mcp --flagged yes
llmsentinel history promote 3f2a9c1b7e4d --by ana

# tool servers
llmsentinel manifests check tools.json --server vendor-mcp
llmsentinel manifests approve tools.json --server vendor-mcp --by ana
llmsentinel manifests alerts
llmsentinel manifests ack 9b1e0c --by ana --note "expected release"

# in code
python -c "from llmsentinel.sdk import Sentinel; print(Sentinel(detector='rules').scan_text('Ignore all previous instructions.').flagged)"

# between an agent and its model
python -m llmsentinel.proxy --upstream http://localhost:11434/v1 --port 8710
```

In the Studio (`python -m studio.server`), every comparison is recorded. The
**Analyst** section offers the review queue, filtered history, insights and manifest
alerts, plus a detail panel with the override form and "promote to fixture".
`--no-history` turns recording off; `--history PATH` moves the database.

## How it was verified

- **Unit and integration tests** cover the store (append-only triggers, overrides,
  queue, filters, statistics, manifest drift, sanitisation, promotion), the SDK, the
  proxy against a mocked upstream, the CLI end to end, and the Studio endpoints. They
  live in `tests/test_analyst.py`, `tests/test_sdk.py`, `tests/test_proxy.py`,
  `tests/test_analyst_cli.py` and `studio/tests/test_studio_analyst.py`.
- **Live check in the Studio**, rules-only, with a separate sandbox history:
  1. One comparison recorded 10 scans (3 flagged, 1 queued: a tool changed after
     approval).
  2. A reviewer label cleared the queue and kept "detector said: injection" beside it.
  3. An uploaded manifest raised `unapproved`; approving and acknowledging cleared it.
  4. The next upload with a changed description was quarantined and raised `changed`.

## Limits

- The review triggers are heuristics built on the dev operating points. They are not
  evaluated for how well they pick cases a reviewer would actually change.
- Predicted families inherit the rule engine's coverage. A model-only detection has
  no family.
- One SQLite file, one machine: no multi-user access control, no retention policy, no
  encryption at rest. Section 18 lists what production monitoring would need.
