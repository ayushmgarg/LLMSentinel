# Longer-term research boundary

Section 18 of the checklist. This document draws the line between what this
project *evidences* and what it only *designs*, so that neither the report nor the
interface has to hedge: anything described here as a design is a plan with no
measurement behind it, and is labelled as such wherever it appears.

Each item states the same four things: what exists today, what the design would
be, what is deliberately **not** done, and what evidence would be needed before
any claim could be made.

---

## 1. Multi-turn attacks

**Today.** Every unit is scored on its own: one passage, one tool response, one
tool description. The proxy scans each `tool` message independently and keeps no
state between requests. A payload that is harmless in each turn and only becomes
an instruction when the turns are read together is therefore invisible to the
detector, and the report says so under Limitations.

**Design.** Two changes, both additive:

- *Representation.* A record gains `conversation_id`, `turn_index` and `role`, and
  the label moves up one level: a conversation is an injection if the **action**
  it produces violates the policy, with per-turn spans marking which turns carry
  the payload. Labelling turns independently would reproduce exactly the blind
  spot being studied.
- *Carry-over state.* The scan keeps a bounded memory of directive-shaped content
  seen earlier in the same conversation from the same untrusted source, and scores
  the current turn jointly with it ("remember X for later" in turn 2, "now do what
  you remembered" in turn 7). The memory is per provenance chain, not per session,
  so a document cannot activate a payload another document planted.

**Not done.** No corpus, no evaluation, no code. A generator could produce split
payloads in an afternoon, and the resulting number would measure the generator.

**Evidence needed.** Conversation-level data from more than one source family,
grouped splits keyed on `conversation_id` (turn-level splitting leaks), and an
attack-success criterion defined on the action taken, not on text similarity.

## 2. Multi-agent trust and provenance

**Today.** Provenance is carried per unit (source, channel, JSON path) and the
capability policy decides from the risk of the context that is in front of it.
There is one agent and one gate.

**Design.** Provenance becomes a *chain* rather than a field: each message records
the agent that produced it and the channel it came from, and trust is
**non-increasing** along the chain — a value derived from untrusted input stays
untrusted however many agents it passes through, which is ordinary taint
propagation. The gate then decides on the *minimum* trust in the chain, so an
agent cannot launder hostile text by summarising it for another agent. Manifest
pins become per-agent, because the same MCP server may be approved for one agent
and not for another.

**Not done.** No multi-agent runtime, no evaluation of laundering attacks.

**Evidence needed.** A multi-agent testbed where the laundering path exists, and a
measurement of how much trust is lost per hop under both benign summarisation
(false positives) and deliberate laundering (false negatives).

## 3. Data for multi-turn and multi-agent evaluation

**Not collected.** This item stays open on purpose. A sufficient dataset would
need: conversations from more than one origin (not one template family), channel
balance comparable to the current corpus, grouped splits at conversation level, a
licence that permits redistribution, and held-out *generator* families so that a
number does not just measure a paraphrase of the training generator. The existing
out-of-distribution result (`docs/ood_evaluation.md`) is the reason for that last
requirement: recall on the authored corpus did not survive a change of source.

## 4. Multilingual and multimodal injection

**Today.** The corpus is English (`docs/corpus_card.md`) and the classifier is a
fine-tuned `distilroberta-base`, an English model. Normalisation folds NFKC and
strips zero-width and bidi characters, which helps against homoglyph tricks in any
script, but nothing in the rule lexicons is non-English. The pipeline accepts text
only: an injection inside an image, a PDF rendering or a screenshot reaches it only
after some other component has extracted the text, and nothing here evaluates that
component.

**Design.** Treat each language as its own evaluation with its own thresholds. Our
own transfer results say thresholds do not move across sources without being
re-selected, so a shared threshold across languages would be unjustified. A
multilingual encoder plus per-language dev splits, rather than translating the
existing corpus, which would measure the translator.

**Not done.** No multilingual data, no multimodal path, no numbers.

**Evidence needed.** A recognised multilingual injection benchmark, per-language
dev thresholds, and separate per-language reporting — never a pooled figure.

## 5. Adaptive and white-box attackers

**Today.** `docs/robustness.md` reports fixed, meaning-preserving transforms. That
is measurement against a *static* attacker; it says nothing about one who can
query the detector and optimise against it.

**Design of a safe protocol.** Before any such study runs:

- *Threat tiers, reported separately:* (a) black-box, decision only; (b)
  score access; (c) white-box, gradients on our own checkpoint.
- *Budget:* a fixed query budget per tier, declared in advance, so "evasion found"
  carries a cost.
- *Safety rules:* attacks run only against this project's own detector and its own
  simulated tools; destinations stay in reserved `.invalid` space (RFC 6761); no
  live system, account or third-party model is targeted; working payloads are not
  published — aggregate evasion rates and sanitised excerpts are.
- *Success criterion:* evasion counts only if the attack still succeeds, judged by
  the same objective indicators the demo uses (leaked canary, attacker
  destination, dangerous tool request, planted claim). A payload that evades the
  detector by ceasing to be an attack is not a result.
- *Protocol integrity:* thresholds are fixed before the adaptive run, and the run
  is logged in `docs/EXPERIMENTS.md` like any other. An adaptive attack that then
  motivates a rule change requires a rebuild and a re-run, not an edit.

**Not done.** No adaptive study has been run.

## 6. Production proxy concerns

**Today.** `llmsentinel.proxy` is a research shim, and the module docstring says
so: it binds localhost, has no authentication of its own, refuses `stream: true`
with an explicit error rather than passing tool calls through ungated, and forwards
one upstream at a time. It is enough to show the gate in an OpenAI-compatible path
and not enough for anything else.

**Design, per concern:**

| Concern | What a production version needs |
|---|---|
| Authentication | Per-caller credentials terminated at the proxy, never the upstream key forwarded verbatim |
| Tenant isolation | Separate history database, manifest pins and approvals per tenant; no shared review queue |
| Streaming | Either buffer-and-scan before the first tool call is emitted, or stream prose and hold `tool_calls` until the gate decides; never emit an ungated call |
| Availability | Bounded detector load time, per-request timeouts, back-pressure, and a circuit breaker that degrades to rules-only rather than to nothing |
| Fail-open vs fail-closed | Decided per action class, not globally: read-only may fail open, `external_send`, `write`, `destructive` and `privilege_escalation` fail closed |
| Audit | Append-only, integrity-protected log with the verdict, the thresholds in force and the model version at decision time |

**Not done.** None of the above is implemented, and no load, latency or
availability measurement exists.

## 7. Secret redaction, egress control, server-side authorisation, sandboxing

**Today.** The gate decides *requests*; it never executes anything. That is the
correct scope for a detector and the wrong scope for enforcement: a blocked
`send_email` is only blocked because the caller honours the verdict.

**Separate work, not this project's.** Secret redaction before text ever reaches a
model, network egress restriction at the tool server, server-side authorisation so
that a tool refuses an unauthorised caller regardless of what the agent asked, and
sandboxing of tool execution. These belong to the surrounding system and are the
reason the project describes itself as defence in depth. Building them here would
produce a worse version of well-understood security engineering.

## 8. Privacy-preserving monitoring and broader annotation

**Today.** History is local by default and can be run with `store_text=False`,
which keeps the hash and the excerpt but not the text. Promotion to a regression
fixture sanitises hosts and redacts secret-shaped tokens. `docs/annotation_study.md`
reports a **self-agreement** study on 50 records — whether the guideline reproduces
the intended labels — and states plainly that it is not inter-annotator agreement.

**Design.** Retention with an expiry per record class, redaction at record time
rather than at promotion time, access control on the history database, and
aggregation that answers "which sources are getting worse" without holding the
text at all (counts and hashes only).

**Not done.** No retention policy, no PII detection, no multi-annotator study.

**Evidence needed.** Several annotators, a measured agreement statistic with a
confidence interval, and an adjudication procedure — before any claim about label
quality beyond "one person applied a written guideline consistently".

## 9. Evidence required before certification, SLA or commercial claims

None of the following exists, and until it does the project claims none of them:

- independent evaluation on data this project did not author or select;
- adaptive-attacker results under the protocol in §5;
- latency and throughput SLOs measured under load, with degradation behaviour;
- false-positive cost measured on real traffic, not on hard negatives we wrote;
- a versioned model card and a change-control policy stating what triggers
  re-evaluation;
- incident response for a detector failure, and a published fix cadence;
- third-party audit.

The Studio, the README and the report therefore say "research prototype" and
"defence in depth, not a guarantee", and no customer, benchmark-leadership,
pricing or production-readiness claim appears anywhere in the project.

---

## Continuous rule proposals: how far the engine may learn by itself

A detector that rewrites itself from the traffic it sees is an attacker's dream
and an evaluator's nightmare: the numbers in the report describe a rule set that
would no longer exist, and the text teaching the new rule is text nobody checked.
The project takes the useful half and refuses the dangerous half
(`llmsentinel.analyst.proposals`, `llmsentinel rules ...`):

1. **Mine.** Phrases repeated across cases a reviewer confirmed as injections, or
   that the transformer flagged with no rule able to explain them (`model_only`),
   counted by distinct text so one document scanned ten times supports nothing.
2. **Filter.** A phrase already matched by an existing rule is redundant; a phrase
   that also occurs in benign dev text is dropped.
3. **Report.** Each candidate carries what it would do on the **dev** split: dev
   injections matched, benign matched, precision, and how many dev injections the
   rule engine misses today that the candidate matches. The test split is not read.
4. **Review.** A candidate is a proposal with a status. Approving or rejecting one
   requires a name and a rationale, and the decision trail is appended, never
   rewritten — re-mining a rejected phrase does not resurrect it.
5. **Advisory only.** An approved candidate runs in a *separate* engine whose hits
   are shown to a reviewer. It is not in `default_rules()`, its features never
   enter the fusion model's fixed feature vector, and no reported number moves
   because of it. Its starting weight (0.60) is below every retained pattern, so
   even inside the scored engine a lone candidate hit would aggregate under the
   rules-only 1%-FPR threshold and could not flag a document by itself.
6. **Promotion is deliberate.** Folding a candidate into the scored detector means
   editing the lexicon, rebuilding the corpus, re-running the frozen protocol and
   logging the run. That is the same bar as any other rule change, which is the
   point: the loop shortens the *discovery* of a rule, never the *acceptance* of
   one.
