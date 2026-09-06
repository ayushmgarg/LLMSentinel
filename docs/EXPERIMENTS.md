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
