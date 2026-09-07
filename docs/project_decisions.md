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

## Still needed from the project owner

These cannot be decided from the repository:

| item | what is needed |
|---|---|
| Final deadline, last two days reserved for demo/rehearsal | the submission date |
| Weekly review time | a day and time, or a decision to review per milestone instead |
| Daily status format | confirm "done / blocked / next", appended to the experiment log |
| Course GenAI policy and academic-integrity obligations | the course's stated policy, recorded verbatim here |
| First git commit | permission to `git init` and commit (a `.gitignore` is required first: the checkpoints are ~300 MB each) |
| Third-party benchmarks | permission to clone BIPIA and InjecAgent, and to inspect an MCPTox release. Both repositories were confirmed reachable from here (`git ls-remote` succeeds); only the download decision is outstanding. |
