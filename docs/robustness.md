# Robustness and generalisation

Section 12 of the checklist. Reproduce with:

```bash
python scripts/robustness_suite.py            # rules-only
python scripts/robustness_suite.py --checkpoint artifacts/models/transformer
python scripts/placement_robustness.py        # attack-position probe
```

All probes are **measurement, not tuning**: the rules-only dev threshold
(`fpr=0.01`, 0.8751) is applied unchanged, and no design choice is made from
these numbers. Failures are recorded here rather than silently removed.

## Method

Robustness is measured as **recall kept**. We start from the injection positives
the detector already flags at baseline (original text, score ≥ threshold), apply
one meaning-preserving transform, and measure how often detection survives. The
same transforms are applied to hard negatives to check they do not manufacture
false positives. Measuring against positives the detector never caught would
report sampling noise, not robustness.

Transforms live in `llmsentinel.robustness.perturbations`, grouped as *surface*
(whitespace, casing, punctuation, quoting, Markdown, code fences), *unicode*
(full-width homoglyphs, zero-width insertion, bidi wrapping, base64 embedding),
and *rewrite* (synonym swap, declarative framing, long-context dilution, benign
distractors).

## 1. Perturbation robustness (rules-only, 47 detected positives, 60 hard negatives)

| transform | group | recall kept | mean risk | hard-neg FPR |
|---|---|---|---|---|
| original | baseline | 1.00 | 0.908 | 0.00 |
| whitespace | surface | 1.00 | 0.908 | 0.00 |
| casing | surface | 1.00 | 0.908 | 0.00 |
| punctuation | surface | 0.79 | 0.826 | 0.00 |
| quote_wrap | surface | 1.00 | 0.909 | 0.07 |
| markdown_blockquote | surface | 1.00 | 0.909 | 0.12 |
| code_fence | surface | 1.00 | 0.915 | 0.15 |
| fullwidth | unicode | 0.96 | 0.871 | 0.02 |
| zero_width | unicode | 1.00 | 0.925 | 0.07 |
| bidi_wrap | unicode | 1.00 | 0.944 | 0.15 |
| base64_embed | unicode | 0.00 | 0.202 | 0.00 |
| synonym | rewrite | 0.91 | 0.885 | 0.00 |
| declarative | rewrite | 0.98 | 0.907 | 0.00 |
| dilution | rewrite | 0.96 | 0.913 | 0.03 |
| distractors | rewrite | 0.96 | 0.909 | 0.02 |

### Failures and mitigations

- **base64_embed — recall 0.00.** The rules *scorer* scores a record's own text
  and does not decode an embedded base64 blob, so a base64-hidden payload evades
  it entirely. This is a scorer/eval limitation, not a pipeline one: the
  `llmsentinel scan` path already normalises and analyses *derived* units
  (`Normalizer.derived_units`), which decode bounded base64 regions, so the full
  guard recovers the payload. *Mitigation:* fold derived-unit analysis into the
  scorer's aggregate score, or gate on the normalisation evidence flag that base64
  decoding already raises.
- **punctuation — recall 0.79.** Inserting commas inside phrases splits some
  multi-word trigger regexes (e.g. "ignore all previous instructions"), dropping
  one positive in five. *Mitigation:* make the high-value patterns tolerant of
  intervening punctuation, or score on a punctuation-stripped view in parallel.
- **quote_wrap / markdown_blockquote / code_fence — hard-neg FPR 0.07–0.15.**
  Wrapping a *benign hard negative* in quotes or a fence shifts the context
  suppression and turns a few hard negatives into false positives. This is the
  known cost of "suppression is expensive to buy": formatting alone cannot buy
  suppression, so adding formatting to otherwise-benign-but-alarming text nudges
  it upward. *Mitigation:* treat a fence/quote that wraps the *entire* input as a
  stronger suppression signal than one wrapping a fragment.
- **zero_width / bidi_wrap — hard-neg FPR 0.07 / 0.15.** The obfuscation rule
  fires on *any* zero-width or bidi control, including in benign text, so
  injecting them into hard negatives raises false positives even though recall on
  positives is unaffected. *Mitigation:* weight concealment evidence by density
  and require a co-occurring directive signal before it lifts the score.

### What held

Whitespace, casing, quoting and Markdown keep recall at 1.00 on positives;
full-width and zero-width keep 0.96–1.00 because NFKC folding and zero-width
stripping run before scoring; dilution and distractors keep 0.96 because the
engine aggregates by the highest-risk unit and does not dilute. Synonym swaps
cost a little recall (0.91), the expected brittleness of any lexicon-anchored
component and the motivation for the transformer in the hybrid.

## 2. Cross-channel transfer (tfidf-word, AUPRC)

Train the lexical baseline on one channel, test on another (disjoint by
construction).

| train \ test | rag_document | tool_response | tool_metadata |
|---|---|---|---|
| rag_document | 0.979 | 0.875 | 0.777 |
| tool_response | 0.716 | 1.000 | 0.810 |
| tool_metadata | 0.558 | 0.578 | 1.000 |

In-channel AUPRC (diagonal) is high; transfer degrades off-diagonal, worst when
training on the small, narrow `tool_metadata` channel and testing on documents
(0.558). The takeaway: a detector trained on one channel does not transfer for
free, which is the argument for the channel-balanced corpus and for reporting
per-channel numbers rather than a pooled figure.

## 3. Metadata vs tool-response scanning (rules-only, AUPRC)

| channel | n / positives | AUPRC |
|---|---|---|
| tool_response | 680 / 354 | 0.619 |
| tool_metadata | 125 / 33 | 0.735 |

Reported separately because a tool manifest (advertised metadata) and a tool
response (returned data) are different surfaces with different base rates; a
pooled number hides the gap. The metadata channel is small (33 positives) and
its number is a sanity signal, not a headline result.

## 4. Attack position

See `scripts/placement_robustness.py` and the experiment log: the rules engine
is position-invariant by construction (it scores the highest-risk unit and
aggregates by max), so a payload at the beginning, middle, or end of a long
document scores identically. The windowed transformer is the position- and
dilution-sensitive component. The script accepts `--checkpoint` for it, but that
probe was **not run** before the canonical results were reported -- a gap this
document previously glossed. The fresh evaluation set later exposed exactly this
failure: a payload that scores ≈1.0 on its own scored ≈0 inside a short benign
paragraph (docs/EXPERIMENTS.md, 2026-09-27). Segment-level scoring, confirmed on a
second blind set, is the fix now deployed; see `docs/fresh_evaluation.md`.

## Out of scope (stated limitations)

- **Genuine paraphrase.** Reliable paraphrase needs a model and a human check;
  the `synonym` and `declarative` transforms here are weak lexical
  approximations and are labelled as such.
- **Multilingual robustness.** The corpus is English; cross-lingual evaluation
  needs a suitable multilingual benchmark and is left to future work.
- **Adaptive / white-box attackers.** These probes are fixed transforms, not an
  adaptive adversary optimising against the detector.
