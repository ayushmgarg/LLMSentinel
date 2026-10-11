# Harder / out-of-distribution evaluation (checklist §16a)

**Status (2026-09-16): complete.** Protocol, hardened data, baselines and the
three-seed transformer run are all scored once on the current hardened sets
(in-dist digests `444a988f` / `7bf9438e`). The GPU run came from
`scripts/hardening_kit.ps1` on a second machine (CUDA, torch 2.5.1+cu121,
transformers 5.17.0); its raw logs and ledgers are in
`artifacts/results/gpu_rerun_2026-09-16/`. Results supersede the earlier baseline
table, which was scored on the previous sets and is kept below as recorded.

> **Keep separate.** Nothing on this page is an in-distribution number. The project
> headline (transformer test AUPRC 0.984) is the canonical corpus result
> (digest `0311c325`) and is unchanged by this work.

## Why

0.98 AUPRC on our own grouped splits says the detector separates *these* sources
well. A sceptical reviewer asks whether it holds on a source it never saw. The goal
here is a harder, more honest number, not a better one: a drop is itself the
finding.

## Protocol

Code: `src/llmsentinel/evaluation/ood.py`, CLI `scripts/ood_eval.py`, tests
`tests/test_ood.py`.

1. **Collect** the builtin data (canonical seed + the opt-in hardening seed below),
   BIPIA and InjecAgent.
2. **Exact-deduplicate** across everything first (3,343 duplicates removed).
3. **Hold out one whole source.** Two directions are built:
   * held out **InjecAgent**; train/dev/test from builtin + BIPIA;
   * held out **BIPIA**; train/dev/test from builtin + InjecAgent.
4. **Split the remaining pool** with the project's grouped, label-stratified
   splitter (seed `20250909`): no content, host or payload group crosses splits.
5. **Scrub the OOD set** against everything in-distribution: drop OOD records that
   are near-duplicates (word 5-gram Jaccard ≥ 0.85) of any in-distribution record,
   or that share a group/host/payload key. Measured, not assumed: 0 near-duplicates
   and 0 shared keys dropped in both directions.
6. **Score once.** Thresholds are chosen on dev (1% and 0.1% FPR) and reused
   unchanged on test and on the OOD set; nothing is tuned on OOD. A local ledger
   (`artifacts/results/ood/test_runs.json`, keyed by system, held-out source and both
   set digests) refuses a second scoring unless `--force-test` is passed and recorded.
7. **Report honestly under class imbalance.** OOD AUPRC is marked informative only
   when both classes have ≥ 30 records and prevalence is within 10–90%; otherwise
   it is shown as `n/i`, because any scorer's AUPRC then sits near the prevalence.
   Recall at the dev thresholds is always reported (it needs only positives).

| Held out | train | dev | test | OOD | OOD injection / benign | digests (indist / OOD) |
|---|---|---|---|---|---|---|
| InjecAgent | 1,886 | 450 | 376 | 1,070 | 1,054 / 16 (98.5%) | `444a988f` / `59a18622` |
| BIPIA | 1,992 | 208 | 203 | 1,379 | 600 / 779 (43.5%) | `7bf9438e` / `ce909669` |

> Sizes and in-distribution digests changed on 2026-09-16 when the answer-shaping
> families below were added to the opt-in seed; the OOD sets and their digests are
> unchanged. The baseline table further down was scored on the earlier sets
> (`3fd78561` / `2d6b2599`) and is kept as recorded; the transformer run will use the
> current ones.

Build: `python scripts/ood_eval.py build --held-out both` →
`data/processed/hardening/<held_out>/{indist.jsonl, ood_<held_out>.jsonl, manifest.json}`.

## Corpus changes

### BIPIA un-capped, within what the splitter can hold

The canonical corpus capped BIPIA at about 350/350. Here the caps are raised to
1,100 per class, and the binding constraint became **hosts per attack**: BIPIA
reuses each attack across many host contexts, so more hosts per attack chains
groups into large connected components that one split swallows. Sweep (caps 1,100):

| hosts / attack | BIPIA injection / benign | attack families | positives train / dev / test |
|---|---|---|---|
| 2 | 300 / 779 | 29 | 210 / 40 / 50 |
| **4 (chosen)** | **600 / 779** | **29** | **420 / 120 / 60** |
| 8 | 1,100 / 779 | 27 | 40 / 1,060 / 0 |
| 16 | 1,100 / 779 | 14 | 1,100 / 0 / 0 |

4 is the largest setting that keeps positive support in all three splits.

### `tool_metadata` thickened (opt-in, canonical corpus untouched)

`data/seed/hardening/` adds authored MCP-manifest data loaded only through
`BuiltinSeedLoader(extra_seed_dirs=...)`: seven attack families with two variants
each (tool shadowing, hidden-parameter exfiltration, scope expansion, response
steering, persistent directive, consent suppression, webhook mirroring; all
destinations `.invalid`), 12 tool manifests, benign distractors and four hard
negatives. Rebuilding the canonical corpus without it still gives digest
`0311c325`.

In-distribution test `tool_metadata` support: **18 positives of 72** (canonical
test: 5 positives). These families are authored for this project; they are not
MCPTox categories.

### Answer-shaping (soft-claim) content manipulation

Added 2026-09-16 after a reported miss: an instruction that fixes what the answer
must claim, without contradicting the document or naming a destination, scored 0.591
with the transformer (operating point 0.9954), while a self-contradicting version
scored 0.9998. Two families, `answer_shaping_claim` and `assert_over_source`
(`content_manipulation`, `rag_document` + `tool_response`), vary domain, verb and
framing so the model sees the move rather than a phrase. Four neutral prose hosts
carry them.

Four benign hard negatives were added with them, because positives alone would teach
that any sentence about answering is an attack: two human-directed style guides, a
warning that quotes the attack, and a one-sided framing paragraph that instructs
nobody (benign by `docs/annotation_guideline.md`). On the rebuilt sets the rule fires
on 25 injections and 19 benign records, and **no benign record reaches the rules-only
operating point** (highest 0.416).

## Benchmarks inspected

* **AgentDojo** ([ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo), MIT).
  Suites are YAML environments whose `injection_vectors.yaml` holds *benign
  defaults*; the attack text is produced at run time by Python attack classes, so
  using it means installing the package and running its pipeline rather than
  reading static files. Deferred: licence fine, extraction needs its runtime.
* **MCPTox** ([repository](https://github.com/zhiqiangwang4/MCPTox-Benchmark),
  [arXiv:2508.14925](https://arxiv.org/abs/2508.14925)). At inspection the
  repository README contained only a title line and no LICENSE file was found. No
  licence means no permission to use the data, so it is not used.

## Results: baselines (scored once, 2026-09-15, CPU)

Command: `python scripts/ood_eval.py eval --held-out both --systems baselines`
(log: `artifacts/results/ood/baseline_eval.log`; JSON:
`artifacts/results/ood/<held_out>/ood_baselines.json`).

**Held out InjecAgent**

| system | dev AUPRC | in-dist test AUPRC | test `tool_metadata` AUPRC (18 pos) | OOD AUPRC | OOD recall @ dev 1%-FPR |
|---|---|---|---|---|---|
| majority | 0.400 | 0.314 | 0.250 | 0.985 (n/i) | 0.000 |
| keyword | 0.392 | 0.368 | 0.250 | 0.985 (n/i) | 0.000 |
| tfidf-word | 0.689 | 0.610 | 0.461 | 0.996 (n/i) | 0.022 |
| tfidf-word+char | 0.668 | 0.628 | 0.405 | 0.996 (n/i) | 0.016 |
| rules-only | 0.555 | 0.580 | 0.712 | 0.986 (n/i) | 0.000 |

**Held out BIPIA**

| system | dev AUPRC | in-dist test AUPRC | test `tool_metadata` AUPRC (18 pos) | OOD AUPRC | shift | OOD recall @ dev 1%-FPR | OOD realised FPR |
|---|---|---|---|---|---|---|---|
| majority | 0.279 | 0.283 | 0.250 | 0.435 | +0.152 | 0.000 | 0.0000 |
| keyword | 0.269 | 0.409 | 0.250 | 0.435 | +0.026 | 0.000 | 0.0000 |
| tfidf-word | 0.790 | 0.640 | 0.500 | 0.598 | −0.042 | 0.697 | 0.5096 (over budget) |
| tfidf-word+char | 0.848 | 0.680 | 0.480 | 0.610 | −0.070 | 0.633 | 0.2824 (over budget) |
| rules-only | 0.776 | 0.798 | 0.712 | 0.469 | −0.329 | 0.050 | 0.0218 (over budget) |

### What this says

* **InjecAgent as an unseen source.** After deduplication the held-out set is 98.5%
  injections (1,054 vs 16 benign), so its AUPRC is not informative. The informative
  number is recall at the dev-chosen 1%-FPR threshold: **at most 0.022 for every
  baseline, 0.000 for rules-only**. Operating points calibrated without InjecAgent
  catch almost none of its tool-response injections. (Realised FPR on 16 benign
  records is not meaningful.)
* **BIPIA as an unseen source** (informative: 600 / 779). Rules-only falls from
  0.798 in-distribution to **0.469** OOD (−0.329) and catches 5% of injections at
  its dev threshold. TF-IDF holds AUPRC near 0.60, but its dev thresholds do not
  transfer: realised FPR is 28–51% against a 1% budget.
* **The drop is the finding.** Lexical and rule systems tuned on authored data plus
  one benchmark do not hold on a benchmark they have not seen. Whether the
  transformer does better is the open question the GPU run answers.
* **`tool_metadata` now has measurable support** (18 test positives); rules-only
  reaches 0.712 there, the lexical baselines 0.41–0.50.

## Results on the current hardened sets (2026-09-16, scored once)

Baselines were re-scored on the rebuilt sets by the same kit; the transformer rows
are three seeds (`20250909/10/11`). JSON: `artifacts/results/ood/<held_out>/`
(`ood_baselines.json`, `ood_transformer.json`); the earlier-digest baselines are
archived in `artifacts/archive/results/ood/pre_answer_shaping_2026-09-16/`.

**Held out BIPIA** (OOD 600 injection / 779 benign: AUPRC informative)

| system | dev AUPRC | in-dist test AUPRC | OOD AUPRC | OOD recall @ dev 1% | OOD realised FPR |
|---|---|---|---|---|---|
| majority | 0.279 | 0.286 | 0.435 | 0.000 | 0.0000 |
| keyword | 0.279 | 0.293 | 0.435 | 0.000 | 0.0000 |
| tfidf-word | 0.656 | 0.660 | 0.564 | 0.000 | 0.0000 |
| tfidf-word+char | 0.663 | 0.697 | 0.581 | 0.002 | 0.0000 |
| rules-only | 0.792 | 0.714 | 0.469 | 0.050 | 0.0218 (over) |
| transformer seed 09 | 0.726 | 0.890 | 0.719 | 0.087 | 0.0077 |
| transformer seed 10 | 0.653 | 0.845 | 0.676 | 0.027 | 0.0000 |
| transformer seed 11 | 0.703 | 0.846 | 0.626 | 0.020 | 0.0026 |
| **transformer mean ± std** | 0.694 ± 0.031 | 0.861 ± 0.021 | **0.673 ± 0.038** | 0.044 ± 0.030 | — |

**Held out InjecAgent** (OOD 1,054 injection / 16 benign: AUPRC not informative)

| system | dev AUPRC | in-dist test AUPRC | OOD AUPRC | OOD recall @ dev 1% |
|---|---|---|---|---|
| majority | 0.396 | 0.314 | 0.985 (n/i) | 0.000 |
| keyword | 0.389 | 0.316 | 0.985 (n/i) | 0.000 |
| tfidf-word | 0.589 | 0.591 | 0.996 (n/i) | 0.000 |
| tfidf-word+char | 0.553 | 0.582 | 0.995 (n/i) | 0.000 |
| rules-only | 0.564 | 0.538 | 0.986 (n/i) | 0.000 |
| transformer seed 09 | 0.941 | 0.972 | 0.994 (n/i) | 0.000 |
| transformer seed 10 | 0.965 | 0.982 | 0.994 (n/i) | 0.000 |
| transformer seed 11 | 0.972 | 0.987 | 0.992 (n/i) | 0.000 |
| **transformer mean ± std** | 0.959 ± 0.013 | 0.980 ± 0.007 | 0.993 (n/i) | **0.000** |

**In-distribution breakdowns (test, at the dev 1% threshold)**

| held out | system | `tool_metadata` AUPRC (18 pos / 72) | content-manipulation recall (27 pos) |
|---|---|---|---|
| InjecAgent | rules-only | 0.712 | 0.000 |
| InjecAgent | transformer seeds 09 / 10 / 11 | 0.920 / 0.917 / 0.905 | 0.222 / 0.481 / 0.370 |
| BIPIA | rules-only | 0.712 | 0.296 |
| BIPIA | transformer seeds 09 / 10 / 11 | 0.742 / 0.663 / 0.672 | 0.222 / 0.037 / 0.222 |

### What this says

1. **The transformer degrades under source shift, but less than anything else.** With
   BIPIA held out it loses 0.187 ± 0.023 AUPRC against its own in-distribution test,
   yet stays above every baseline (best baseline 0.581).
2. **The operating point is what breaks.** A dev-chosen 1% threshold catches 4.4% of
   held-out BIPIA injections and 0% of held-out InjecAgent's, although InjecAgent's
   positives are ranked high. Ranking transfers far better than calibration; a
   deployment facing a new source must recalibrate on that source.
3. **The thin channel is now measurable.** `tool_metadata` has 18 test positives, and
   the transformer reaches 0.905–0.920 AUPRC there when trained with BIPIA in the pool.
4. **Soft-claim content manipulation is not solved by retraining.** Recall on 27
   content-manipulation positives stays low at the strict threshold. The grouped
   splitter placed `answer_shaping_claim` wholly in train and `assert_over_source`
   wholly in test, so the test measures generalisation to an unseen phrasing family:
   the released canonical checkpoint flags **0 / 9** of those records (highest 0.344
   against 0.9954), while `answer_shaping.v1` fires on **9 / 9**, and 0 of the 11
   style-guide hard negatives in test are flagged by either. The hardened checkpoints
   were not returned, so per-family recall for the retrained models is not available.

## Transformer run (kit, for reference)

`scripts/hardening_kit.ps1` / `.sh` trains three seeds per direction on the hardened
train split (checkpoint `artifacts/models/transformer_hardening_<held_out>`,
separate from the canonical one), then scores test and OOD once. Results land in
`artifacts/results/ood/<held_out>/ood_transformer.json`.

## Limitations

* Two held-out directions over three sources is a small shift study, not a general
  robustness claim.
* The InjecAgent direction has too few benign OOD records for AUPRC or FPR.
* The hardening metadata families are authored by the project team; they add
  support but not independent provenance.
