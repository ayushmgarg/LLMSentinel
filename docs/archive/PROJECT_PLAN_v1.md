# LLMSentinel Project Plan

## 1. Decision and scope

**Working title:** LLMSentinel: Provenance-Aware Detection and Capability Gating for Indirect Prompt Injection in RAG and MCP Agents.

**Project outcome:** deliver a reproducible NLP mini-project that detects suspicious instructions in untrusted context and presents a visual, live demo. The demo must show a RAG document and an MCP-style tool response being inspected, the suspicious span and reasons being highlighted, and the resulting policy decision.

**Timebox:** 4 weeks maximum. A usable 3-week version is defined below; Week 4 is for robustness, polish, and fallback work.

**Team assumption:** 2 people minimum, 3 people ideal. The project must remain buildable by two people.

## 2. Research question

Can provenance, task context, and lightweight linguistic signals improve low-false-positive detection of indirect prompt injection in retrieved text and MCP-style tool outputs, while allowing an action-policy layer to prevent sensitive tool actions?

The project does not claim to solve prompt injection universally. It evaluates a defense-in-depth guard under clearly stated limits.

## 3. Final product definition

### Required deliverables

1. A documented, reproducible corpus containing benign and injection-bearing examples from RAG and tool-response settings.
2. Baseline detectors: keyword rules, TF-IDF plus logistic regression, and a fine-tuned small transformer.
3. LLMSentinel hybrid detector: normalisation, high-precision rules, transformer score, calibration, explanation trace, and flagged spans.
4. Evaluation report with AUPRC, TPR at fixed FPR, false positives on hard negatives, latency, cross-channel transfer, and error analysis.
5. A visual local web demo with live results for at least one poisoned RAG document and one poisoned MCP-style JSON response.
6. A concise project report and presentation-ready figures.

### Optional deliverable

A separate landing-page section in the demo that positions LLMSentinel as an enterprise MCP/RAG guard. It must not claim that the system guarantees security or is production-certified.

## 4. Threat model and boundary

### In scope

- Retrieved documents, web-style text, emails, wiki chunks, and RAG context.
- MCP-style tool responses, including nested JSON string fields.
- Basic MCP tool metadata scanning: tool name, description, parameter schema, and changed manifest warning.
- English text, public benchmarks, public payloads, and offline demo data.
- Detection, explanation, redaction/isolation recommendation, and action-policy recommendation.

### Out of scope

- Claims of complete protection against adaptive or white-box attackers.
- Attacking live systems, real third-party MCP servers, or real user data.
- Automatic execution of sensitive actions.
- A production security product, multilingual optimisation, image/audio attacks, multi-hop assembled payloads, or model-weight modification.

## 5. System to build

```text
RAG chunk / MCP result / MCP manifest
              |
              v
       Normalise and preserve provenance
  JSON path, source type, Unicode, markup, encoding
              |
              v
      Candidate sentence or string-leaf extraction
              |
              +------------------------+
              |                        |
              v                        v
   High-precision linguistic rules   Small transformer
              |                        |
              +----------+-------------+
                         v
             Calibrated risk / explanation
                         v
     Allow | isolate text | require confirmation | block
                         v
       Capability policy for proposed tool action
```

### Minimum viable rule signals

- Meta-instruction references: system prompt, previous instructions, ignore, override, role tokens.
- Obfuscation: zero-width characters, homoglyph changes, encoded text, hidden markup.
- Sensitive action/exfiltration pattern: send/upload/post/disclose plus URL, email, credential-like string, or sensitive tool.
- Tool-manifest change/hash mismatch in the demo.

Imperative detection, WordNet expansion, topic outlier scoring, n-gram surprise, and coreference resolution are experiments, not required security assumptions. Add them only after the MVP evaluates correctly.

## 6. Dataset and evaluation design

### Data sources

- BIPIA for retrieval/document indirect injections.
- InjecAgent and/or AgentDojo extracts for tool-agent cases.
- MCPTox samples for MCP tool-metadata poisoning, if the loader is practical.
- Public, permissively usable benign text: documentation, API references, READMEs, tutorials, policies, and ordinary RAG passages.

### Corpus requirements

Each record must retain: source ID, source channel, raw text, normalised text, label, attack type, host task, JSON path where applicable, provenance, source licence, and split.

At least 25% of benign examples must be hard negatives: legitimate imperatives, security articles quoting attacks, code/API documentation, policies, or instructions for humans. Never put variants of one payload or host document across train and test.

### Main metrics

- AUPRC.
- TPR at 1% and 0.1% false-positive rate.
- False-positive rate specifically on hard negatives.
- Per-channel and per-attack-type recall.
- Mean and p95 inference latency.
- End-to-end demo outcome: unsafe proposed action blocked/confirmed versus normal task retained.

### Required baselines

1. Majority-class baseline.
2. Keyword/regex baseline.
3. TF-IDF word and character n-grams plus logistic regression.
4. Transformer-only detector.
5. Rules-only detector.
6. Hybrid calibrated detector.

Use the same splits and thresholds for every system. Do not promise an improvement before experiments run; report a negative result honestly.

## 7. Four-week delivery schedule

### Week 1: Foundation and corpus MVP

**Goal:** obtain a clean, inspectable dataset and a reliable evaluation harness before building a complex model.

- Freeze the scope, title, threat model, evaluation protocol, and team roles.
- Create environment and dependency lock strategy.
- Implement data loaders for BIPIA and one tool-channel source.
- Define one unified JSONL schema and deterministic grouped splits.
- Collect and label hard negatives.
- Implement normalisation and source/JSON-path preservation.
- Build metric utilities and baseline evaluation command.
- Hand-check at least 20 random records and 20 hard negatives.

**Week 1 exit criterion:** a command can build a corpus card and run keyword and TF-IDF baselines without data leakage.

### Week 2: Detection MVP

**Goal:** produce the core detector and first real result table.

- Implement the minimum rule signals and unit tests.
- Fine-tune one practical encoder model, with a CPU-compatible fallback.
- Implement transformer inference and threshold selection on validation data.
- Implement score-level fusion of transformer probability and rule signals.
- Add calibrated confidence, flagged span, source, and reason trace.
- Run rules-only, transformer-only, and hybrid experiments with fixed seeds.
- Perform initial false-positive/error analysis.

**Week 2 exit criterion:** LLMSentinel produces a verdict, confidence, highlighted span, and reason trace on document and JSON inputs; an initial comparison table exists.

### Week 3: Agent policy and live visual demo

**Goal:** make the work understandable and demonstrable in a room.

- Define a small capability policy: read-only, local sensitive read, external send, data write, destructive action.
- Implement demo-only action decisions: allow, isolate, confirmation required, block.
- Build a safe local RAG example with a clean corpus and one poisoned document.
- Build a safe local MCP-style JSON response example with a poisoned string leaf.
- Build the local visual page: input/source panel, detection result, highlighted spans, rule trace, proposed action, and final policy decision.
- Add a clean-versus-poisoned toggle and an inspectable JSON-path view.
- Measure demo latency and capture screenshots/video backup.

**Week 3 exit criterion:** a fresh local start runs the live demo and visibly distinguishes clean and attack cases without any external credentials.

### Week 4: Evidence, polish, and optional landing framing

**Goal:** make results defensible and presentation-ready.

- Add cross-channel or cross-dataset evaluation, if source loaders support it.
- Run ablation for each implemented rule family.
- Run robustness checks: paraphrase, casing/whitespace, position shift, Unicode/encoding where safely supported, and long-context dilution.
- Complete error analysis of false positives and false negatives.
- Generate figures, tables, corpus card, reproducibility instructions, and experiment log.
- Prepare presentation narrative and demo script.
- Optionally add a non-functional landing-page section explaining target customers, supported channels, audit output, and a contact/demo CTA.

**Week 4 exit criterion:** all reported numbers are reproducible, limitations are explicit, and the demo has a recorded fallback.

## 8. Team allocation

### Two-person team

- **Person A:** corpus, normalisation, rules, experiment logging, error analysis.
- **Person B:** baselines, transformer, fusion, evaluation, visual demo shell.
- Both: dataset review, demo narrative, results interpretation, presentation.

### Three-person team

- **Person A:** corpus and hard negatives.
- **Person B:** rules, transformer, fusion, metrics.
- **Person C:** MCP/RAG demo, capability policy, visual UI, report figures.

Do not parallelise work that depends on an unfrozen corpus schema or untested metric harness.

## 9. Demo specification

The demo must be an offline local page, not a mockup.

### Required user flow

1. User selects **RAG document** or **MCP tool response**.
2. User chooses a clean or poisoned sample, or pastes safe text/JSON.
3. The page shows source type, text/JSON path, normalised text, risk score, decision, and highlighted suspicious spans.
4. The page displays why it flagged: e.g. meta-instruction, obfuscation, exfiltration/action pattern.
5. The page shows a proposed action and the policy outcome.
6. The page shows the same task with guard off versus guard on, without actually sending data or invoking privileged tools.

### Optional commercial landing content

- Headline: “Detect untrusted instructions before they reach your agent.”
- Target environments: enterprise RAG, support agents, developer agents, MCP integrations.
- Product cards: manifest scan, runtime response guard, audit trail, action-policy gate.
- Honest disclaimer: demonstration/research prototype; detection complements least privilege, approval, and server-side access control.

## 10. Risk controls and fallback decisions

| Risk | Decision |
|---|---|
| Benchmark loading takes too long | Use BIPIA plus one tool dataset; document the reduced scope. |
| GPU unavailable | Fine-tune DistilRoBERTa on a smaller corpus or use a frozen sentence-encoder baseline. |
| Hybrid does not beat transformer | Report it as an interpretability/latency trade-off; do not manufacture a gain. |
| Rules create high false positives | Keep only high-precision rules in fusion; report discarded rules as failed ablations. |
| MCP benchmark is difficult to execute | Use safely replayed JSON fixtures and clearly call them MCP-style, not live MCP evaluation. |
| UI is delayed | Deliver a simple Streamlit/local web interface before optional landing content. |
| Time runs short | Preserve: corpus, TF-IDF, one transformer, rule trace, one RAG demo, one MCP JSON demo, and honest metrics. |

## 11. Completion standard

The project is complete only when:

- Every final metric has a reproducible command, fixed split, and logged seed.
- No test data is used for threshold selection or design changes.
- The model’s limits and false-positive behaviour are stated in the report and demo.
- The demo runs offline from a clean setup, or has a tested recorded fallback.
- The team can explain each model, rule, metric, and demo decision without relying on generated text.
