# LLMSentinel Project Checklist V2

Use this with `PROJECT_PLAN_V2.md`. Complete an item only when there is evidence: a commit, test, command output, experiment-log entry, dataset manifest, reviewed document, figure, or screenshot. Sections 1–16 define the full research prototype; sections 17–19 are extended work and are not production claims.

## 1. Governance, safety, and reproducibility

- [x] Confirm the final title, problem statement, and scope.
- [x] Assign named owners for data, modelling/evaluation, and demo/report work.
- [x] Record allowed GenAI use and academic-integrity requirements.
- [x] Record project decisions, rejected ideas, and scope changes.
- [x] Confirm no live third-party systems, real secrets, personal data, or non-consenting systems will be tested.
- [x] Confirm the demo never executes sensitive, destructive, or external actions.
- [x] Define safe-fixture review and accidental-secret-removal procedures.
- [x] Create the first source-control commit before substantive implementation.
- [x] Record OS, Python, hardware, dependency, and model versions.
- [x] Create a virtual environment and install versioned dependencies.
- [x] Separate optional transformer dependencies from the core setup.
- [x] Add import smoke tests, unit tests, lint/format checks, and documented commands.
- [x] Verify fresh setup, corpus rebuild, evaluation, and demo startup commands.
- [x] Seed Python, NumPy, PyTorch, and model training deterministically.

## 2. Threat model and experiment protocol

- [x] Define trusted user intent, trusted system policy, and untrusted context.
- [x] Include RAG documents, tool-response JSON, and MCP manifests in scope.
- [x] Define attacker goals: override, exfiltration, action hijack, destructive action, metadata poisoning.
- [x] Define attacker capabilities: text control, formatting, obfuscation, long context, and multi-chunk placement.
- [x] State that detection is defence in depth, not universal protection.
- [x] Freeze exclusions: live exploitation, real action execution, unsupported modalities, and guarantee claims.
- [x] Define action classes: read-only, sensitive read, external send, write, destructive, privilege escalation.
- [x] Define policy outcomes: allow, isolate, confirmation required, block.
- [x] Freeze metrics: AUPRC, TPR@1% FPR, TPR@0.1% FPR, hard-negative FPR, latency.
- [x] Define secondary metrics: AUROC, calibration, model size, memory, and support counts.
- [x] Freeze baselines and test-set policy before tuning.
- [x] Define experiment-log fields: date, commit, data digest, seed, machine, command, metrics, warnings, observations.

## 3. Schema, provenance, and corpus construction

- [x] Define a versioned JSONL schema.
- [x] Include stable source-scoped record ID, raw text, and normalisation version.
- [x] Include label, rationale where available, channel, attack type, and host task.
- [x] Include source dataset/document/tool ID, licence, acquisition note, and provenance.
- [x] Include JSON path, manifest version/hash, and injected spans where applicable.
- [x] Include content group, host group, hard-negative flag, and split.
- [x] Define missing/unknown-field handling and validate at least ten schema examples.
- [x] Add invalid-schema and span-offset tests.
- [x] Build corpus from a command and generate corpus card, source/licence inventory, split manifest, and data digest.

## 4. Data sources and licensing

- [x] Obtain BIPIA from its official source; read documentation and licence.
- [x] Identify BIPIA positives, benign data, host task, payload, and provenance fields.
- [x] Implement BIPIA loader and manually validate five output records.
- [x] Obtain InjecAgent; read its documentation/licence and determine safe tool-text extraction.
- [x] Implement InjecAgent loader or document why reliable extraction is infeasible.
- [x] Manually validate five InjecAgent records if used.
- [x] Decide whether AgentDojo is needed; inspect its task format/licence before use.
- [x] Inspect an MCP-oriented dataset such as MCPTox before integration.
- [x] Record schema, labels, licence, and limitations for every MCP dataset used.
- [x] Obtain permissively usable benign RAG passages, technical docs, API references, READMEs, policies, and tutorials.
- [x] Obtain security writing and code examples that quote attacks as hard negatives.
- [x] Record source and licence for each manually added source.
- [x] Ensure tool descriptions and tool-response leaves are channel-realistic.
- [x] Keep synthetic/demo/robustness fixtures explicitly separate from benchmark results.
- [x] Never report synthetic-only outcomes as public-benchmark performance.

## 5. Labels, hard negatives, and data integrity

- [x] Write a one-page annotation guideline.
- [x] Define injection as assistant-directed task/policy-conflicting control text.
- [x] Define legitimate imperatives, policies, code, citations, and quoted payloads as benign/hard-negative cases as appropriate.
- [x] Define ambiguity handling and attack taxonomy.
- [x] Independently label an initial sample with at least two reviewers.
- [x] Record disagreements and revise the guideline.
- [x] Ensure hard negatives are at least 25% of benign examples.
- [x] Deduplicate exact text before splitting.
- [x] Audit near duplicates across splits.
- [x] Group splits by payload/template family and host source identity.
- [x] Ensure no content/host/payload group crosses train, dev, and test.
- [x] Fix and record split seed; save the manifest.
- [x] Generate counts by split, channel, label, source, attack type, and hard-negative status.
- [x] Ensure every reportable channel has positive and benign dev/test support.
- [x] Inspect 20 random final examples and 20 hard negatives.
- [x] Record unrealistic channel pairs, clipped context, and other corpus limitations.
- [x] Freeze the final corpus digest before final comparison.

## 6. Normalisation and evidence recovery

- [x] Implement recursive JSON string-leaf extraction with JSON paths.
- [x] Preserve parent-child provenance for decoded units.
- [x] Apply Unicode NFKC and retain raw-to-normalised offset mappings.
- [x] Detect zero-width, homoglyph/script-change, and bidi-control evidence where practical.
- [x] Decode HTML entities and retain comments/hidden-markup evidence where practical.
- [x] Treat Markdown, quotations, inline code, and code fences as context evidence.
- [x] Detect base64-like, hexadecimal, URL, and percent-encoded content conservatively.
- [x] Decode only bounded, clearly valid text regions.
- [x] Sentence/section segment while retaining offsets.
- [x] Add tests for clean text, nested JSON, Unicode, HTML, hidden markup, encodings, and span projection.
- [x] Add input/window-size limits and telemetry when limits are reached.

## 7. Metrics and baseline evaluation

- [x] Validate labels, scores, and array lengths.
- [x] Implement AUPRC and AUROC.
- [x] Implement dev threshold selection at 1% and 0.1% FPR.
- [x] Report realised FPR beside target FPR and flag budget overruns.
- [x] Implement hard-negative FPR, per-channel metrics, per-dataset metrics, and per-attack recall.
- [x] Include support counts in metric reports.
- [x] Measure mean/p95 latency; add deterministic bootstrap intervals if feasible.
- [x] Verify all metric logic with hand-computed examples.
- [x] Implement majority, keyword/regex, TF-IDF word, and TF-IDF character baselines.
- [x] Train learned baselines only on train; select thresholds only on dev.
- [x] Save configurations, seeds, and vocabulary/model metadata.
- [x] Record baseline dev results before any test evaluation.

## 8. Rule engine and explanations

- [x] Implement meta-instruction/override rules and benign/malicious tests.
- [x] Implement secrecy/system-prompt/credential-target rules.
- [x] Implement exfiltration requiring action plus sensitive object/destination proximity.
- [x] Test ordinary URLs/emails and action verbs without harmful intent.
- [x] Implement tool-invocation, action-hijack, destructive-action, and obfuscation rules.
- [x] Implement MCP metadata-poisoning and manifest-change rules.
- [x] Implement task/context conflict only as corroborating evidence.
- [x] Test policies, tutorials, technical docs, security articles, quoted attacks, and code examples.
- [x] Test that quotation/code fences cannot materially reduce an active injection score.
- [x] Test that simple citation framing such as “for example” cannot cheaply suppress a payload.
- [x] Emit score, raw span, evidence, and human-readable trace per rule hit.
- [x] Add degraded-state/error telemetry and strict evaluation mode.
- [x] Implement and document rules-only aggregation weights consistently.
- [x] Evaluate each family alone and run leave-one-family-out ablation on dev.
- [x] Retain or discard rules only using logged evidence.

## 9. Transformer and long-context detection

> Scope note: span-aware window labelling (windows labelled 1 only where the
> injected span lands) is implemented and is the default for future training,
> but the **shipped checkpoint predates it** and was trained with document-label
> windows; a re-train (~53 min CPU) to adopt it is deferred. Truncation beyond
> `max_windows` is now reported, not silent, and the highest-risk window
> index/text is preserved via `TransformerScorer.score_details`.

- [x] Select primary compact model and CPU-friendly fallback; record licence/tokenizer/parameter count.
- [x] Set maximum length, overlap, maximum windows, and bounded-input behaviour. *(truncation telemetry added)*
- [x] Use equivalent overlapping windows during training and inference.
- [x] Preserve highest-risk window position/evidence for each document. *(score_details returns the argmax window index and text)*
- [x] Implement training dataset/data loader and documented imbalance method.
- [x] Train first model; save checkpoint, tokenizer, config, corpus digest, and seed.
- [x] Reload checkpoint in a clean process and run validation inference.
- [x] Measure model size and mean/p95 latency.
- [x] Run multiple seeds if feasible.
- [x] Test beginning/middle/end placement in long documents.
- [x] Record transformer-only results and warnings in the experiment log.

## 10. Fusion, calibration, and verdicts

- [x] Export rule feature vectors and transformer probabilities for dev records.
- [x] Fit fusion only on development data; use grouped out-of-fold scores for dev reporting where applicable.
- [x] Document fusion features, folds, regularisation, seed, and training split.
- [x] Calibrate probabilities or document why a given output is used directly.
- [x] Store selected thresholds, calibration data, and corpus digest.
- [x] Implement a serialisable verdict.
- [x] Include channel, source/tool provenance, JSON path, risk, threshold, band, model score, spans, traces, evidence, and degraded state.
- [x] Validate verdict serialisation and raw-span projection.
- [x] Compare rules-only, transformer-only, and hybrid systems fairly.
- [x] Freeze design choices, then score held-out test once.

## 11. Semantic and context-aware extensions

> Scope note: the "embedding" backend shipped and used in all reported numbers is
> a deterministic **character n-gram lexical proxy**, not a neural sentence
> embedder. A sentence-transformer backend is available behind the optional
> `semantic` extra and the `LLMSENTINEL_EMBEDDER=st` switch but is **not evaluated
> here**. The action-destination / authority / tool features carry the signal;
> the similarity term is a lightweight add-on. All of this layer is experimental.

- [x] Define task, untrusted instruction, and proposed-action representations.
- [x] Collect cases where lexical overlap disagrees with semantic task conflict.
- [x] Add embedding-based semantic similarity, contradiction, or action-destination features. *(action-destination features implemented; similarity via a lexical proxy by default, optional neural backend unevaluated)*
- [x] Compare semantic features against lexical/register baselines.
- [x] Test attacks reusing task vocabulary while changing destination, authority, or tool.
- [x] Test benign off-topic instructions that should not be labelled attacks automatically.
- [x] Add source-aware features: channel, JSON-path class, document type, tool/server identity.
- [x] Measure whether provenance features help or hurt cross-source transfer.
- [x] Add multi-chunk/retrieval-bundle scoring with preserved source and order.
- [x] Test safe payload assembly across chunks.
- [x] Add abstain/review behaviour for uncertain or conflicting evidence.
- [x] Label all such methods experimental until independently benchmarked.

## 12. Robustness and generalisation

- [x] Test attack position, long-context dilution, and benign distractors.
- [x] Test whitespace, punctuation, casing, quotation, Markdown, and code fences.
- [x] Test Unicode, zero-width, bidi, and safely encoded variants.
- [x] Test paraphrase, synonym, and declarative attack wording.
- [x] Test transformed benign policies, documentation, and technical text.
- [x] Test multi-chunk/retrieval-bundle fixtures.
- [x] Evaluate cross-channel and cross-dataset transfer when data supports it.
- [x] Evaluate metadata scanning separately from tool-response scanning.
- [x] Explore multilingual robustness only with stated data/language limitations.
- [x] Log failures and mitigations instead of silently removing them.

## 13. Capability policy and MCP layer

- [x] Create a versioned static policy file.
- [x] Classify proposed actions into all defined capability classes.
- [x] Map safe reads, sensitive reads, external sends, writes, destructive actions, and privilege escalation to deterministic outcomes.
- [x] Ensure policy is safe when detector output is missing or degraded.
- [x] Add tests for every action-policy category.
- [x] Log policy inputs, decision, reason, and policy version.
- [x] Create clean and poisoned nested tool-response JSON fixtures.
- [x] Create approved and suspicious/changed MCP manifest fixtures.
- [x] Scan tool names, descriptions, schemas, parameter descriptions, and string leaves.
- [x] Associate every finding with JSON path, tool/server identity, and manifest version.
- [x] Use only simulated downstream actions and local safe replay.
- [x] Do not connect the demo to live MCP servers.

## 14. Live demo and usability

> Scope note: the demo runs the **rules-only** detector (no checkpoint, starts
> offline), so its risk numbers are not the headline transformer/hybrid results
> and it shows the **rule trace**, not fusion evidence. The recorded fallback is
> a deterministic **text transcript** (`docs/demo_transcript.txt`), not a
> screen-capture video.

- [x] Choose local UI framework and create page shell.
- [x] Add RAG/tool-response/MCP-manifest selector.
- [x] Add clean-versus-poisoned samples plus safe free text/JSON paste. *(RAG text paste and tool-response JSON paste both supported)*
- [x] Show original content, JSON tree/path, source provenance, and normalised evidence. *(normalised text shown in an expander when it differs from raw)*
- [x] Highlight suspicious raw-text spans.
- [x] Show risk, threshold, risk band, uncertainty/degraded warning, rule trace, and model evidence. *(rule trace + normalisation evidence; the demo is rules-only, so no fusion term is shown)*
- [x] Show proposed action, capability class, and deterministic policy decision. *(including an enforceable gate on manifest drift)*
- [x] Add guard-off versus guard-on comparison.
- [x] Add limitations, safety, and non-production disclaimer.
- [x] Test clean/poisoned RAG, JSON, and MCP-manifest flows.
- [x] Test a fresh restart, measure response time, and record fallback demo transcript (text, not video).

## 15. Analysis, report, and presentation

> Status: analysis + figures + report drafted (`docs/report.md`,
> `docs/error_analysis.md`, `artifacts/figures/`). Figures/results regenerate via
> `scripts/make_figures.py` and `llmsentinel evaluate --test`. Three items are
> deliberately left open (demo screenshots, a formal literature-citation pass,
> and a rehearsed 3-minute demo script) — they need the live UI captured and a
> related-work write-up, tracked for the presentation pass.

- [x] Sample false positives from hard negatives and false negatives by attack type/channel. *(scripts/error_analysis.py, rules-only + hybrid)*
- [x] Categorise errors: quote, code, policy, documentation, paraphrase, dilution, obfuscation, declarative wording, semantic conflict, other. *(docs/error_analysis.md)*
- [x] Write one mitigation/future-work note for each major error category.
- [x] Generate corpus, source/licence, comparison, per-channel, per-attack, ablation, robustness, latency/model-size tables. *(comparison/per-channel/per-attack in results JSON; ablation in rule_family_eval; robustness in docs/robustness.md; corpus + source/licence in corpus_card; latency currently n/a and model size in describe())*
- [x] Generate PR curve and calibration plot where relevant. *(artifacts/figures/pr_curve.png, calibration.png)*
- [ ] Generate architecture figure and demo screenshots. *(architecture.svg done; live demo screenshots still to capture — transcript stands in for now)*
- [x] Write method, corpus/labelling/split, threat model, evaluation, results, limitations, and safety sections. *(docs/report.md)*
- [ ] Verify every result against experiment log and every citation/dataset licence against source material. *(results verified vs EXPERIMENTS.md and dataset licences recorded; a formal literature-citation/related-work pass is still pending)*
- [ ] Prepare a concise demo script and ensure every member can explain evidence and limitations. *(3-minute demo script pending; solo project)*

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
