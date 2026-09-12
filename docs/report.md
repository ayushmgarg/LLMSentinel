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
breach. On a corpus combining BIPIA, InjecAgent and authored data, the detector
reaches **0.95–0.96 AUPRC on held-out test** (transformer 0.958, hybrid 0.950,
with span-aware window labelling); we report the result with its confounds
(source/channel imbalance) stated rather than hidden.

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

*Citations are drafted; arXiv IDs, authors and venues must be verified against
the source material before any submission (checklist §15).*

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
  redistributed) plus an authored seed corpus (CC0). Combined: **1,669 records**
  across all three channels; train/dev/test = 1286/197/186. See Fig.
  `corpus_composition.png` and `docs/corpus_card.md`.
- **Labels.** Injection = assistant-directed, task-conflicting control text;
  merely discussing attacks is benign. Guideline in
  `docs/annotation_guideline.md`; independent double-annotation with Cohen's κ in
  `docs/annotation_study.md`. Hard negatives are ≥25% of benign records.
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
  action-hijack, assistant-address, metadata-poisoning, task-conflict), each
  emitting a score, span, and human-readable trace, with context suppression for
  quoted/documented text.
- **Transformer.** `distilroberta-base` fine-tuned as a binary classifier;
  overlapping windows for long text, scored by the max window; class-weighted
  loss; span-aware window labelling (windows labelled positive only where the
  injected span lands). See `docs/EXPERIMENTS.md` for checkpoint provenance.
- **Fusion.** Logistic regression over rule features + the transformer
  probability, fitted on dev with grouped (family+host) out-of-fold predictions
  for honest dev reporting. Output used directly for thresholding; not separately
  calibrated (see Limitations).
- **Verdict → policy.** The verdict (risk, band, spans, reasons, provenance)
  feeds a deterministic table keyed by (action class × risk band). The detector
  advises; the policy decides; the policy package contains no callables.

## 5. Evaluation setup

- **Protocol (enforced, not by discipline).** Fit on train; select thresholds on
  dev; score test **once** (a digest-keyed ledger refuses a second `--test` run).
  Realised FPR is reported next to the target and flagged when the budget is
  missed.
- **Metrics.** AUPRC (primary), AUROC (comparison only), TPR@1% and @0.1% FPR,
  hard-negative FPR, per-channel / per-dataset / per-attack, bootstrap CIs.

## 6. Results

Held-out **test** (186 records, 47 injection), current run — see Fig.
`model_comparison.png` and `pr_curve.png`:

| system | dev AUPRC | test AUPRC | test TPR@1%FPR | test hard-neg FPR |
|---|---|---|---|---|
| majority | 0.244 | 0.253 | 0.000 | 0.000 |
| keyword | 0.256 | 0.407 | 0.000 | 0.000 |
| tfidf-word | 0.769 | 0.675 | 0.362 | 0.000 / 0.055 |
| tfidf-word+char | 0.730 | 0.725 | 0.468 | 0.000 / 0.127 |
| rules-only | 0.769 | 0.673 | 0.191 | 0.000 |
| transformer | 0.936 | **0.958** | 0.745 | 0.000 |
| hybrid | 0.926 | **0.950** | 0.532 | 0.000 |

*Transformer/hybrid rows are the span-aware-labelled checkpoint (`seed 20250909`,
retrained 2026-09-12). Baselines and rules are deterministic and unchanged.*

- The transformer and hybrid dominate the baselines and the rule engine on test.
- **Dev hybrid (0.926) is an out-of-fold estimate** under family+host grouping,
  which unions payload family and host so neither leaks across folds; an earlier
  family-only grouping reported an inflated 0.957.
- Per-channel test AUPRC in Fig. `per_channel.png`; the reliability diagram
  (`calibration.png`) is descriptive only.

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

- **Source/channel confound.** Dev has zero BIPIA positives; metadata support is
  small; InjecAgent is 93% positive. Combined-corpus headline AUPRC is confounded
  by source and channel — the per-source, per-channel, and transfer breakdowns
  are the numbers to quote for claims about *detection*. A source-stratified
  re-split is future work (changes the frozen digest, needs full re-evaluation).
- **Single-seed transformer**, and the shipped checkpoint predates span-aware
  labelling (a retrain adopts it).
- **Calibration not established** — fusion output is used directly; no reliability
  / Brier / ECE validated.
- **Semantic layer** uses a lexical similarity proxy by default; the neural
  backend is optional and unevaluated. Experimental.
- **Not production enforcement** — no authentication, streaming, tenant
  isolation, or fail-closed guarantees.

## 10. Safety and ethics

No live third-party systems, real secrets, or personal data were used. All
payloads use reserved `.invalid` destinations and placeholder credentials.
Nothing is executed: the policy returns a decision, never an action. LLMSentinel
is defence in depth and must be paired with least privilege, human approval, and
server-side authorisation.

## 11. Conclusion

A provenance-aware detector plus a deterministic capability gate catches
indirect prompt injection across three channels and turns the risk into an
auditable action decision, with an honest account of where it fails. The
strongest next steps are removing the source confound (stratified re-split +
retrain) and validating calibration.

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

*To verify (IDs/authors/venues) before submission.*

1. K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, M. Fritz.
   "Not What You've Signed Up For: Compromising Real-World LLM-Integrated
   Applications with Indirect Prompt Injection." arXiv:2302.12173, 2023.
2. F. Perez, I. Ribeiro. "Ignore Previous Prompt: Attack Techniques for Language
   Models." arXiv:2211.09527, 2022.
3. J. Yi et al. "Benchmarking and Defending Against Indirect Prompt Injection
   Attacks on Large Language Models" (BIPIA). arXiv:2312.14197, 2023.
4. Q. Zhan et al. "InjecAgent: Benchmarking Indirect Prompt Injections in
   Tool-Integrated Large Language Model Agents." arXiv:2403.02691, 2024.
5. Anthropic. "Model Context Protocol (MCP)." Specification, 2024.
   https://modelcontextprotocol.io
6. OWASP. "Top 10 for Large Language Model Applications — LLM01: Prompt
   Injection." 2023–2025.

