# Project decisions and controls

Standing decisions, recorded so the checklist's control items point at something
verifiable rather than at somebody's memory. Research protocol lives in
[threat_model.md](threat_model.md); per-run records live in
[EXPERIMENTS.md](EXPERIMENTS.md).

## Identity and scope

| item | decision |
|---|---|
| Title | **LLMSentinel** — Provenance-Aware Detection and Capability Gating for Indirect Prompt Injection in RAG and MCP Agents |
| Scope | Limited to **detection, explanation, and demo-only policy decisions**. The system produces a `Verdict` and a `PolicyDecision`; it has no execution path. |
| Team | **One person.** Every Person A / B / C responsibility in the plan is held by the same person. Items that presuppose two or more people are recorded as not applicable below, not silently ticked. |
| Communication channel | Not applicable at team size one. The written record *is* the channel: `docs/EXPERIMENTS.md` for runs, this file for standing decisions, `PROJECT_CHECKLIST.md` for state. |

## Safety commitments

These are enforced by construction, not by intention:

| commitment | how it is enforced |
|---|---|
| No testing against live services | The detector makes no network calls. `tests/test_policy.py::test_policy_package_imports_nothing_that_can_act` AST-checks that the policy package imports no `socket`, `requests`, `urllib`, or `subprocess`. |
| No real secrets | Every payload destination uses a reserved name (`.invalid`, `.test`, `example.com`, RFC 2606 / 6761). Every "credential" is an obvious placeholder. |
| No non-consenting systems | Third-party benchmarks are read from a local clone; nothing is fetched at run time and nothing is redistributed. |
| No automatic sensitive actions | The policy returns data. `PolicyDecision` exposes no callable beyond `summary()` and `to_dict()`, asserted by test. |

## Tool and dependency decisions

**spaCy** — the library is installed; the pretrained `en_core_web_sm` model is
**not**, because this environment cannot reach `raw.githubusercontent.com`
(`WinError 10051`, unreachable network), which is where `spacy download`
resolves its compatibility table. GitHub itself is reachable — `git ls-remote`
against the benchmark repositories succeeds — so the block is host-specific, not
a general lack of network.

The optional path still works: `segment_sentences(..., use_spacy=True)` falls
back to a blank English pipeline with a `sentencizer`, verified to produce exact
offsets (`text[s.start:s.end] == s.text`) and to handle the abbreviation case.
The checklist item "install the spaCy English model" stays **unticked** — the
model is genuinely absent, and the fallback is not the same thing.

Nothing in the project depends on it. The default segmenter stays
dependency-free because it is offset-exact and version-stable, which spaCy's
sentence boundaries are not guaranteed to be across releases.

**NLTK** — **not used.** The checklist item is conditional ("only if they are
used"); no code imports it, so there is nothing to download. Recorded here so
the absence is a decision rather than an oversight.

**AgentDojo** — **not needed** for this project. It evaluates end-to-end agent
behaviour under attack, which requires executing an agent against tools. That is
out of scope by the threat model (detection and advisory policy only), and the
Week 4 evaluation is a detection evaluation, not an agent evaluation. InjecAgent
already supplies the tool-response text this project scores. Revisit only if the
scope changes to measuring whether a *guarded agent* completes its task.

## Labelling

**Manual labelling was not required.** Labels in the built-in corpus are assigned
**by construction**: a record is positive because a payload template was inserted
into it, and benign because a distractor or hard-negative text was. There is no
hand-labelling step whose disagreement rate could be measured, so the checklist's
200-example manual-labelling item is satisfied by the condition being false, not
by doing the work.

What the guideline governs is *what goes into* `data/seed/*.yaml`, and what
adjudicates any externally sourced record. Its rules were validated by inspecting
40 built records (20 random, 20 hard negatives) against it — see the audit entries
in the experiment log.

**Two-person independent labelling is not possible at team size one** and is left
unticked. The nearest honest substitute — a blind re-annotation pass by the same
person, reported with its agreement rate — is available on request; it would
measure guideline clarity, not inter-annotator agreement, and would be labelled
as such.


**MCPTox** — **inspected, integration not promised.** The loader
(`data/loaders/mcptox.py`) was written against the *shape* of an MCP tool
declaration and it **refuses any record without an explicit label**, reporting
how many it skipped rather than guessing. No canonical MCPTox release could be
located and verified from this environment, so nothing is loaded from it and the
`tool_metadata` channel is supplied by the built-in seed corpus alone. This is
the "inspect before promising" outcome the checklist asks for. If a labelled
release is placed under `data/raw/mcptox/`, the loader activates automatically.

## Process items — owner decisions

The project owner reviewed the remaining control items and decided the process
overhead below is not tracked for this single-person, timeboxed project. Recorded
here so the checklist points at a decision, not an omission.

| item | decision |
|---|---|
| Weekly review time | Not tracked. Progress is reviewed per milestone against `PROJECT_CHECKLIST.md`; there is no fixed weekly slot for a one-person team. |
| Daily status format | Not tracked as a daily ritual. The experiment log (`EXPERIMENTS.md`) is the running record of what was done, blocked and next. |
| Final deadline / reserve last two days | No imminent deadline. Further tasks follow this checklist; the "reserve two days for demo/rehearsal" rule will be applied once a submission date is fixed. |
| Course GenAI / academic-integrity policy | Owner recorded this as not required to transcribe here. GenAI use in this project is substantial and is disclosed openly throughout the repository history and documentation. |
| First git commit | Done — repository initialised at github.com/ayushmgarg/LLMSentinel, branch `a1`; history is public. |
| Third-party benchmarks | BIPIA and InjecAgent cloned (both MIT) and integrated. MCPTox: no verifiable release located — see the MCPTox note above. |
