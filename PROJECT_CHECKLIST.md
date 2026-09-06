# LLMSentinel Project Checklist

Use this as the team’s execution checklist. Do not mark an item complete until there is evidence: a commit, command output, test, screenshot, experiment-log entry, or reviewed document.

## Project controls

- [ ] Confirm the final project title.
- [ ] Confirm the project is limited to detection, explanation, and demo-only policy decisions.
- [ ] Confirm no one will test against live services, real secrets, or non-consenting systems.
- [ ] Create a shared team communication channel.
- [ ] Assign Person A, Person B, and optional Person C responsibilities.
- [ ] Agree on a weekly review time.
- [ ] Agree on a daily short status-update format: done, blocked, next.
- [ ] Confirm the final deadline and reserve the last two days for demo/rehearsal only.
- [ ] Read the course policy and record allowed GenAI use and academic-integrity obligations.
- [ ] Read the project plan fully before coding.

## Week 1 - setup and data

### Repository and environment

- [x] Inspect the existing repository without deleting generated files.
- [ ] Create the first git commit before substantive implementation begins.
- [x] Confirm Python version supported by PyTorch, spaCy, and transformers.
- [x] Create a virtual environment.
- [x] Install package dependencies.
- [ ] Install the spaCy English model.
- [ ] Download required NLTK resources only if they are used.
- [x] Run package import test.
- [x] Run lint/test commands and record the initial result.
- [x] Add a short local setup section if the existing README is inaccurate.

### Research protocol freeze

- [x] Freeze the threat model.
- [x] Freeze included source categories: RAG, tool response, MCP metadata.
- [x] Freeze exclusions: live servers, images/audio, universal-defense claims, automatic sensitive actions.
- [x] Freeze primary metrics: AUPRC, TPR@1% FPR, TPR@0.1% FPR, hard-negative FPR, latency.
- [x] Freeze the initial baselines.
- [x] Define the action categories: read-only, sensitive read, external send, write, destructive.
- [x] Define policy outcomes: allow, isolate, confirmation, block.
- [x] Create an experiment-log convention: date, commit hash, data version, seed, command, metrics, observation.

### Unified corpus schema

- [x] Write the exact JSONL schema.
- [x] Include stable record ID.
- [x] Include raw text.
- [x] Include normalised text or reproducible normalisation version.
- [x] Include label.
- [x] Include channel/source type.
- [x] Include attack type.
- [x] Include host task where known.
- [x] Include source dataset/document ID.
- [x] Include source licence/usage note.
- [x] Include JSON path for tool/metadata records.
- [x] Include injected-span offsets when available.
- [x] Include split field.
- [x] Decide how unknown fields are represented.
- [x] Validate ten hand-written schema examples.

### Data acquisition and inspection

- [ ] Download or clone BIPIA using its official source.
- [ ] Read BIPIA data documentation and licence.
- [ ] Identify BIPIA positive, benign, host-task, and payload fields.
- [x] Implement a BIPIA loader.
- [ ] Validate five loaded BIPIA records manually.
- [ ] Download or clone InjecAgent using its official source.
- [ ] Read InjecAgent data documentation and licence.
- [ ] Identify whether its cases expose extractable tool-response text.
- [x] Implement an InjecAgent loader or explicitly document why extraction is not practical.
- [ ] Decide whether AgentDojo is needed for Week 4 end-to-end evaluation.
- [ ] Inspect MCPTox schema before promising tool-metadata integration.
- [ ] Obtain benign RAG passages from a documented public source.
- [x] Obtain benign technical documentation/README/API examples from a permitted source.
- [x] Obtain benign policy/tutorial examples.
- [x] Collect examples that quote prompt-injection strings for hard negatives.
- [x] Record source and licence for every manually added source.

### Labels and splits

- [x] Write a one-page annotation guideline.
- [x] Define injection-bearing text as task-conflicting assistant-directed control content, not mere discussion of attacks.
- [x] Define benign imperative examples.
- [x] Define quoted attack examples as hard negatives unless they direct the active assistant.
- [ ] Label an initial 50 examples independently by two team members.
- [ ] Resolve disagreements and refine the guideline.
- [ ] Label at least 200 reviewable examples if manual labels are needed.
- [x] Ensure at least 25% of benign records are hard negatives.
- [x] Deduplicate exact text before splitting.
- [x] Group split by payload/template family.
- [x] Group split by host document ID.
- [x] Fix split seed and save split manifest.
- [x] Verify no group crosses train/dev/test.
- [x] Generate corpus counts by split, channel, label, attack type, and source.
- [x] Manually inspect 20 random records after final corpus build.
- [x] Manually inspect 20 hard negatives after final corpus build.

### Normalisation MVP

- [x] Implement JSON recursive string-leaf extraction.
- [x] Preserve JSON path for every extracted string.
- [x] Apply Unicode NFKC normalisation.
- [x] Detect and remove zero-width characters while retaining an evidence flag.
- [x] Detect suspicious homoglyph/Unicode changes if practical.
- [x] Decode HTML entities.
- [x] Preserve comment/hidden-markup evidence where practical.
- [x] Detect base64-like text conservatively.
- [x] Decode only safely valid text encodings.
- [x] Preserve parent-child relationship for derived decoded spans.
- [x] Sentence-segment text while retaining character offsets.
- [x] Write tests for clean text, JSON, zero-width text, HTML entity text, and encoded text.

### Week 1 exit review

- [x] Corpus builds from a command.
- [x] Corpus card/count report is generated.
- [x] Leakage checks pass.
- [x] Keyword baseline runs.
- [x] TF-IDF baseline runs.
- [x] Initial results are logged.
- [ ] Team decides whether scope remains on schedule.

## Week 2 - detector MVP

### Evaluation harness

- [x] Implement binary labels and score input validation.
- [x] Implement AUPRC.
- [x] Implement AUROC for comparison only.
- [x] Implement TPR@1% FPR.
- [x] Implement TPR@0.1% FPR.
- [x] Implement hard-negative FPR.
- [x] Implement per-channel metrics.
- [x] Implement per-attack-type recall.
- [x] Implement latency measurement.
- [x] Implement deterministic bootstrap confidence intervals if time permits.
- [x] Verify metric calculations on a hand-computed toy example.

### Baselines

- [x] Implement majority-class baseline.
- [x] Implement keyword/regex baseline.
- [x] Implement TF-IDF word n-grams plus logistic regression.
- [x] Add character n-grams to TF-IDF baseline.
- [x] Train baseline only on train split.
- [x] Select thresholds only on dev split.
- [x] Freeze test split before model iteration.
- [ ] Record baseline results in experiment log.

### Rule engine MVP

- [x] Implement meta-instruction rule.
- [x] Add tests for benign and malicious meta-instruction text.
- [x] Implement obfuscation-evidence rule.
- [x] Add tests for zero-width/encoding/markup evidence.
- [x] Implement exfiltration/action-proximity rule.
- [x] Add tests for URL/email without malicious action.
- [x] Add tests for action verbs with no sensitive destination.
- [x] Ensure every rule emits score, evidence span, and human-readable trace.
- [x] Implement rules-only aggregation.
- [x] Evaluate each rule family separately.
- [x] Keep rule thresholds fitted only on training/dev data.

### Transformer MVP

- [x] Select primary backbone.
- [x] Select CPU-friendly fallback backbone.
- [x] Implement tokenisation with fixed maximum length.
- [x] Decide and document long-text windowing strategy.
- [x] Implement training dataset class.
- [x] Implement weighted loss or another documented imbalance method.
- [x] Set seed.
- [ ] Train first transformer run.
- [ ] Verify checkpoint can reload in a clean process.
- [ ] Run validation inference.
- [ ] Record model size and inference latency.
- [ ] Run at least three seeds if compute permits.

### Fusion and explanation

- [ ] Export transformer probabilities for dev split.
- [ ] Export rule feature vectors for dev split.
- [ ] Fit logistic-regression fusion on dev only.
- [ ] Calibrate probabilities with a documented method.
- [ ] Select operating thresholds on dev only.
- [ ] Store selected threshold and calibration parameters.
- [x] Implement final verdict object.
- [x] Include source/channel in verdict.
- [x] Include JSON path in verdict where relevant.
- [x] Include risk score in verdict.
- [x] Include flagged span in verdict.
- [x] Include reason/rule trace in verdict.
- [ ] Evaluate rules-only, transformer-only, and hybrid systems once on held-out test.

### Week 2 exit review

- [ ] Core result table exists.
- [ ] At least one false positive is explained correctly.
- [ ] At least one false negative is explained honestly.
- [ ] Team confirms no test leakage occurred.
- [ ] Team decides which rules are retained for demo.

## Week 3 - policy layer and live demo

### Capability policy

- [ ] Define a small static tool/action policy file.
- [ ] Mark actions as read-only, sensitive-read, send, write, or destructive.
- [ ] Map sensitive-read actions to confirmation or block.
- [ ] Map external-send actions to confirmation or block.
- [ ] Map destructive actions to block in demo.
- [ ] Ensure policy does not execute a real action.
- [ ] Add tests for each action-policy category.
- [ ] Record that detector output is advisory and policy is deterministic.

### Safe RAG demonstration data

- [ ] Choose a harmless local document topic.
- [ ] Create or collect clean source documents with clear provenance.
- [ ] Add one known public-style injection fixture.
- [ ] Verify fixture contains no real secret or harmful action.
- [ ] Build a local retriever/index or deterministic retrieval simulation.
- [ ] Build clean query example.
- [ ] Build poisoned query example.
- [ ] Define expected guard-off behaviour for display only.
- [ ] Define expected guard-on result.

### Safe MCP-style demonstration data

- [ ] Define a fake `search_notes` or `get_report` tool response.
- [ ] Create clean nested JSON fixture.
- [ ] Create poisoned nested JSON fixture.
- [ ] Ensure a suspicious string is inside a named JSON path.
- [ ] Create fake sensitive downstream action proposal.
- [ ] Verify guard outcome is deterministic and non-destructive.
- [ ] Add MCP-manifest fixture with benign description.
- [ ] Add MCP-manifest fixture with suspicious metadata or changed hash.

### Visual demo page

- [ ] Choose implementation framework.
- [ ] Create page shell.
- [ ] Add source selector: RAG / tool response / tool manifest.
- [ ] Add clean-versus-poisoned sample selector.
- [ ] Add safe text/JSON paste input.
- [ ] Add run-analysis button.
- [ ] Show source provenance.
- [ ] Show JSON tree/path for JSON input.
- [ ] Show original text or JSON.
- [ ] Show normalised/derived evidence when applicable.
- [ ] Highlight suspicious spans.
- [ ] Show confidence/risk score.
- [ ] Show rule and model explanations.
- [ ] Show proposed tool action.
- [ ] Show deterministic policy result.
- [ ] Add guard-off versus guard-on comparison.
- [ ] Add a limitations/disclaimer panel.
- [ ] Test page with clean RAG input.
- [ ] Test page with poisoned RAG input.
- [ ] Test page with clean JSON input.
- [ ] Test page with poisoned JSON input.
- [ ] Test page after restarting from a clean terminal.
- [ ] Measure page response time.

### Week 3 exit review

- [ ] Demo runs locally without external API credentials.
- [ ] Demo visibly highlights an injection in a RAG document.
- [ ] Demo visibly highlights an injection in MCP-style JSON.
- [ ] Demo blocks/requires confirmation for unsafe proposed action.
- [ ] Demo preserves a normal clean task.
- [ ] Screen-record a complete successful demo run.

## Week 4 - research evidence and polish

### Robustness and ablations

- [ ] Evaluate each retained rule family with leave-one-rule-out ablation.
- [ ] Test attack position: beginning, middle, end.
- [ ] Test whitespace/casing perturbation.
- [ ] Test Unicode/zero-width perturbation.
- [ ] Test safely encoded payload fixtures.
- [ ] Test long-context dilution.
- [ ] Test paraphrase or synonym variant if safe and practical.
- [ ] Record failures instead of silently removing them.
- [ ] Evaluate cross-channel transfer if tool-channel data supports it.
- [ ] Evaluate metadata scanning separately from tool-response scanning.

### Error analysis

- [ ] Sample false positives from hard negatives.
- [ ] Sample false negatives by attack type.
- [ ] Categorise false positives: documentation, quote, policy, tutorial, other.
- [ ] Categorise false negatives: paraphrase, dilution, obfuscation, declarative wording, other.
- [ ] Write one concrete mitigation/future-work note per major error category.

### Figures and report

- [ ] Generate corpus statistics table.
- [ ] Generate main model comparison table.
- [ ] Generate per-channel/attack-type table.
- [ ] Generate ablation table.
- [ ] Generate precision-recall curve.
- [ ] Generate latency/model-size table.
- [ ] Generate one pipeline architecture figure.
- [ ] Generate demo screenshots.
- [ ] Write method section.
- [ ] Write data/split/leakage section.
- [ ] Write results section only from logged outputs.
- [ ] Write limitations section.
- [ ] Verify all literature citations and venues before submission.
- [ ] Verify every result number against an experiment-log entry.

### Optional landing-page framing

- [ ] Add a clearly labelled research-prototype landing section only after demo works.
- [ ] Write one-sentence problem statement.
- [ ] Add target users: enterprise RAG, support agents, developer agents, MCP integrations.
- [ ] Add capability cards: manifest scan, runtime scan, audit trace, action gate.
- [ ] Add an honest non-production disclaimer.
- [ ] Do not add fabricated customers, security certifications, benchmark claims, or pricing.

## Final pre-submission checklist

- [ ] Fresh clone/setup can run the core detector.
- [ ] Fresh setup can run the visual demo or recorded fallback is ready.
- [ ] All final dependencies are documented.
- [ ] All public data sources and licences are recorded.
- [ ] No real credentials, personal data, or harmful payload additions are committed.
- [ ] All commands in README work.
- [ ] Test suite passes.
- [ ] Lint/format checks pass.
- [ ] Final corpus split is frozen.
- [ ] Final results were not tuned on test data.
- [ ] Final presentation has a three-minute demo script.
- [ ] Final presentation has screenshots/video backup.
- [ ] Every teammate can explain the architecture, dataset, metrics, results, and limitations.
- [ ] Report states that detection is defense in depth, not a complete guarantee.
