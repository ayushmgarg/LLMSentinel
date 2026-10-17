# Remaining things

Everything still pending for LLMSentinel, in one place. Written 2026-09-22; the item
tables below are kept as written, and progress is tracked in the status list.

## Status (2026-10-14) — after cluster round r1

Results in `docs/EXPERIMENTS.md` (2026-10-14); raw outputs in `artifacts/cluster_runs/r1_cluster_kit/`.

**Done:**
- **B1/F7** — per-source calibration incl. the transformer rows. Finding: calibration keeps the
  FPR bound but does not recover recall on held-out BIPIA (≤1.5%); InjecAgent not computable.
- **B4 (position augmentation)** — trained 3 seeds + controls, scored once on v3 with
  pre-registered tests. **Negative:** no significant gain anywhere, worse on dev at every seed,
  deployed recall collapses. Not deployed.
- **B2/F8** — 170 valid fresh rewrites; 89% of caught attacks stay caught (small n).
- **B7/F6 and F3** — real model (Qwen3-4B-Instruct): attack success 27% none, 25% prompt-only,
  2% LLMSentinel.
- **Fresh set v3** — scored once (ledger `artifacts/results/fresh_runs.json`).

**Partly done:**
- **F4** — cost on clean inputs measured (prompt changed on 3 of 69, nothing withheld);
  answer *quality* not scored (no reference answers).
- **D2** — EXPERIMENTS updated; README, report and `docs/fresh_evaluation.md` do not have the
  cluster results yet.

**Left (only what was already listed or discussed):**
- **A1** open part: fresh-setup / clean-install check. **A2** screenshots (deferred). (A4 dropped 2026-10-17.)
  **A3/F11** adaptive attacker (optional). ~~A4/F12 inter-annotator agreement~~ dropped.
- **B3/F9** NLI soft-claim check — soft claims are now the clearest remaining hole (v3 recall
  0.12; Sentinel's one real-model miss).
- Paraphrase-augmentation retrain (the original B4 idea) — train rewrites now exist
  (`data/processed/paraphrase/train_paraphrases.jsonl`, 210 valid); needs a new fresh set first.
- **B12/B13, F14** semantic signals; **F13** retrieval poisoning per retriever; **B9** active
  learning; **B5/B6** deferred.
- Agentic rule-evolution loop (idea, discussed 2026-10-11; not started).
- **C1** — try the MCP gateway inside Claude Desktop.
- **D1** merge PR #2; **E** research paper (after the rest); **D3** move the repo out of
  OneDrive (very last).

## Status (2026-10-11)

Details in `docs/EXPERIMENTS.md`, 2026-10-11 entries; the cluster run in `docs/CLUSTER_RUN.md`.

**Done this round:**
- **Output check and repair** — polarity-aware claims, reply directives, directed
  destinations, repair-and-retry, temperature 0; then hardened after a code review
  (clause-scoped negation, negative prefixes, Unicode normalisation, every planting
  sentence removed on repair).
- **Fresh set v3** — `data/fresh/fresh_eval_v3.yaml`, frozen in commit `52de9d6` before the
  augmentation code; reserved for one scoring of the retrained models (cluster step 6).
- `fresh_eval.py` — global score-once ledger, pre-registered `--compare`, `--extra` checkpoints.

**Partly done:**
- **B1/F7** — method and CPU rows done (BIPIA: calibration holds the FPR bound but adds no
  recall for rules-only or TF-IDF). InjecAgent cannot be calibrated this way (no clean page
  separable from its injected copies). Transformer rows: the cluster kit trains the hardening
  checkpoints itself (step 3), so nothing is needed from the friend.
- **B4, redefined** — the measured failure is *position* (277 of 315 train document
  injections at the end), so B4 is now embedded-position augmentation, not paraphrase
  retraining: the data is built (`data/processed/augmented/`, digest `9a115633639334e1`);
  augmented and control models train on the cluster (step 4).
- **B2/F8** — generator, automatic validation and measurement ready
  (`scripts/paraphrase_attacks.py`); runs on the cluster with a model server (step 7).
- **B7/F6, F3, F4** — harness ready (`scripts/real_model_eval.py`: none / prompt-only /
  Sentinel); smoke-tested on the laptop (too slow there); full run on the cluster (step 8).
- **D2** — EXPERIMENTS, README, studio README, fresh-evaluation doc and report corrected
  for this round; the report still needs a pass once the cluster results are in.

**Not started:** A2, A3, A4, B3/F9, B5, B6, B9, B12, B13, D1, D3, F11, F12, F13, F14.

## Status (2026-09-28)

**Done** (details in `docs/EXPERIMENTS.md`, 2026-09-27):
- **A1** — §19 pass: 9 of 10 criteria ticked with evidence in `PROJECT_CHECKLIST_V2.md`;
  inconsistencies fixed (bootstrap-CI claim, stale conclusion, annotation wording, unrun
  transformer placement probe). *Open:* fresh-setup / clean-install check.
- **B0** — fresh set v1 (`data/fresh/fresh_eval.yaml`), frozen and scored once; plus a
  second, confirmatory set v2 (`fresh_eval_v2.yaml`).
- **B8** — output-side check (Studio guarded run, proxy, SDK-level function).
- **B10** — gated auto-promotion of candidate rules (`llmsentinel rules shadow | auto-promote | rollback`).
- **B11** — dense retriever (MiniLM) as the Studio default, TF-IDF option and fallback.
- **C1** — MCP gateway (`python -m llmsentinel.gateway`, `docs/mcp_gateway.md`); tested
  through real MCP client/server code and a stdio run; not yet tried inside Claude Desktop.
- **D2** — report, README, EXPERIMENTS, studio README and analyst docs updated for the above.
- **F1** — paired bootstrap + McNemar on dev and both fresh sets (not on the canonical
  test split: per-record test scores were never saved).
- **F2** — latency and overhead (`artifacts/results/latency.json`).
- **F5** — isolation quality on both fresh sets.
- **F10** — manifest drift correctness (all 6 cases) + tool-description detection on v1.
- **New (not in the list)** — the fresh set exposed that the passage-level transformer
  misses instructions embedded in benign prose; **segment-level scoring** fixes part of it,
  confirmed on v2, and is now the deployed default.

**Not started:** A2, A3, A4, B1/F7, B2/F8, B3/F9, B4, B5, B6, B7/F6, B9, B12, B13, D1, D3,
F3, F4, F11, F12, F13, F14. Blocked on something outside this machine: B1/F7 transformer
rows (friend's `transformer_hardening_*` folders); B2, B7, F3, F4 (Ollama running); A4/F12
(other annotators); B4–B6 (GPU).

**One rule applies to every new evaluation below:** the canonical test split and
both out-of-distribution sets have already been scored **once**. A new method must
not be tuned or re-scored on them. Use a **fresh evaluation set** (item B0) or
clearly disclose a post-hoc re-score in the report.

---

## A. Finishing the checklist (needed to call the project done)

| # | Item | What it involves | Effort |
|---|---|---|---|
| A1 | **§19: final completion criteria** (10 items) | Verification pass: every result has a command, corpus digest, seed and log entry. Test data never drove a design choice. Datasets and licences are accurate; synthetic and benchmark results are kept separate. Comparisons are fair. Failures are reported. Verdicts keep provenance. Policy is deterministic. A fresh setup runs the demo. README, tests and lint are current. The report says "defence in depth, not complete protection". | ½ day, mostly checking and ticking |
| A2 | **§15: demo screenshots** | Capture the new Studio pages (demo, about, how-it-works, analyst) per `docs/demo_script.md`. The UI is stable now. | 1 hour |
| A3 | **§18: adaptive-attacker study** (optional) | Small tier-a (black-box, decision-only) run against our own rules-only detector, following the protocol in `docs/research_boundary.md` §5. | 1 day, CPU is enough |
| A4 | **§18: inter-annotator agreement** (optional) | 2–3 classmates label 50–100 records using `docs/annotation_guideline.md`; report Cohen's/Fleiss' kappa with a confidence interval, plus an adjudication note. | A few hours of their time |
| — | §18: multi-turn data, multilingual/multimodal | Closed as out of scope: designed in `docs/research_boundary.md`, not evidenced. | none |

---

## B. Add-on features ("make the project better")

English only (multilingual dropped).

| # | Add-on | New training? | Needs friend's GPU? | Effort | Status |
|---|---|---|---|---|---|
| B0 | **Small fresh evaluation set**: soft-claim cases, paraphrased attacks, benign counterparts; built before any method below is implemented | No | No | ½–1 day | Do first |
| B1 | **Per-source threshold calibration**: threshold set at 1% FPR on ~100–200 clean pages from the target source; calibration part and evaluation part kept separate. (Temperature scaling alone does not help: it is monotone.) | No | Only his two `transformer_hardening_*` folders | ~1 day | Top priority; fixes the 0–9% OOD recall finding |
| B2 | **Paraphrase robustness, measured**: local instruct model rewrites ~100–200 attacks; keep rewrites that still carry the attack (auto check + spot check); measure recall drop | No | No | Few hours of CPU | Recommended |
| B3 | **NLI soft-claim check**: when `answer_shaping.v1` finds a claim, `roberta-large-mnli` checks it against the document; contradicted means flag | No | No | 1–2 days | Recommended as experimental; only catches contradictions, not plausible unrelated claims |
| B4 | Paraphrase-augmentation **retrain** (rewrites stay inside their attack family's split) | Yes | Yes | Medium–high | Only if B2 shows a real drop |
| B5 | Span-level tagging (token classification, span F1) | Yes | Yes | High | Deferred |
| B6 | DeBERTa-v3 teacher, distilled into a small student | Yes, twice | Yes | High | Deferred |
| — | Multilingual (XLM-R, Hinglish) | — | — | — | **Dropped** |

Extensions to the same problem:

| # | Extension | Effort | Note |
|---|---|---|---|
| B7 | **Prompt-only defence baseline**: "tell the LLM to ignore injections" vs Sentinel, with a real local model | ~1 day, CPU, slow | Answers the obvious reviewer question |
| B8 | **Output-side check**: the answer repeats a planted claim or leaks a secret; a second line of defence | ~1 day | Studio compromise indicators are halfway there |
| B9 | **Active learning**: reviewer labels from the analyst queue feed the next retrain | Design now, retrain on GPU later | Pairs with B10 |
| B10 | **Gated auto-promotion of candidate rules**: human-confirmed cases only, independent-source diversity, auto-reject on benign dev match or low dev precision, shadow mode, FP budget, rate limit, one-click rollback, versioned rule set. Still advisory; never touches the scored detector or the fusion feature vector | ~½ day | From the "self-updating rules" discussion |
| — | Multi-turn / memory poisoning, multimodal | — | Out of scope (§18) |

Semantic retrieval and embedding signals (MiniLM):

| # | Item | New training? | Effort | Note |
|---|---|---|---|---|
| B11 | **Pluggable retriever, dense by default**: `tfidf` (current, reproducible) / `dense` (`all-MiniLM-L6-v2` sentence embeddings, cosine similarity), selectable in the Studio and CLI; dense is the Studio default, TF-IDF stays as the fallback and for tests | No | ~½ day | Realism only: the detector scans whatever is retrieved, so no detection number changes. TF-IDF also stays as the baseline *classifier* (separate use). BM25 / hybrid / reranker skipped: still lexical, or extra tuning for no visible gain |
| B12 | **Semantic task-conflict signal** (experimental): MiniLM distance between each passage sentence and the user's question; a directive far from the question in meaning is suspicious. The semantic version of the lexical task-conflict rule | No (threshold picked on dev) | ~½ day | Effect on detection is unknown until measured on B0; never on test |
| B13 | **Similarity to confirmed attacks** (experimental, advisory): embed sentences, compare with embeddings of human-confirmed injections from the analyst history; catches paraphrases that n-gram candidate rules miss | No | ~½ day | Same safety rule as candidate rules: built only from human-confirmed cases, advisory only, never in the scored detector |

Not a use for MiniLM: replacing the detector (a frozen 22M-parameter encoder is not
expected to beat the fine-tuned `distilroberta-base`), or the soft-claim problem
(that needs NLI, B3).

---

## C. MCP gateway (Shape B), chosen

| # | Item |
|---|---|
| C1 | **LLMSentinel MCP gateway.** Claude/GPT connect to the gateway only; it fronts the real MCP servers. |

- **On connect:** scan every tool manifest; pin approved tools; quarantine poisoned or drifted ones.
- **On tool call:** gate by action class via `configs/policy.yaml` (allow / confirm / block). "Confirm" comes back as a structured "held for confirmation" result; nothing executes without approval.
- **On tool result:** scan (JSON by leaf, with paths), strip minimally or withhold, then return.
- Record everything in the analyst store (history, alerts, review queue).
- **Transport:** stdio first (Claude Desktop, Claude Code). HTTP for remote clients such as ChatGPT connectors comes later and needs auth.
- **Library:** official Python `mcp` SDK. Reuse `Sentinel` from `llmsentinel.sdk`.
- **Tests:** a fake upstream MCP server; a Claude Desktop / Claude Code config example.
- **Not covered, state in README:** the client's own built-in web search, and files pasted into chat.
- **Demo-grade only:** no auth, single user. `docs/research_boundary.md` §6 lists what production would need.
- **Effort:** about 1 day.

---

## D. Housekeeping

| # | Item |
|---|---|
| D1 | Merge PR #2 (`a1` → `main`); it already contains the latest commits |
| D2 | Update `docs/report.md`, README and `docs/EXPERIMENTS.md` for whatever gets done from B, C, E and F |
| D3 | **Very last:** move the repo out of OneDrive |

---

## E. Research paper checklist

`docs/report.md` is the current draft (abstract, intro, related work, threat model,
data, method, setup, results incl. OOD, robustness, error analysis, limitations,
safety/ethics, conclusion, reproduce, references). What turning it into a paper still needs:

### E1. Decisions first
- [ ] Target: course submission only, or a workshop/conference? Decides template, page limit and anonymity.
- [ ] Template: ACL (`acl.sty`) or IEEE two-column. Page limit and appendix rules noted.
- [ ] Anonymity: double-blind means no repo link, names or acknowledgements in the submission version.
- [ ] Code/data availability: the repo is private. Decide whether to release it (or an anonymised copy) with the paper.
- [ ] Course rules on AI-assistance disclosure, followed.

### E2. Structure and content
- [ ] Title and abstract rewritten around the final numbers (in-distribution, OOD drop, isolation, gate).
- [ ] Explicit **contributions list** (3–4 bullets) at the end of the introduction.
- [ ] **Related work expanded.** Only 6 references now. Candidates to read and verify before citing: AgentDojo (agent prompt-injection benchmark), spotlighting (input marking), StruQ / SecAlign (structured queries, preference-trained defences), TaskTracker (activation-based drift detection), Prompt Guard / Llama Guard (classifier guards), and LLM security surveys. Every citation checked against its source, as was done for the current list.
- [ ] Threat model condensed to one paragraph plus a table (attacker capabilities, channels, out of scope).
- [ ] Method section with the architecture figure (`artifacts/figures/architecture.svg`) and a pipeline figure (normalise → score → isolate → gate).
- [ ] Clear statement of the **frozen protocol** (train / dev thresholds / test once, digest-keyed ledger) as a methodological contribution.
- [ ] Results tables: in-distribution (all systems, realised FPR beside target, over-budget flags), per-channel, OOD, leave-one-family-out ablation, robustness, error analysis.
- [ ] Every table has CIs (bootstrap CIs exist) and seed variance where the model is involved.
- [ ] **Negative results kept:** OOD recall drop, soft-claim gap (retraining did not close it), base64 0.00 in the rules scorer, punctuation 0.79, wrapping FPR 7–15%.
- [ ] Limitations: "defence in depth, not complete protection"; English only; text only; single-turn; authored data share; no adaptive attacker.
- [ ] Ethics / broader impact: dual use of the attack corpus, reserved `.invalid` destinations, no working payloads released.
- [ ] Reproducibility statement: commands, corpus digest, seeds, hardware (CPU laptop + GPU run), library versions.
- [ ] Data statement / licences: BIPIA, InjecAgent, authored CC0 data (from `docs/corpus_card.md`).
- [ ] Appendix: annotation guideline excerpt, corpus card, rule inventory, policy table, extra per-dataset tables, Studio screenshots.

### E3. Figures
- [ ] Architecture (exists), PR curves (exist), per-channel (exists), corpus composition (exists), calibration (exists).
- [ ] New: OOD comparison figure (in-distribution vs held-out source).
- [ ] New: robustness bar chart (recall kept per transform).
- [ ] New: one Studio screenshot showing an unguarded answer compromised vs a guarded one.
- [ ] All figures readable in grayscale, vector where possible, consistent fonts.

### E4. Consistency pass
- [ ] Every number in the paper traced to a results file (`artifacts/results/...`), and identical in the paper, README, report and Studio.
- [ ] Terminology fixed: channel names, "isolate / strip / withhold", "flag", risk bands.
- [ ] Proofread; references formatted to the template.

---

## F. Extra evaluations needed for the paper

All on the fresh set (B0) or on data not yet scored; never re-tuned on test. Each
gets a command, digest, seed and an `EXPERIMENTS.md` entry.

| # | Evaluation | Why the paper needs it | Needs | Effort |
|---|---|---|---|---|
| F1 | **Paired significance tests** between systems (paired bootstrap on AUPRC, McNemar at the operating point), computed from the already-saved test predictions without re-scoring | Claims like "hybrid beats rules-only" need a test, not just two numbers | Saved test predictions (confirm they exist) | ½ day |
| F2 | **Latency / overhead**: per-passage scan time (rules-only vs transformer, CPU), model load time, added end-to-end latency per question | "Practical guard" claims need a cost number | CPU only | ½ day |
| F3 | **End-to-end attack success rate (ASR)** with a real local model (`qwen3:4b-instruct`), unguarded vs guarded, on the sample pack + fresh set | Detection metrics are not the same as attacks prevented; this is the headline system result | Ollama, CPU (slow) | 1 day |
| F4 | **Utility cost**: answer quality on *clean* context with and without the guard, and the over-stripping rate (benign text removed) | A guard that breaks benign answers is not useful; reviewers will ask | Same runs as F3 + small judged set | ½–1 day |
| F5 | **Isolation quality, measured**: fraction of injection text removed vs benign text kept, per passage | Currently only shown on 6 demo cases | Fresh set with span labels | ½ day |
| F6 | **Prompt-only defence baseline** (= B7) | Answers "why not just tell the model?" | Ollama, CPU | 1 day |
| F7 | **Per-source calibration** (= B1) on the OOD sources, with separate calibration and evaluation parts | Main fix for the biggest negative result | Friend's two model folders | ~1 day |
| F8 | **Paraphrase robustness** (= B2) | Robustness is currently only measured with weak word swaps | Ollama, CPU | Few hours |
| F9 | **NLI soft-claim layer** (= B3) on fresh soft-claim cases | Tests the fix for the measured soft-claim gap | CPU | 1–2 days |
| F10 | **Manifest channel**: larger manifest set (currently 33 positives) + drift-detection correctness | Metadata poisoning is a stated contribution; 33 positives is thin | Authored manifests | ½ day |
| F11 | Adaptive attacker, tier a (= A3), optional | Strongest robustness evidence | CPU | 1 day |
| F12 | Inter-annotator agreement (= A4), optional | Label-quality claim | 2–3 annotators | Few hours |
| F13 | **Retrieval poisoning under each retriever** (TF-IDF vs dense, = B11): how many poisoned passages reach the model per retriever, and whether Sentinel still catches what each surfaces | Shows the guard is retriever-independent under a realistic retriever | MiniLM, CPU | ½ day |
| F14 | **Semantic signals** (= B12, B13) on the fresh set: added recall vs added false positives over the current hybrid | Decides whether embedding signals earn a place | MiniLM, CPU | ½ day |

**Minimum for a credible paper:** F1, F2, F3, F4 and F7. The rest strengthen it.

---

## Suggested order

1. **A1 + A2**: project "done".
2. **C1**: MCP gateway. **B11** (dense retriever) alongside, since both touch the context path.
3. **B0**, then **F1, F2**: cheap, no new data needed beyond B0.
4. **F3 + F4 (+ F6)**: one batch of real-model runs.
5. **B1/F7 → B2/F8 → B3/F9**, then **F5, F10**, then **B12/B13 with F13/F14**.
6. **B8, B10**, then **A3/A4** if time allows.
7. **E**: write the paper from the results.
8. **D1–D3** last. B4–B6 only with GPU time.
