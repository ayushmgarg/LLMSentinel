# LLMSentinel Project Checklist V2

Use this with `PROJECT_PLAN_V2.md`. Complete an item only when there is evidence: a commit, test, command output, experiment-log entry, dataset manifest, reviewed document, figure, or screenshot. Sections 1–16 define the full research prototype; sections 17–19 are extended work and are not production claims.

## 1. Governance, safety, and reproducibility

- [ ] Confirm the final title, problem statement, and scope.
- [ ] Assign named owners for data, modelling/evaluation, and demo/report work.
- [ ] Record allowed GenAI use and academic-integrity requirements.
- [ ] Record project decisions, rejected ideas, and scope changes.
- [ ] Confirm no live third-party systems, real secrets, personal data, or non-consenting systems will be tested.
- [ ] Confirm the demo never executes sensitive, destructive, or external actions.
- [ ] Define safe-fixture review and accidental-secret-removal procedures.
- [ ] Create the first source-control commit before substantive implementation.
- [ ] Record OS, Python, hardware, dependency, and model versions.
- [ ] Create a virtual environment and install versioned dependencies.
- [ ] Separate optional transformer dependencies from the core setup.
- [ ] Add import smoke tests, unit tests, lint/format checks, and documented commands.
- [ ] Verify fresh setup, corpus rebuild, evaluation, and demo startup commands.
- [ ] Seed Python, NumPy, PyTorch, and model training deterministically.

## 2. Threat model and experiment protocol

- [ ] Define trusted user intent, trusted system policy, and untrusted context.
- [ ] Include RAG documents, tool-response JSON, and MCP manifests in scope.
- [ ] Define attacker goals: override, exfiltration, action hijack, destructive action, metadata poisoning.
- [ ] Define attacker capabilities: text control, formatting, obfuscation, long context, and multi-chunk placement.
- [ ] State that detection is defence in depth, not universal protection.
- [ ] Freeze exclusions: live exploitation, real action execution, unsupported modalities, and guarantee claims.
- [ ] Define action classes: read-only, sensitive read, external send, write, destructive, privilege escalation.
- [ ] Define policy outcomes: allow, isolate, confirmation required, block.
- [ ] Freeze metrics: AUPRC, TPR@1% FPR, TPR@0.1% FPR, hard-negative FPR, latency.
- [ ] Define secondary metrics: AUROC, calibration, model size, memory, and support counts.
- [ ] Freeze baselines and test-set policy before tuning.
- [ ] Define experiment-log fields: date, commit, data digest, seed, machine, command, metrics, warnings, observations.

## 3. Schema, provenance, and corpus construction

- [ ] Define a versioned JSONL schema.
- [ ] Include stable source-scoped record ID, raw text, and normalisation version.
- [ ] Include label, rationale where available, channel, attack type, and host task.
- [ ] Include source dataset/document/tool ID, licence, acquisition note, and provenance.
- [ ] Include JSON path, manifest version/hash, and injected spans where applicable.
- [ ] Include content group, host group, hard-negative flag, and split.
- [ ] Define missing/unknown-field handling and validate at least ten schema examples.
- [ ] Add invalid-schema and span-offset tests.
- [ ] Build corpus from a command and generate corpus card, source/licence inventory, split manifest, and data digest.

## 4. Data sources and licensing

- [ ] Obtain BIPIA from its official source; read documentation and licence.
- [ ] Identify BIPIA positives, benign data, host task, payload, and provenance fields.
- [ ] Implement BIPIA loader and manually validate five output records.
- [ ] Obtain InjecAgent; read its documentation/licence and determine safe tool-text extraction.
- [ ] Implement InjecAgent loader or document why reliable extraction is infeasible.
- [ ] Manually validate five InjecAgent records if used.
- [ ] Decide whether AgentDojo is needed; inspect its task format/licence before use.
- [ ] Inspect an MCP-oriented dataset such as MCPTox before integration.
- [ ] Record schema, labels, licence, and limitations for every MCP dataset used.
- [ ] Obtain permissively usable benign RAG passages, technical docs, API references, READMEs, policies, and tutorials.
- [ ] Obtain security writing and code examples that quote attacks as hard negatives.
- [ ] Record source and licence for each manually added source.
- [ ] Ensure tool descriptions and tool-response leaves are channel-realistic.
- [ ] Keep synthetic/demo/robustness fixtures explicitly separate from benchmark results.
- [ ] Never report synthetic-only outcomes as public-benchmark performance.

## 5. Labels, hard negatives, and data integrity

- [ ] Write a one-page annotation guideline.
- [ ] Define injection as assistant-directed task/policy-conflicting control text.
- [ ] Define legitimate imperatives, policies, code, citations, and quoted payloads as benign/hard-negative cases as appropriate.
- [ ] Define ambiguity handling and attack taxonomy.
- [ ] Independently label an initial sample with at least two reviewers.
- [ ] Record disagreements and revise the guideline.
- [ ] Ensure hard negatives are at least 25% of benign examples.
- [ ] Deduplicate exact text before splitting.
- [ ] Audit near duplicates across splits.
- [ ] Group splits by payload/template family and host source identity.
- [ ] Ensure no content/host/payload group crosses train, dev, and test.
- [ ] Fix and record split seed; save the manifest.
- [ ] Generate counts by split, channel, label, source, attack type, and hard-negative status.
- [ ] Ensure every reportable channel has positive and benign dev/test support.
- [ ] Inspect 20 random final examples and 20 hard negatives.
- [ ] Record unrealistic channel pairs, clipped context, and other corpus limitations.
- [ ] Freeze the final corpus digest before final comparison.

## 6. Normalisation and evidence recovery

- [ ] Implement recursive JSON string-leaf extraction with JSON paths.
- [ ] Preserve parent-child provenance for decoded units.
- [ ] Apply Unicode NFKC and retain raw-to-normalised offset mappings.
- [ ] Detect zero-width, homoglyph/script-change, and bidi-control evidence where practical.
- [ ] Decode HTML entities and retain comments/hidden-markup evidence where practical.
- [ ] Treat Markdown, quotations, inline code, and code fences as context evidence.
- [ ] Detect base64-like, hexadecimal, URL, and percent-encoded content conservatively.
- [ ] Decode only bounded, clearly valid text regions.
- [ ] Sentence/section segment while retaining offsets.
- [ ] Add tests for clean text, nested JSON, Unicode, HTML, hidden markup, encodings, and span projection.
- [ ] Add input/window-size limits and telemetry when limits are reached.

## 7. Metrics and baseline evaluation

- [ ] Validate labels, scores, and array lengths.
- [ ] Implement AUPRC and AUROC.
- [ ] Implement dev threshold selection at 1% and 0.1% FPR.
- [ ] Report realised FPR beside target FPR and flag budget overruns.
- [ ] Implement hard-negative FPR, per-channel metrics, per-dataset metrics, and per-attack recall.
- [ ] Include support counts in metric reports.
- [ ] Measure mean/p95 latency; add deterministic bootstrap intervals if feasible.
- [ ] Verify all metric logic with hand-computed examples.
- [ ] Implement majority, keyword/regex, TF-IDF word, and TF-IDF character baselines.
- [ ] Train learned baselines only on train; select thresholds only on dev.
- [ ] Save configurations, seeds, and vocabulary/model metadata.
- [ ] Record baseline dev results before any test evaluation.

## 8. Rule engine and explanations

- [ ] Implement meta-instruction/override rules and benign/malicious tests.
- [ ] Implement secrecy/system-prompt/credential-target rules.
- [ ] Implement exfiltration requiring action plus sensitive object/destination proximity.
- [ ] Test ordinary URLs/emails and action verbs without harmful intent.
- [ ] Implement tool-invocation, action-hijack, destructive-action, and obfuscation rules.
- [ ] Implement MCP metadata-poisoning and manifest-change rules.
- [ ] Implement task/context conflict only as corroborating evidence.
- [ ] Test policies, tutorials, technical docs, security articles, quoted attacks, and code examples.
- [ ] Test that quotation/code fences cannot materially reduce an active injection score.
- [ ] Test that simple citation framing such as “for example” cannot cheaply suppress a payload.
- [ ] Emit score, raw span, evidence, and human-readable trace per rule hit.
- [ ] Add degraded-state/error telemetry and strict evaluation mode.
- [ ] Implement and document rules-only aggregation weights consistently.
- [ ] Evaluate each family alone and run leave-one-family-out ablation on dev.
- [ ] Retain or discard rules only using logged evidence.

## 9. Transformer and long-context detection

- [ ] Select primary compact model and CPU-friendly fallback; record licence/tokenizer/parameter count.
- [ ] Set maximum length, overlap, maximum windows, and bounded-input behaviour.
- [ ] Use equivalent overlapping windows during training and inference.
- [ ] Preserve highest-risk window position/evidence for each document.
- [ ] Implement training dataset/data loader and documented imbalance method.
- [ ] Train first model; save checkpoint, tokenizer, config, corpus digest, and seed.
- [ ] Reload checkpoint in a clean process and run validation inference.
- [ ] Measure model size and mean/p95 latency.
- [ ] Run multiple seeds if feasible.
- [ ] Test beginning/middle/end placement in long documents.
- [ ] Record transformer-only results and warnings in the experiment log.

## 10. Fusion, calibration, and verdicts

- [ ] Export rule feature vectors and transformer probabilities for dev records.
- [ ] Fit fusion only on development data; use grouped out-of-fold scores for dev reporting where applicable.
- [ ] Document fusion features, folds, regularisation, seed, and training split.
- [ ] Calibrate probabilities or document why a given output is used directly.
- [ ] Store selected thresholds, calibration data, and corpus digest.
- [ ] Implement a serialisable verdict.
- [ ] Include channel, source/tool provenance, JSON path, risk, threshold, band, model score, spans, traces, evidence, and degraded state.
- [ ] Validate verdict serialisation and raw-span projection.
- [ ] Compare rules-only, transformer-only, and hybrid systems fairly.
- [ ] Freeze design choices, then score held-out test once.

## 11. Semantic and context-aware extensions

- [ ] Define task, untrusted instruction, and proposed-action representations.
- [ ] Collect cases where lexical overlap disagrees with semantic task conflict.
- [ ] Add embedding-based semantic similarity, contradiction, or action-destination features.
- [ ] Compare semantic features against lexical/register baselines.
- [ ] Test attacks reusing task vocabulary while changing destination, authority, or tool.
- [ ] Test benign off-topic instructions that should not be labelled attacks automatically.
- [ ] Add source-aware features: channel, JSON-path class, document type, tool/server identity.
- [ ] Measure whether provenance features help or hurt cross-source transfer.
- [ ] Add multi-chunk/retrieval-bundle scoring with preserved source and order.
- [ ] Test safe payload assembly across chunks.
- [ ] Add abstain/review behaviour for uncertain or conflicting evidence.
- [ ] Label all such methods experimental until independently benchmarked.

## 12. Robustness and generalisation

- [ ] Test attack position, long-context dilution, and benign distractors.
- [ ] Test whitespace, punctuation, casing, quotation, Markdown, and code fences.
- [ ] Test Unicode, zero-width, bidi, and safely encoded variants.
- [ ] Test paraphrase, synonym, and declarative attack wording.
- [ ] Test transformed benign policies, documentation, and technical text.
- [ ] Test multi-chunk/retrieval-bundle fixtures.
- [ ] Evaluate cross-channel and cross-dataset transfer when data supports it.
- [ ] Evaluate metadata scanning separately from tool-response scanning.
- [ ] Explore multilingual robustness only with stated data/language limitations.
- [ ] Log failures and mitigations instead of silently removing them.

## 13. Capability policy and MCP layer

- [ ] Create a versioned static policy file.
- [ ] Classify proposed actions into all defined capability classes.
- [ ] Map safe reads, sensitive reads, external sends, writes, destructive actions, and privilege escalation to deterministic outcomes.
- [ ] Ensure policy is safe when detector output is missing or degraded.
- [ ] Add tests for every action-policy category.
- [ ] Log policy inputs, decision, reason, and policy version.
- [ ] Create clean and poisoned nested tool-response JSON fixtures.
- [ ] Create approved and suspicious/changed MCP manifest fixtures.
- [ ] Scan tool names, descriptions, schemas, parameter descriptions, and string leaves.
- [ ] Associate every finding with JSON path, tool/server identity, and manifest version.
- [ ] Use only simulated downstream actions and local safe replay.
- [ ] Do not connect the demo to live MCP servers.

## 14. Live demo and usability

- [ ] Choose local UI framework and create page shell.
- [ ] Add RAG/tool-response/MCP-manifest selector.
- [ ] Add clean-versus-poisoned samples plus safe free text/JSON paste.
- [ ] Show original content, JSON tree/path, source provenance, and normalised evidence.
- [ ] Highlight suspicious raw-text spans.
- [ ] Show risk, threshold, risk band, uncertainty/degraded warning, rule trace, and model/fusion evidence.
- [ ] Show proposed action, capability class, and deterministic policy decision.
- [ ] Add guard-off versus guard-on comparison.
- [ ] Add limitations, safety, and non-production disclaimer.
- [ ] Test clean/poisoned RAG, JSON, and MCP-manifest flows.
- [ ] Test a fresh restart, measure response time, and record fallback demo video.

## 15. Analysis, report, and presentation

- [ ] Sample false positives from hard negatives and false negatives by attack type/channel.
- [ ] Categorise errors: quote, code, policy, documentation, paraphrase, dilution, obfuscation, declarative wording, semantic conflict, other.
- [ ] Write one mitigation/future-work note for each major error category.
- [ ] Generate corpus, source/licence, comparison, per-channel, per-attack, ablation, robustness, latency/model-size tables.
- [ ] Generate PR curve and calibration plot where relevant.
- [ ] Generate architecture figure and demo screenshots.
- [ ] Write method, corpus/labelling/split, threat model, evaluation, results, limitations, and safety sections.
- [ ] Verify every result against experiment log and every citation/dataset licence against source material.
- [ ] Prepare a concise demo script and ensure every member can explain evidence and limitations.

## 16. Optional product framing

- [ ] Add only after the demo and evidence are stable.
- [ ] Label the page a research prototype.
- [ ] Describe target users: enterprise RAG, support agents, developer agents, MCP integrations.
- [ ] Describe capabilities: manifest scan, runtime context scan, provenance/audit trace, deterministic action gate.
- [ ] State that least privilege, approval, and server-side authorisation remain necessary.
- [ ] Do not claim customers, certifications, pricing, benchmark leadership, production readiness, or guaranteed security.

## 17. Analyst workflow extensions

- [ ] Design local scan-history storage with verdict, policy, provenance, timestamp, and version data.
- [ ] Add filters by channel, source/tool, attack type, action class, and decision.
- [ ] Add analyst review queue for elevated/uncertain cases.
- [ ] Add safe verdict override with reviewer rationale while retaining original verdict.
- [ ] Add aggregation by tool, server, source domain, and attack family.
- [ ] Add local manifest-change alerts and regression fixtures for discovered safe attack patterns.
- [ ] Add Python SDK/local proxy interface only after core evaluation is stable.
- [ ] Document that an SDK/demo proxy is not production enforcement.

## 18. Longer-term research boundary

- [ ] Design multi-turn attack representation and multi-agent trust/provenance tracking.
- [ ] Collect sufficient data for multi-turn/multi-agent evaluation.
- [ ] Study multilingual and multimodal prompt injection separately with suitable benchmarks.
- [ ] Study adaptive/white-box attacker robustness under an approved safe protocol.
- [ ] Design production proxy concerns: authentication, streaming, tenant isolation, availability, fail-open/fail-closed behaviour.
- [ ] Investigate authorised secret redaction, network egress restriction, server-side authorisation, and sandboxing as separate security-engineering work.
- [ ] Design privacy-preserving monitoring and conduct broader annotation/human-review studies before production claims.
- [ ] Establish evidence required for certifications, SLAs, and any commercial security claim.

## 19. Final completion criteria

- [ ] Every final result has reproducible command, fixed corpus digest, seed, and log entry.
- [ ] Test data did not influence design, threshold, retained-rule, or final-report choices.
- [ ] Public datasets/licences are accurate; synthetic and benchmark results are clearly separated.
- [ ] Baseline, rules-only, transformer-only, and hybrid comparisons are fair.
- [ ] Robustness and error analysis include failures as well as successes.
- [ ] Verdicts preserve provenance, evidence, spans, and degraded state.
- [ ] Policy decisions are deterministic and simulated.
- [ ] Fresh setup runs the demo or a tested video fallback exists.
- [ ] README, dependencies, tests, lint/format checks, and report evidence are current.
- [ ] Final report explicitly states that LLMSentinel is defence in depth, not complete prompt-injection protection.
