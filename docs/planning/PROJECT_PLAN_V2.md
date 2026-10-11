# LLMSentinel Project Plan V2

## 1. Purpose

**Working title:** LLMSentinel: Provenance-Aware Detection and Capability Gating for Indirect Prompt Injection in RAG and MCP Agents.

LLMSentinel is a defence-in-depth research system for AI agents that consume
untrusted text. It inspects retrieved RAG content, tool responses, and MCP tool
metadata for indirect prompt-injection attempts; preserves where suspicious
text came from; explains the risk; and applies a deterministic policy to any
proposed downstream action.

The project does **not** claim that detection can solve prompt injection on its
own. Its value is to reduce risk, preserve evidence for review, and prevent a
possibly compromised model from receiving sensitive capabilities without a
separate policy decision.

## 2. Research questions

1. Can provenance, task context, linguistic rules, and learned text signals
   improve low-false-positive detection of indirect prompt injection across RAG
   documents, tool responses, and MCP metadata?
2. Does combining interpretable rules with a trained model improve robustness,
   calibration, or useful explanations compared with either component alone?
3. Can deterministic capability gating reduce unsafe agent actions even when
   detector confidence is uncertain?
4. How well does the approach transfer across datasets, channels, attack
   families, document lengths, and benign instruction-like text?

## 3. Scope and safety boundary

### In scope

- RAG chunks, web pages, wikis, emails, documents, and retrieved context.
- Nested tool-response JSON and MCP-like tool output.
- MCP manifests: tool names, descriptions, parameter schemas, and metadata
  changes.
- English-first detection, with optional multilingual robustness experiments.
- Offline fixtures, public benchmarks, safely replayed tools, and local demos.
- Detection, evidence, isolation/redaction recommendations, and deterministic
  policy decisions.

### Out of scope

- Claims of universal protection or guaranteed detection of adaptive attacks.
- Tests against live third-party systems, real credentials, or personal data.
- Executing sensitive, destructive, or external actions in the demo.
- Treating model output as an authorisation decision.

## 4. Target architecture

```text
Untrusted RAG context / tool response / MCP manifest
                         |
                         v
          Normalisation and provenance extraction
  Unicode, hidden markup, encodings, JSON paths, source identity
                         |
                         v
       Per-unit and context-bundle risk feature extraction
          |                              |
          v                              v
  High-precision rules          Learned text detector
          |                              |
          +---------- calibrated fusion -+
                         |
                         v
       Verdict: score, spans, source, trace, uncertainty
                         |
                         v
  Capability policy: allow / isolate / confirm / block
                         |
                         v
    Safe demo action, audit event, or analyst review queue
```

### Design principles

- Keep untrusted instructions distinct from trusted user intent and system
  policy.
- Treat provenance as a first-class signal: channel, server/tool identity,
  source document, JSON path, retrieval position, and manifest version.
- Make policy deterministic and independently auditable; detection is advisory.
- Prefer measurable claims over marketing claims.
- Ensure every high-risk verdict can show its contributing evidence.

## 5. Core detector and corpus foundation

### Unified corpus

Build a reproducible JSONL corpus where every record includes:

- stable record ID and dataset/document origin;
- raw text and reproducible normalisation version;
- injection/benign label and attack type;
- channel: RAG document, tool response, or tool metadata;
- host task where available;
- JSON path for structured fields;
- injected spans where known;
- source licence, provenance note, group keys, and split;
- hard-negative flag and annotation rationale where applicable.

Use public sources and loaders for BIPIA, InjecAgent, AgentDojo extracts when
appropriate, and an MCP-oriented metadata dataset such as MCPTox where its
licence and schema support use. Retain synthetic fixtures only as clearly
labelled demo and robustness data, never as a substitute for benchmark claims.

### Data quality controls

- Group splits by source host, payload family, and near-duplicate content.
- Preserve realistic channel/content pairings; a tool description should look
  like a tool description, not a random document pasted into a JSON leaf.
- Include substantial hard negatives: API documentation, security articles,
  quoted attacks, policies, tutorials, code, and legitimate imperatives.
- Perform independent annotation on an agreed sample, resolve disagreements,
  and record guideline revisions.
- Generate a corpus card, source/licence inventory, split manifest, and leakage
  report for every frozen data version.

## 6. Detection methods

### Normalisation and evidence recovery

Normalise safely while retaining raw-to-normalised offset mappings and evidence
for all transformations:

- Unicode NFKC, suspicious homoglyphs, zero-width characters, and bidi text.
- HTML entities, comments, hidden markup, Markdown/code fences, and structured
  JSON string leaves.
- Conservative base64, hexadecimal, URL, and percent-decoding with parent-child
  provenance.
- Sentence and section segmentation with offsets.

### Interpretable rules

Implement and evaluate rules for:

- instruction override and role/system-prompt references;
- secrecy, exfiltration, sensitive-object plus outbound-action combinations;
- suspicious tool invocation, action hijacking, and destructive operations;
- obfuscation and hidden/encoded control content;
- MCP metadata poisoning and manifest changes;
- task/context conflict as corroborating evidence.

Context suppression must be adversarially tested. Quotation, code fences, or
phrases such as “for example” must not become inexpensive ways to hide an
otherwise active malicious instruction.

### Learned detectors

Compare, at minimum:

1. Majority baseline.
2. Keyword/regex baseline.
3. TF-IDF word and character n-gram logistic regression.
4. Transformer-only detector.
5. Rules-only detector.
6. Calibrated hybrid detector.

For the transformer, use consistent train/inference handling of long documents:
train on the same overlapping windows that inference scores, retain window and
position provenance, and explicitly handle documents beyond the maximum window
budget. Evaluate a compact encoder first; investigate long-context encoders
only after the baseline protocol is sound.

### Contextual and semantic extensions

Add these as experiments, not assumptions:

- semantic comparison between the user task, proposed action, and untrusted
  instruction;
- source-aware features such as a manifest field, tool server identity, or
  document type;
- retrieval-bundle scoring over several chunks rather than one chunk at a time;
- document register and instruction outlier signals;
- calibrated uncertainty and abstention/review for borderline cases.

Do not describe lexical overlap or imperative detection alone as genuine
semantic task-conflict reasoning.

## 7. Evaluation protocol

### Primary measurements

- AUPRC and AUROC (the latter for comparison only).
- TPR at 1% and 0.1% target FPR, with realised FPR reported beside each target.
- Hard-negative FPR.
- Per-channel, per-dataset, per-attack-type, and per-action-category results.
- Mean and p95 detection latency, model size, and memory where feasible.
- Calibration quality and policy outcomes for demo scenarios.

### Experimental discipline

- Fit base models only on training data.
- Use development data for threshold selection, model selection, fusion, and
  calibration; use out-of-fold predictions where a stacker is trained on dev.
- Freeze a held-out test set before design iteration; score it only once for
  final reporting.
- Log date, code commit, corpus digest, seed, command, machine details,
  metrics, warnings, and observations for every quote-worthy result.
- Report confidence intervals or repeated seeds where compute permits.

### Required analysis

- Leave-one-rule-family-out and retained-rule ablations.
- Rules-only versus transformer-only versus hybrid comparison.
- Cross-channel and cross-dataset transfer when data permits.
- Error analysis of false positives and false negatives, including evidence,
  channel, attack type, and mitigation ideas.
- Explicit negative results; a complex hybrid must not be retained merely
  because it is more elaborate.

## 8. Robustness programme

Test the detector against safe, reproducible variants:

- payload at beginning, middle, and end of a long context;
- whitespace, punctuation, casing, Markdown, quotation, and code fencing;
- Unicode homoglyph, zero-width, and bidi perturbations;
- conservative encoded payloads;
- paraphrase and declarative rather than imperative attack wording;
- long-context dilution and multiple benign distractor chunks;
- instruction-like but benign documentation and policies;
- payloads divided across several retrieval chunks or safe replayed tool calls;
- optional multilingual variants with language and dataset limits stated.

Record failures as first-class findings. Never silently tune them away using
test data.

## 9. MCP and agent-security layer

### MCP scanning

Provide offline scanning for:

- tool descriptions, parameter descriptions, schemas, and manifest fields;
- nested tool-response JSON leaves and their exact JSON paths;
- manifest hashes and changes between approved and observed tool definitions;
- risky text paired with downstream capability categories.

### Capability policy

Define a small declarative policy model with action classes:

- read-only;
- sensitive read;
- external send/network egress;
- write or state change;
- destructive action;
- tool installation or permission escalation.

Map them deterministically to `allow`, `isolate`, `require confirmation`, or
`block`. The policy must work even if detector confidence is unavailable, and
the demonstration must only simulate actions.

### Advanced security research direction

Longer-term work can add constrained tool sandboxes, redacted secrets,
restricted network egress, server-side authorisation checks, safe replay logs,
and fail-open/fail-closed operational design. These are security-engineering
projects in their own right and should not be represented as complete merely
because a detector exists.

## 10. Demo and usability

Build an offline local page that demonstrates the full chain with no external
credentials.

### Required flows

1. RAG: clean versus poisoned retrieved document.
2. Tool response: clean versus poisoned nested JSON leaf.
3. MCP manifest: approved versus suspicious/changed metadata.
4. Same proposed action with guard off versus guard on, with no real execution.

### Required views

- source selector and safe text/JSON paste input;
- original content, JSON tree/path, and source provenance;
- normalised/decoded evidence where relevant;
- highlighted suspicious raw-text spans;
- risk score, operating threshold, uncertainty/degraded-state warning;
- rule trace and model/fusion evidence where available;
- proposed action, capability class, and deterministic policy decision;
- limitations/disclaimer panel and reproducibility information.

### Optional product framing

After the demo and evidence are sound, add a clearly labelled research-prototype
landing section. Suitable target users are enterprise RAG applications, support
agents, developer agents, and MCP integrations. Suitable capability cards are
manifest scanning, runtime context scanning, provenance/audit traces, and action
gating. Do not invent customers, certifications, performance claims, or pricing.

## 11. Analyst and operational extensions

These additions make the prototype more useful for a security-team workflow:

- persistent local scan history and a searchable audit trail;
- analyst review queue with verdict override and rationale;
- aggregation by tool, server, source domain, attack family, and action type;
- regression suite for newly discovered safe attack fixtures;
- drift/change alerts for tool manifests and model/rule releases;
- safe replay of historical, sanitised tool and retrieval events;
- SDK or local proxy interface between the agent and its retriever/MCP client.

They should be implemented only after the detection/evaluation baseline is
stable, because an attractive dashboard cannot compensate for unvalidated
detection quality.

## 12. Longer-term research and engineering boundary

The following are valuable directions but require substantially more evidence,
engineering, and often real organisational data:

- reliable multi-turn and multi-agent injection detection;
- broad multilingual or multimodal protection;
- generalisation to adaptive, white-box attackers;
- production proxy deployment with authentication, streaming, availability,
  tenant isolation, and robust failure semantics;
- OS/container sandboxing and real secret-management integration;
- continuous monitoring over real enterprise traffic;
- large human-review studies and a broad independently annotated corpus;
- production security guarantees, certifications, or commercial SLAs.

Keep these as explicit future work rather than promises for the prototype.

## 13. Definition of a credible completed project

LLMSentinel is research-complete when it has:

- a reproducible, licence-documented corpus with real public benchmark coverage;
- leakage-controlled splits and a frozen test protocol;
- fair baseline, rules-only, transformer-only, and hybrid comparisons;
- robustness and error analysis that report failures honestly;
- evidence-backed provenance, spans, and explanations;
- deterministic simulated action gating separate from model output;
- an offline live demonstration across RAG, tool-response JSON, and MCP
  metadata scenarios;
- a report that frames detection as defence in depth, clearly states limits,
  and ties every result to a logged experiment.
