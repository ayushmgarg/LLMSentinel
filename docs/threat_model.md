# Threat model and research protocol (frozen)

Frozen on 2026-09-06. Changing anything here invalidates every logged
experiment, so a change must be accompanied by a new entry in
[EXPERIMENTS.md](EXPERIMENTS.md) and, where it affects the data or the
normalisation output, a bump of `CORPUS_SCHEMA_VERSION` or
`NORMALISATION_VERSION` in `src/llmsentinel/constants.py`.

## 1. What is being defended

An LLM agent that reads untrusted content and can call tools. The content
reaches it through three channels, and provenance is tracked per channel because
the same sentence means different things depending on where it arrived from:

| Channel | What it is | Example |
|---|---|---|
| `rag_document` | retrieved documents, web pages, emails, wiki chunks | a support article returned by search |
| `tool_response` | JSON returned by a tool, including nested string leaves | `$.results[0].content` from `search_notes` |
| `tool_metadata` | a tool's own advertised name, description and parameter schema | an MCP server's tool declaration |

## 2. Attacker

**Capability.** Can write arbitrary text into any of the three channels: publish
a page that will be retrieved, control a document the user uploads, operate or
compromise an MCP server whose results or manifest the agent reads. Can choose
the *formatting* of that text freely — quotes, code fences, HTML, Unicode
tricks, encodings.

**Goal.** Cause the agent to follow instructions that conflict with the user's
task: exfiltrate data, call a tool the user did not ask for, take a destructive
action, or change what the agent reports.

**Not assumed.** No access to model weights, no access to the system prompt, no
ability to modify the guard's code or its corpus, no control of the user's own
request.

### Attacker control of the detector's inputs

Because the attacker writes the text, every signal the guard derives from that
text is attacker-influenced. This has one concrete consequence that shapes the
implementation: **context suppression may not be cheaply purchasable.** Wrapping
a payload in quotation marks or a code fence must not lower its score
meaningfully — see `src/llmsentinel/rules/context.py` and
`tests/test_rules.py::test_formatting_alone_cannot_lower_a_detection`.

## 3. In scope

- Detection of injected instructions in the three channels above.
- Explanation: flagged spans, matched rules, normalisation evidence.
- Provenance: channel, JSON path, offsets back into the raw bytes.
- Recommendation only — isolate the text, require confirmation, block a
  proposed action (Week 3). The system never executes anything.
- English text, public benchmarks, public payload patterns, offline fixtures.

## 4. Out of scope

- Any claim of complete protection, especially against an adaptive attacker who
  can query the detector.
- Multi-hop payloads assembled across several retrieved chunks.
- Multilingual optimisation, image and audio channels.
- Live third-party MCP servers, real credentials, and any non-consenting system.
- Automatic execution of sensitive actions, now or later.
- Model-weight modification, and any change to the protected model itself.

## 5. Labels

An example is **positive** when it contains *assistant-directed control content
that conflicts with the host task*. Both halves are required. The full
adjudication rules, with worked examples, are in
[annotation_guideline.md](annotation_guideline.md).

## 6. Metrics (frozen)

Primary, reported for every system on the same splits:

- **AUPRC** (average precision) — the headline ranking metric.
- **TPR at 1% FPR** and **TPR at 0.1% FPR** — usable operating points.
- **False-positive rate on hard negatives** — reported separately, because it is
  the number that decides deployability.
- **Realised FPR at each operating point**, next to the target, with an explicit
  flag when the budget is exceeded.
- **Per-channel** metrics and **per-attack-type recall**, reported at each
  operating point with support counts.
- **Latency**, mean and p95, measured single-document.

AUROC is computed for comparison with published work only. It is never used to
select a model, a threshold or a design decision.

## 7. Experimental protocol (frozen)

1. Systems are fitted on **train** only. The fusion meta-model is the documented
   exception: it is fitted on **dev**, and dev numbers for it are out-of-fold.
2. Thresholds are selected on **dev** only.
3. **Test** is scored once, with dev thresholds, and only behind an explicit
   `--test` flag.
4. Splits are grouped by payload family *and* host document; the guarantee is
   re-derived from the written corpus by an independent audit.
5. Seeds are fixed (`DEFAULT_SEED`). Any seed selection is made on corpus
   structure only and is recorded with its criterion.
6. Every reported number has a command, a corpus digest and a log entry.

## 8. Baselines (frozen)

`majority`, `keyword`, `tfidf-word`, `tfidf-word+char`, `rules-only`,
`transformer`, `hybrid`. All are evaluated through one harness, on identical
splits, with identical threshold selection.

## 9. Action categories and policy outcomes (defined now, implemented in Week 3)

Actions an agent might propose, in increasing order of consequence:

| Category | Meaning |
|---|---|
| `read_only` | reads non-sensitive data already in scope |
| `sensitive_read` | reads credentials, private files, conversation history |
| `external_send` | transmits data outside the trust boundary |
| `write` | changes state that others can observe |
| `destructive` | irreversible deletion, security-control removal, money movement |

Policy outcomes, deterministic given the category and the risk band:

| Outcome | Meaning |
|---|---|
| `allow` | proceed |
| `isolate` | proceed, but strip the flagged text from the model's context |
| `confirm` | require explicit human confirmation before acting |
| `block` | refuse in the demo, regardless of confidence |

The detector's score is advisory input; the policy mapping is deterministic and
auditable. Detection failure must degrade to a *safe* outcome, never to `allow`.

## 10. Honest limits

- The current corpus is synthetic. Nothing measured on it is benchmark
  performance or evidence of generalisation to real attacks; the corpus card
  says so in a banner generated from the data itself.
- Detection is defence in depth. It complements least privilege, human approval
  and server-side authorisation, and replaces none of them.
