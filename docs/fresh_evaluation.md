# Fresh evaluation sets

The canonical test split and both out-of-distribution sets were each scored once and
are spent. Two small, authored sets measure what came after them without touching
them. Commands, digests and full numbers are in `docs/EXPERIMENTS.md` (2026-09-27).

| set | purpose | records | frozen before scoring |
|---|---|---|---|
| **v1** `data/fresh/fresh_eval.yaml` | first evaluation of the deployed decision rule, isolation, output check, manifest drift | 107 (54 injections) + 6 drift cases | commit `a97f4e4`, SHA-256 `1317e370…` |
| **v2** `data/fresh/fresh_eval_v2.yaml` | **confirm** the fix for the failure v1 exposed | 52 (24 injections) | commit `ab500e0`, SHA-256 `90b09375…`, before the fix existed |

Each host document has a `{{PAYLOAD}}` slot, so the injected span is exact and every
host also yields a clean **counterpart** (same text, no payload). Categories: blatant,
paraphrase (no stock trigger phrases), soft claim, hidden (HTML comment / zero-width /
base64), hard negatives that *mention* or *quote* attacks, and (v1) poisoned and clean
tool descriptions. Both sets are CC0, use reserved `.invalid` addresses, and were
written by this project — a bias towards the authors' idea of an attack, stated
wherever the numbers are used. Each is scored once per digest
(`scripts/fresh_eval.py` keeps a ledger).

## 1. What v1 showed

Thresholds recomputed on canonical dev, identical to `results_dev.json`.

| system | dev AUPRC | v1 AUPRC [95% CI] | v1 recall at dev 1% (FPR) |
|---|---|---|---|
| tfidf-word+char | 0.632 | 0.802 [0.689, 0.893] | 0.630 (0.151) |
| rules-only | 0.683 | 0.697 [0.580, 0.800] | 0.130 (0.019) |
| transformer | 0.964 | 0.661 [0.540, 0.789] | 0.204 (0.038) |
| hybrid (fusion) | 0.873 | 0.687 [0.563, 0.809] | 0.037 (0.000) |
| deployed OR rule | recall 0.825, FPR 0.006 | — | 0.204 (0.038) |

The transformer scored **≈0 on every blatant injection embedded in a document** and
≈1 on the same kind of payload in a JSON tool result. Post-hoc, the same seven payloads
scored 0.996–1.000 **alone** and 0.000–0.050 **inside their benign paragraph**: the
model recognises the instruction, but the surrounding prose masks it. These documents
fit in one window, so max-over-windows could not help; JSON results escaped because
each leaf is scored on its own. The canonical 0.984 therefore overstated how the model
handles an instruction placed inside ordinary prose it has not seen.

## 2. The fix, and its confirmation on v2

**Segment scoring** (`llmsentinel.models.segment`): the same checkpoint scores the
passage and each of its sentences (JSON: each string leaf's sentences) and keeps the
maximum. No retraining. The segmentation rule was fixed before any run; thresholds were
selected on canonical dev (`scripts/select_segment_thresholds.py`). v2 was written and
frozen before the scorer existed, then scored once:

| | dev AUPRC | v2 AUPRC [95% CI] | deployed rule on v2: recall / FPR |
|---|---|---|---|
| passage scoring | 0.964 | 0.748 [0.591, 0.887] | 0.208 / 0.000 |
| **segment scoring** | 0.938 | **0.865 [0.745, 0.958]** | **0.458 / 0.000** |

- Paired bootstrap, segment − passage on v2: **+0.117 AUPRC [0.027, 0.227], p = 0.007**.
- McNemar, deployed rule with vs without segments on v2: 6 records only the segment rule
  got right, 0 the other way (**p = 0.031**).
- No false positive on v2's 28 benign records, including 14 hard negatives that quote
  attack sentences.
- Cost on dev: AUPRC 0.964 → 0.938 (p = 0.001); the deployed rule's dev recall is
  unchanged (0.825) and its dev FPR falls from 0.6% to 0.0%.
- Cost on v1 (post-hoc for this fix): hard negatives flagged rose from 1 to 3 of 20.
- Still weak on v2: paraphrases 1 of 6, soft claims 1 of 6.

Segment scoring is now the default in the Studio, the SDK, the proxy and the gateway
(`--passage-scoring` restores the old behaviour).

## 3. Isolation quality (`scripts/isolation_eval.py`)

What the model would receive from the Studio guard as deployed. *Contained* = at most
20% of the payload's content words (base64: the blob) survive; *host kept* = share of the
genuine text that survives, measured against what retrieval delivers without the guard.

| | contained | contained when flagged | host kept when flagged | benign flagged | benign text removed |
|---|---|---|---|---|---|
| **v2, segment (deployed)** | **0.458** | 1.00 | 0.977 | 0.000 | 0.000 |
| v2, passage | 0.208 | 1.00 | 0.950 | 0.000 | 0.000 |
| v2, rules-only | 0.083 | 1.00 | 1.000 | 0.036 | 0.025 |
| v1, segment | 0.357 | 1.00 | 0.986 | 0.073 | 0.037 |
| v1, passage | 0.071 | 1.00 | 0.972 | 0.024 | 0.012 |

When the guard flags a passage it removes the payload every time and keeps almost all of
the genuine text; nothing was withheld whole. The limit is detection, not isolation.
(The first run of this script compared against the raw record, charging the guard for
JSON keys that are never delivered; it was corrected and re-run before any number was
used.)

## 4. Output-side check

Measured once on v1 after being built on non-fresh data: a claim is extracted from 8 of
10 soft-claim payloads (10 of 14 content-manipulation payloads), and falsely from 0 of 21
counterparts, 0 of 12 clean tool descriptions and 1 of 20 hard negatives (a negated
directive). On the sample pack with the simulator, it lifts rules-only containment from
3/6 to 6/6 without withholding any correct guarded answer — illustrative only; the
real-model attack success rate is still unmeasured.

## 5. Manifest drift

All six v1 drift cases come out as annotated (`tests/test_fresh_set.py`), including a
reordered declaration (unchanged) and an added parameter (changed). Detection on the 24
v1 tool descriptions: deployed rule recall 0.33 with no false positive on the 12 clean
ones.

## 6. Cost (`scripts/latency_eval.py`, this laptop's CPU)

Per passage: rules-only 6 ms, transformer passage 108 ms, **segment 256 ms**
(p95 426 ms), segment + isolation 358 ms. Output check 6 ms. Retrieval of the top 4 of 12
passages: TF-IDF 13 ms, dense 704 ms (the passages are re-embedded on every query). One-off
start-up: transformer 17 s, sentence encoder 4.3 s.

## Limits

- Small sets (v1: 54 injections; v2: 24), written by the project's authors.
- v1 is post-hoc for every change made after it; only v2 confirms the segment fix.
- No per-record test-split scores were ever saved, so no significance test exists for
  the canonical test numbers.
- Paraphrased injections and soft claims remain largely undetected by the model.
