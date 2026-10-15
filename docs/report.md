# LLMSentinel: provenance-aware detection and capability gating for indirect prompt injection

*Research prototype report. All numbers are traceable to `docs/EXPERIMENTS.md`
and regenerate from `llmsentinel evaluate --test` and `python scripts/make_figures.py`.
Figures referenced below live in `artifacts/figures/`.*

## Abstract

LLM agents act on text they retrieve or receive from tools. That text is
untrusted, and an attacker can embed instructions in it — *indirect prompt
injection* — to make the agent leak data or take unsafe actions. We build a
guard that (1) detects injected instructions across three channels (RAG
documents, tool responses, MCP tool manifests) with provenance preserved, and
(2) gates the agent's proposed action through a deterministic capability policy.
The detector is advisory and probabilistic; the policy is deterministic and
auditable, so a missed detection degrades to a confirmation prompt rather than a
breach. On a **source-stratified** corpus combining BIPIA, InjecAgent and authored
data, the transformer detector reaches **0.984 AUPRC on held-out test** (hybrid
0.981) and **0.951 ± 0.011 dev AUPRC across three seeds**, with span-aware window
labelling. We report results with confounds stated rather than hidden — InjecAgent
is train-only by construction (§9), so the held-out numbers are carried by builtin
and BIPIA.

## 1. Introduction

- **Problem.** An agent cannot tell, from content alone, whether a sentence in a
  retrieved page is part of the data or an instruction aimed at it.
- **Contribution.** (a) A multi-channel, provenance-preserving detector
  (rules + fine-tuned transformer + fusion); (b) a deterministic capability
  policy that turns a risk score into an action decision without executing
  anything; (c) an honest evaluation — leakage-free splits, a once-only test
  protocol, per-channel/per-source breakdowns, robustness probes, and logged
  failures.
- **Scope.** Detection and demo-only policy decisions. No live services, no real
  secrets, no execution. Defence in depth, not a guarantee.

## 1a. Related work

- **Indirect prompt injection** was characterised by Greshake et al. [1], who
  showed real LLM-integrated applications can be compromised by instructions
  planted in retrieved content. Direct prompt-injection techniques were catalogued
  earlier by Perez and Ribeiro [2]. OWASP lists prompt injection as LLM01 [6].
- **Benchmarks.** We evaluate on **BIPIA** [3], a benchmark for indirect
  injection on LLMs, and **InjecAgent** [4], which targets tool-integrated agents;
  our contribution is not a new benchmark but a detector-plus-policy layer over
  these, with provenance preserved and the tool-manifest channel (**MCP** [5])
  added.
- **Positioning.** Prior detectors largely score a single text stream. We (a)
  keep channel/JSON-path provenance through detection, (b) add a deterministic
  capability-gating policy so a missed detection degrades to a confirmation rather
  than an action, and (c) evaluate with leakage-free grouped splits and a
  once-only test protocol, reporting confounds explicitly.

*Citations were verified against the source material on 2026-09-16 (checklist §15):
arXiv abstract pages for [1]–[4], modelcontextprotocol.io for [5], and the OWASP Gen
AI Security Project page for [6].*

## 2. Threat model

- **Trusted:** the user's task and the system policy. **Untrusted:** everything
  from RAG documents, tool responses, and tool manifests — by provenance, not by
  content. See `docs/threat_model.md`.
- **Attacker goals:** override, exfiltration, action hijack, destructive action,
  metadata poisoning, privilege escalation.
- **Attacker capabilities:** text control, formatting, obfuscation (Unicode,
  encodings), long-context dilution, multi-chunk placement.
- **Action classes:** read-only, sensitive-read, external-send, write,
  destructive, privilege-escalation. **Policy outcomes:** allow, isolate,
  confirm, block.

## 3. Data

- **Sources.** BIPIA and InjecAgent (both MIT, cloned locally, never
  redistributed) plus an authored seed corpus (CC0). Combined (stratified corpus,
  digest `0311c325`): **1,960 records** across all three channels. See Fig.
  `corpus_composition.png` and `docs/corpus_card.md`.
- **Labels.** Injection = assistant-directed, task-conflicting control text;
  merely discussing attacks is benign. Guideline in
  `docs/annotation_guideline.md`; independent double-annotation with Cohen's κ in
  `docs/annotation_study.md` — by two LLM annotators given only the guideline, so it
  measures guideline clarity, not human inter-annotator agreement. Hard negatives are ≥25% of benign records.
- **Splits.** Grouped by payload family *and* host document; no group crosses
  train/dev/test; leakage audited (`llmsentinel corpus check`). Split seed chosen
  on corpus structure before any model existed.
- **Caps.** BIPIA/InjecAgent capped at ~350 positive / 350 benign each for a
  balanced, channel-covered corpus; the sources are larger, so this is a
  deliberate slice, recorded as a limitation.

## 4. Method

- **Normalisation.** Unicode NFKC; zero-width / homoglyph / bidi detection kept
  as evidence; HTML-entity and bounded base64/hex decoding; sentence
  segmentation — all with an offset map back to the raw bytes so a flagged span
  highlights the original text.
- **Rule engine.** Seven families (meta-instruction, obfuscation, exfiltration,
  action-hijack, assistant-address, metadata-poisoning, task-conflict) — the
  meta-instruction family holds four rules, including `answer_shaping.v1` for
  content manipulation that fixes what the answer must claim about its own
  document (added 2026-09-16; see Limitations) — each
  emitting a score, span, and human-readable trace, with context suppression for
  quoted/documented text. The family weights and the suppression/damping factors
  are **hand-set constants**, not learned: each is a named constant carrying its
  reasoning in the module, fixed by inspection on train/dev. Their value was tested
  rather than assumed — every family was scored alone and in a leave-one-family-out
  ablation on dev (`docs/EXPERIMENTS.md`, 2026-09-06), and no weight was chosen
  against test, which is scored once. The learned combination of these signals is
  the fusion model below.
- **Transformer.** `distilroberta-base` fine-tuned as a binary classifier;
  overlapping windows for long text, scored by the max window; class-weighted
  loss; span-aware window labelling (windows labelled positive only where the
  injected span lands). See `docs/EXPERIMENTS.md` for checkpoint provenance.
  **Deployed scoring (since 2026-09-27):** the same checkpoint scores the passage
  *and each of its sentences* (JSON: each string leaf's sentences) and keeps the
  maximum, with thresholds re-selected on dev — no retraining. Motivated by the
  fresh-set failure in §6b and confirmed on a second blind set.
- **Fusion.** Logistic regression over rule features + the transformer
  probability, fitted on dev with grouped (family+host) out-of-fold predictions
  for honest dev reporting. Output used directly for thresholding; not separately
  calibrated (see Limitations).
- **Verdict → policy.** The verdict (risk, band, spans, reasons, provenance)
  feeds a deterministic table keyed by (action class × risk band). The detector
  advises; the policy decides; the policy package contains no callables.
- **Output-side check.** After the model answers, a second line of defence looks
  for a claim the untrusted context told the answerer to make, a destination taken
  from flagged or untrusted text, or a leaked secret, using run-time evidence only;
  high findings withhold the answer (§6b).

## 5. Evaluation setup

- **Protocol (enforced, not by discipline).** Fit on train; select thresholds on
  dev; score test **once** (a digest-keyed ledger refuses a second `--test` run).
  Realised FPR is reported next to the target and flagged when the budget is
  missed.
- **Metrics.** AUPRC (primary), AUROC (comparison only), TPR@1% and @0.1% FPR,
  hard-negative FPR, per-channel / per-dataset / per-attack. *Correction
  (2026-09-27):* earlier versions listed bootstrap CIs here, but the canonical runs
  used `--bootstrap 0` and saved no per-record test scores, so the canonical test
  numbers carry **no** confidence interval and no significance test; re-scoring test
  to add them would break the score-once protocol. CIs and paired tests are reported
  for dev and the fresh sets (§6b).

## 6. Results

Source-stratified corpus (digest `0311c325`, 1960 records; InjecAgent train-only,
§9). Transformer/hybrid are the span-aware checkpoint, **canonical seed 20250909**;
baselines and rules are deterministic. Held-out **test**: 246 records, 100
injection. See Fig. `model_comparison.png`, `pr_curve.png`.

| system | dev AUPRC | test AUPRC | test TPR at dev 1%-FPR threshold (realised test FPR) | test hard-neg FPR |
|---|---|---|---|---|
| majority | 0.340 | 0.407 | 0.000 (0.0000) | 0.000 |
| keyword | 0.338 | 0.450 | 0.000 (0.0000) | 0.000 |
| tfidf-word | 0.684 | 0.657 | 0.280 (0.0685, over budget) | 0.164 |
| tfidf-word+char | 0.632 | 0.664 | 0.280 (0.0548, over budget) | 0.127 |
| rules-only | 0.683 | 0.574 | 0.200 (0.0068) | 0.000 |
| transformer | 0.964 | **0.984** | **0.920 (0.0274, over budget)** | 0.000 |
| hybrid | 0.873 | 0.981 | 0.240 (0.0000) | 0.000 |

*Correction (2026-09-16).* Earlier versions of this table gave the transformer's test
recall without its realised FPR, and listed the TF-IDF hard-negative FPR as 0.000;
both are corrected here from `results_test.json`. The transformer's dev-selected 1%
threshold admits **4 false positives on 146 test negatives (2.74%)**, so 0.920 is
recall at that threshold, not a 1%-FPR operating point on test.

**Independent reproduction (second machine, RTX GPU, 2026-09-16).** Retraining the
same corpus and seeds with torch 2.5.1+cu121 / transformers 5.17.0 gave dev AUPRC
0.9494 ± 0.0113 across seeds and canonical-seed test AUPRC **0.986**, TPR 0.930 at a
realised test FPR of 0.0411 (6 / 146). The ranking reproduces within 0.002 AUPRC; the
threshold transfer to test is again over budget. Files:
`artifacts/results/gpu_rerun_2026-09-16/`. The canonical files above are kept because
they match the released checkpoint.

**Seed variance (3 seeds, dev):** transformer AUPRC **0.951 ± 0.011**
(0.937–0.964), AUROC 0.965 ± 0.010, TPR@1%FPR 0.758 ± 0.052. The single-seed
critique is answered: spread is small.

- **The transformer is the recommended system.** It is far above the baselines
  and the rule engine, and generalises to test (0.984).
- **Fusion does not help here, and its operating point is unstable.** The hybrid
  matches the transformer on test AUPRC (0.981) but its dev-selected 1% -FPR
  threshold transfers badly (test TPR@1%FPR 0.240 vs the transformer's 0.920),
  and its grouped out-of-fold dev estimate (0.873) is below the transformer. On
  this stratified corpus the rule features add noise rather than signal to the
  fused score; we report the transformer alone as the headline detector and keep
  the hybrid as a comparison, not a recommendation.
- **Per-source / per-channel (test).** transformer: BIPIA 1.000 (60 positives),
  builtin 0.920; rag_document 0.998, tool_response 0.960, tool_metadata 0.683 (5
  positives, thin). Rules-only: BIPIA 0.551, builtin 0.782 — the rule engine
  leans on the authored builtin data and drops on the real BIPIA split.
- Per-channel AUPRC in Fig. `per_channel.png`; the reliability diagram
  (`calibration.png`) is descriptive only.

### 6a. Out-of-distribution evaluation (§16a)

Full protocol and tables: `docs/ood_evaluation.md`. One whole source is held out; the
rest is split with the same grouped, leakage-free splitter; thresholds come from dev
and are reused unchanged on test and on the held-out source; each set is scored once.
Transformer rows are the mean ± std over three seeds.

| held out | system | in-dist test AUPRC | OOD AUPRC | OOD recall at dev 1% threshold |
|---|---|---|---|---|
| BIPIA (600 inj / 779 benign) | transformer | 0.861 ± 0.021 | **0.673 ± 0.038** | 0.044 ± 0.030 |
| BIPIA | tfidf-word+char | 0.697 | 0.581 | 0.002 |
| BIPIA | rules-only | 0.714 | 0.469 | 0.050 |
| InjecAgent (1,054 inj / 16 benign) | transformer | 0.980 ± 0.007 | 0.993 (not informative) | **0.000** |
| InjecAgent | rules-only | 0.538 | 0.986 (not informative) | 0.000 |

- **Performance drops under source shift, and the drop is the finding.** On a
  benchmark it never saw, the transformer loses 0.19 AUPRC (it still ranks better
  than every baseline).
- **Operating points do not transfer.** At the threshold chosen on dev the transformer
  catches 4% of held-out BIPIA injections and none of held-out InjecAgent's, although
  its ranking of InjecAgent looks high. A deployment would need calibration on data
  from the target source.
- **In-distribution `tool_metadata` is now measured** (18 test positives): transformer
  AUPRC 0.905–0.920 when InjecAgent is held out, 0.663–0.742 when BIPIA is.
- **Soft-claim content manipulation is still missed.** Retraining with the answer-shaping
  families did not make content manipulation reliably caught at the strict threshold:
  recall on 27 content-manipulation test positives was 0.22–0.48 (InjecAgent held out)
  and 0.04–0.22 (BIPIA held out). The released checkpoint flags 0 of the 9 held-out
  `assert_over_source` records (highest score 0.34, threshold 0.9954), while the
  answer-shaping rule fires on all 9.

### 6b. Fresh evaluation sets and segment-level scoring (2026-09-27)

Full protocol and tables: `docs/fresh_evaluation.md`. Two small authored sets, each
frozen by commit before it was scored and scored once: **v1** (107 records, 54
injections) and **v2** (52 records, 24 injections), the latter written *after* v1
exposed a failure and *before* the fix for it existed.

- **The deployed decision rule had never been scored.** On v1 it caught 20% of
  injections at 3.8% FPR (dev: 82.5% at 0.6%); the transformer's v1 AUPRC was 0.661
  [0.540, 0.789] and it was significantly *worse* than TF-IDF word+char on v1
  (−0.141 [−0.267, −0.009], p = 0.04).
- **Diagnosis: benign prose masks an embedded instruction.** Seven blatant payloads
  scored 0.996–1.000 alone and 0.000–0.050 inside their benign paragraph. The documents
  fit in one window, so max-over-windows could not help; JSON results escaped because
  each leaf is scored separately.
- **Fix, confirmed blind.** Segment scoring (max over the passage and its sentences,
  same checkpoint, thresholds from dev) lifted v2 AUPRC from 0.748 to **0.865**
  (paired Δ +0.117 [0.027, 0.227], p = 0.007) and the deployed rule's recall from 0.208 to
  **0.458** with no false positive (McNemar 6 vs 0, p = 0.031). It costs 0.026 dev AUPRC,
  raises v1 hard-negative false positives from 1/20 to 3/20, and 2.4× the per-passage
  latency (108 → 256 ms on a laptop CPU). It is now the deployed default.
- **Isolation is not the bottleneck.** On v2, every flagged injection was fully removed
  with 97.7% of the genuine text kept and no benign text removed; the limit is how many
  are flagged.
- **Still open.** Paraphrased injections (1 of 6 on v2) and soft claims (1 of 6) are
  mostly missed by the model; the output-side check extracted 8 of 10 v1 soft claims
  (extractor before its later fixes), and an answer that repeats one is repaired —
  the planted sentence removed and the model asked again — or withheld.

## 7. Robustness (§12)

Full report in `docs/robustness.md`. Recall *kept* from a baseline of detected
positives under meaning-preserving perturbations; hard-negative FPR under the
same. Surface/Unicode transforms keep recall 0.96–1.00 (NFKC folding and
zero-width stripping run before scoring); **failures logged**: base64 embedding
evades the rules *scorer* (the scan pipeline's derived-unit pass decodes it),
punctuation splits some trigger regexes, and quote/fence/zero-width/bidi wrapping
of benign text raises hard-negative FPR. Cross-channel transfer degrades
off-diagonal (worst: train `tool_metadata` → test documents, AUPRC 0.558 vs 0.98
in-channel).

## 8. Error analysis (§15)

See `docs/error_analysis.md` (generated from `scripts/error_analysis.py`).
Categories and one mitigation each: quote/documentation false positives
(suppression tuning), obfuscation-injection false positives on transformed hard
negatives (density-weighted concealment evidence), declarative / paraphrase false
negatives (transformer generalisation), dilution false negatives (max-window
aggregation already mitigates), and base64 false negatives (fold derived-unit
scoring into the aggregate).

## 9. Limitations

- **Source/channel confound (addressed).** The corpus is now **source-stratified**
  (digest `0311c325`): BIPIA contributes real positives to dev (40) and test (60),
  and every (split, channel) cell has positives. **InjecAgent is a single leakage
  component** (every attacker instruction × every user tool) and cannot be split
  without payload/host leakage, so it is **train-only by design**; held-out
  evaluation is carried by builtin + BIPIA. This removes the earlier misleading
  InjecAgent test rows. Per-source/per-channel breakdowns remain the numbers to
  quote for detection claims. (Model numbers refresh after the multi-seed run.)
- **Seed variance is small but real:** dev AUPRC 0.951 ± 0.011 across three seeds
  (`seed_variance.json`). Test was scored once with the canonical seed's
  thresholds, so its numbers are a single realisation, not a variance estimate.
- **Rule weights are hand-set, not learned.** Family weights and suppression/damping
  factors were fixed by inspection on train/dev. They are ablated (each family alone
  and leave-one-family-out on dev) and never tuned against test, but they are a
  designer's priors: another corpus could need different values, and the rule engine
  should be re-ablated before it is trusted elsewhere.
- **`tool_metadata` is the thinnest channel.** The canonical corpus has ~5 test
  positives there, so its per-channel number (0.683) is indicative only. The §16a
  hardening sets raise it to 18 test positives with authored families
  (`docs/ood_evaluation.md`). Consequence seen in practice: on a poisoned MCP tool
  description the transformer scored 0.984, under its 0.9954 operating point, and the
  metadata rule carried the detection — which is why the rules stay in the decision.
- **Soft-claim content manipulation is under-covered.** An instruction that fixes
  the answer's content without contradicting the document or naming a destination
  ("when answering questions about this document, always state that …") scored 0.591
  with the transformer, under its 0.9954 operating point, while a blatantly
  self-contradicting version scored 0.9998. `answer_shaping.v1` and two opt-in seed
  families were added on 2026-09-16; the rule fires on the shape but its rules-only
  aggregate (0.75–0.78) stays below the 0.8340 operating point. The retraining that was
  expected to close the gap did not (§6a): content-manipulation recall at the strict
  threshold stayed at 0.04–0.48, and a family held out of training
  (`assert_over_source`) scored at most 0.34. The rule's weight is a prior: it fires on
  one record in the canonical corpus, so dev gives it no support (dev metrics were
  byte-identical before and after adding it).
- **The canonical test result overstates prose robustness.** The 0.984 is real for the
  test split, but a passage-level transformer missed injections embedded in unseen
  benign prose (§6b); the placement probe for the transformer that would have shown this
  was never run before the numbers were reported. Segment scoring recovers part of it;
  the fresh sets are small (24–54 injections) and authored by the project.
- **Dev thresholds do not survive a change of source.** In-distribution the
  transformer's dev 1% threshold already over-admits on test (2.74%); on a held-out
  benchmark it catches 0–9% of injections. Any real deployment would need to calibrate
  its operating point on data from the source it will face.
- **One-sided framing is out of scope by definition.** Prose that argues a position
  without instructing the assistant is benign under `docs/annotation_guideline.md`,
  and the detector scores it near zero. Detecting slanted-but-passive content is a
  different problem (claim verification), not indirect prompt injection.
- **Calibration not established** — fusion output is used directly; no reliability
  / Brier / ECE validated.
- **Semantic layer** uses a lexical similarity proxy by default; the neural
  backend is optional and unevaluated. Experimental.
- **Not production enforcement** — no authentication, streaming, tenant
  isolation, or fail-closed guarantees. The §17 analyst tooling does not change this.
  The SDK and the local proxy are advisory: code that ignores them bypasses them, and
  the proxy refuses streaming rather than gating it. The review-queue triggers are
  heuristics on the dev operating points and have not been evaluated for how well they
  select cases a reviewer would change (`docs/analyst_workflow.md`).

## 10. Safety and ethics

No live third-party systems, real secrets, or personal data were used. All
payloads use reserved `.invalid` destinations and placeholder credentials.
Nothing is executed: the policy returns a decision, never an action. LLMSentinel
is defence in depth and must be paired with least privilege, human approval, and
server-side authorisation.

## 11. Conclusion

A provenance-aware detector plus a deterministic capability gate catches
indirect prompt injection across three channels and turns the risk into an
auditable action decision, with an honest account of where it fails. The source
confound was removed by the stratified re-split (§9). What the later fresh sets
showed is sharper: the canonical 0.984 overstated how the passage-level transformer
handles an instruction embedded in ordinary prose it has not seen, and the
operating points do not survive a change of source. Segment-level scoring (§6b)
recovers part of that without retraining; paraphrased attacks, soft claims and
threshold transfer remain the open problems, and the next steps are per-source
threshold calibration, retraining with more varied hosts and phrasings, and a
real-model end-to-end evaluation.

## Reproduce

```bash
python -m llmsentinel.cli corpus build
python scripts/train_transformer.py --epochs 3      # optional; ~53 min CPU
python -m llmsentinel.cli evaluate --test
python scripts/make_figures.py
python scripts/error_analysis.py --system hybrid
python scripts/robustness_suite.py
```

## References

*Checked against the sources on 2026-09-16: every arXiv ID, title and author list
below matches its abstract page. Venues are given where the source states one; [1]'s
abstract page lists no venue, so it is cited as a preprint.*

1. K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, M. Fritz.
   "Not What You've Signed Up For: Compromising Real-World LLM-Integrated
   Applications with Indirect Prompt Injection." arXiv:2302.12173, 2023.
2. F. Perez, I. Ribeiro. "Ignore Previous Prompt: Attack Techniques for Language
   Models." arXiv:2211.09527, 2022. ML Safety Workshop, NeurIPS 2022.
3. J. Yi, Y. Xie, B. Zhu, E. Kiciman, G. Sun, X. Xie, F. Wu. "Benchmarking and
   Defending Against Indirect Prompt Injection Attacks on Large Language Models"
   (BIPIA). arXiv:2312.14197, 2023; accepted at KDD 2025
   (doi:10.1145/3690624.3709179).
4. Q. Zhan, Z. Liang, Z. Ying, D. Kang. "InjecAgent: Benchmarking Indirect Prompt
   Injections in Tool-Integrated Large Language Model Agents." arXiv:2403.02691,
   2024. Findings of ACL 2024.
5. "Model Context Protocol (MCP)." Open standard introduced by Anthropic in 2024;
   https://modelcontextprotocol.io (specification dated 2026-07-28 when checked).
6. OWASP Gen AI Security Project. "2025 Top 10 Risk & Mitigations for LLMs and Gen
   AI Apps" — entry "LLM01:2025 Prompt Injection".
   https://genai.owasp.org/llm-top-10/

