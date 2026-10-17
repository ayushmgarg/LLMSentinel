# Development round R2 (after cluster round r1)

One task at a time, each reviewed before the next. Laptop, CPU only; anything that needs a
GPU or the LLM is prepared here and runs in cluster round r2. Numbering is fixed: outputs
of task R2.n go to `artifacts/results/r2/<nn>_<name>/`, code and docs say "R2.n", and
`docs/EXPERIMENTS.md` gets one entry per task titled "R2.n". Not in this round: D1 (merge),
A1 (clean install), C1 (Claude Desktop), the paper, screenshots. A4 (inter-annotator agreement) dropped 2026-10-17.

| # | Task | Item | Runs where | Status |
|---|---|---|---|---|
| R2.1 | Fresh set v4, written and frozen **before** any R2 method exists | B0-style | laptop (authoring) | done: digest `b4020d05…` |
| R2.2 | NLI soft-claim check | B3 / F9 | laptop | done: post-hoc soft-claim recall 1→8/10, 1→5/6, 1→6/8, 0 false alarms |
| R2.3 | Semantic signals: task conflict (B12), similarity to confirmed attacks (B13) | B12, B13, F14 | laptop | done: B12 negative; B13 +4 injections, 0 false alarms, 0 paraphrases |
| R2.4 | Retrieval poisoning under each retriever | F13 | laptop | done: dense surfaces a bit more poison (51% vs 46%); guard flags ~same share (39% vs 36%) |
| R2.5 | Adaptive attacker, tier a, against rules-only | A3 / F11 | laptop | |
| R2.6 | Agentic rule-evolution loop (red team → analyst → gatekeeper) | discussed 2026-10-11 | laptop code; LLM part on cluster | |
| R2.7 | Active learning: reviewed cases → training data | B9 | laptop | |
| R2.8 | Paraphrase-augmentation retrain + seed ensemble (prepared) | B4 (original) | cluster | |
| R2.9 | Answer-quality judge (prepared) | F4 | cluster | |
| R2.10 | Cluster round r2 plan and zip (built, not run) | — | laptop | |
| R2.11 | Docs pass: README, report, fresh-evaluation doc | D2 | laptop | |
| R2.12 | Studio UI: plain restyle, system fonts, no external requests, phone-width fix | — | laptop | done |

**Protocol.** v4 is frozen in its own commit before R2.2 starts and is scored exactly once,
in cluster round r2, with every R2 system that has a score. Until then, R2 methods are
developed on train/dev and judged post-hoc on the spent sets (v1–v3, labelled as such).
