# Experiment log

One entry per run that produced a number anybody might quote. Entries are
append-only; a corrected entry gets a new line that says what it supersedes.

Format: date · what · data_version (corpus digest) · seed · command · result ·
observation.

---

## 2026-09-06 · Split-seed selection (structural, no scores)

**Why.** With the original seed the corpus had no positive `tool_metadata`
examples in the dev split, so that channel could be neither calibrated nor
claimed. The split assignment is a hash of `(seed, grouping key)`, so per-cell
coverage varies with the seed.

**Method.** Built the corpus for seeds 20250906-20250917 and recorded, for each,
the smallest number of injection examples in any `(split, channel)` cell. No
model was trained and no metric was computed; the criterion is corpus structure
only, so this selection cannot have tuned any result.

| seed | records | min positives per (split, channel) | cells with < 5 positives |
|---|---|---|---|
| 20250906 | 800 | 0 | dev/tool_metadata |
| 20250907 | 1338 | 0 | test/tool_response |
| 20250908 | 900 | 0 | test/tool_metadata, dev/tool_metadata |
| **20250909** | **1803** | **24** | **none** |
| 20250910 | 909 | 6 | none |
| 20250911 | 1172 | 13 | none |
| 20250912 | 1971 | 0 | dev/tool_metadata |
| 20250913 | 783 | 6 | none |
| 20250914 | 783 | 6 | none |
| 20250915 | 2340 | 0 | test/rag_document |
| 20250916 | 2207 | 0 | test/tool_metadata |
| 20250917 | 1263 | 15 | none |

**Outcome.** `DEFAULT_SEED = 20250909`. Every channel has positives in every
split, no record is dropped for crossing a group boundary, and the corpus is the
largest of the fully covered candidates.

**Caveat.** Seed choice does not create data. The metadata channel is still
built from a small number of payload families, and the corpus card's per-cell
table remains the reference for what each channel can support.

---

## 2026-09-06 · Rule-engine sanity run (not a result)

**Why.** Confirm the rule engine runs end to end after the suppression and
task-conflict changes, and that no rule fails silently.

**Command.** Rules-only scoring of the dev split, `RuleEngine()` defaults, with
`host_task` passed from each record.

**Observed (seed 20250906 corpus, superseded by the seed change above).**
AUPRC 0.795, AUROC 0.891, TPR@1% FPR 0.280, hard-negative FPR 0.000, rule
failures 0.

**Status: not a reportable result.** Thresholds were derived on the same split
being scored, the corpus is synthetic-only, and the rule weights were set by
hand rather than fitted. It is recorded to show the pipeline executes and the
error telemetry reports a healthy run, nothing more.

---

## 2026-09-06 · Manual corpus inspection (20 random + 20 hard negatives)

**Command.** `llmsentinel corpus inspect -n 20` and
`llmsentinel corpus inspect -n 20 --hard-negatives`, corpus digest
`73f127176aad1013`.

**Labels.** All 40 records were adjudicated against
[annotation_guideline.md](annotation_guideline.md). No label was wrong. Every
sampled hard negative is genuinely benign under the rule: policies addressed to
employees, API references addressed to developers, papers and moderation logs
quoting payloads, and legitimate imperatives ("Ignore the resting time printed
on the packet").

**Finding 1 — implausible channel/content pairings.** Benign insertions are
placed into hosts of any channel, so the corpus contains an exam rubric inside a
tool *description* and a glossary appended to a code snippet. The labels stay
correct and the pairings arguably strengthen the negatives, since a model cannot
lean on channel-topic priors. But a tool description would never carry an exam
rubric, so part of the `tool_metadata` result measures an artificial task.
*Not fixed in this run*: the transformer is training on this exact corpus, and
changing the data mid-experiment is what the protocol forbids. Planned fix:
give benign insertions the same per-channel plausibility declaration that
payloads already have in `payloads.yaml`.

**Finding 2 — truncated host leaves.** Injecting into a short JSON leaf yields a
visibly clipped host ("Exports above two million rows are split into several
assistant: Understood, ..."). Realistic for a chunked retrieval pipeline, but it
makes some tool-response records shorter and easier than a full document.

**Finding 3 — no positives sampled from `tool_metadata`** in the random draw of
20, which is consistent with the per-cell counts (24 of 279 dev records). The
corpus card's per-cell table remains the reference for what each channel can
support.

**Conclusion.** Labels are sound; realism is the limitation. Both findings are
recorded in the report's limitations section rather than silently corrected.

---

## 2026-09-06 · Rule-family evaluation on dev (negative result)

**Command.** `python scripts/rule_family_eval.py`, corpus digest
`73f127176aad1013`, dev split (279 records, 84 injection).

| family | alone (AUPRC) | engine without it (AUPRC) | Δ from removing |
|---|---|---|---|
| all families | — | 0.570 | — |
| meta_instruction | 0.791 | 0.325 | **+0.245** |
| obfuscation | 0.501 | 0.544 | +0.025 |
| exfiltration | 0.293 | 0.643 | −0.074 |
| task_conflict | 0.423 | 0.635 | −0.065 |
| metadata_poisoning | 0.301 | 0.610 | −0.041 |
| action_hijack | 0.299 | 0.578 | −0.009 |
| assistant_address | 0.301 | 0.578 | −0.008 |

**Finding.** The hand-weighted noisy-OR aggregate is *worse than its best single
family*: `meta_instruction` alone reaches 0.791 AUPRC while the full engine
reaches 0.570. Five of seven families have a negative Δ, meaning the engine
scores better with them switched off.

**Why.** Noisy-OR accumulates evidence, and the family weights were set by hand
rather than fitted. Families that fire weakly on many benign records —
`assistant_address` on any "you must", `exfiltration` on documentation that
mentions credentials — push benign scores up faster than they push positives up.
Combination without fitted weights is the problem, not the individual rules:
every family alone beats the majority baseline (0.301).

**Decision.** The aggregate is **not** re-weighted to make the rules-only number
look better. It is reported as the interpretable, hand-specified detector it is,
and the ablation is reported with it. The fusion layer is where rule signals are
supposed to earn their weights, and the hybrid row in the results table is the
test of whether they do. Nothing is dropped from the rule set on this evidence
alone: a family that hurts an unweighted OR can still carry information a fitted
model uses, and dropping it now would prejudge that.

**Protocol note.** This ablation and the three patterns added after the earlier
dev error analysis were both fitted on dev. Test has not been scored at this
point.
