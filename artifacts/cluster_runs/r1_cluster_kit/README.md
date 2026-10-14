# Cluster round r1_cluster_kit (SVKM Altair, 2026-10-12/13)

Untouched copy of `r1_cluster_kit_results.zip` as it came back from the cluster: every result
file the round wrote, the fresh-set ledger, and all logs. The zips themselves were removed
after every extracted file was checked against the zip's CRC (73 files, 0 mismatches).

- Code: commit `357507e` (clean), Python 3.14, torch 2.14.0+cu130, transformers 5.16.1.
- GPU: NVIDIA H100 PCIe, MIG 3g.40gb slice; 1 CPU core.
- Plan: `logs/plan.normalized` (= `altair/plans/round1.txt`); timings: `logs/timing.csv`.
- All 10 steps exit 0 (`logs/STATUS`). The first attempt on 2026-10-12 failed at `hardening`
  (`ModuleNotFoundError: llmsentinel`, the project was not on `PYTHONPATH`); it was resumed on
  2026-10-13 with `PYTHONPATH` set, and finished steps were not rerun. Compute: ~26 min.
- Fresh set v3 scored once: `artifacts/results/fresh_runs.json`, status `completed`, not forced.

## Where the copies were placed

| From here | Placed at |
|---|---|
| `artifacts/results/augmented/`, `fresh_v3/`, `real_model/`, `paraphrase/`, `fresh_runs.json` | same paths in the project (new, nothing replaced) |
| `data/processed/paraphrase/` | same path (new) |
| `artifacts/results/calibration/per_source.json` | same path; it **replaced** the laptop CPU run, which is kept as `per_source.laptop_cpu_2026-10-11.json`. The cluster file is a superset: the laptop's rules-only and TF-IDF rows are byte-identical, plus two transformer rows |
| `r1_cluster_kit_models.zip` | `artifacts/models/transformer_hardening_{bipia,injecagent}`, `transformer_augmented_seed{20250909,20250910,20250911}`, `transformer_control_seed{20250909,20250910,20250911}` (not in git; ~332 MB each) |
