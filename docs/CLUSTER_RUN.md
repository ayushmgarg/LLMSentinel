# Cluster run

Everything GPU-heavy goes through one script. Step 6 is the single scoring of fresh set
v3; steps 5, 7 and 8 analyse sets that were already scored once and are labelled
post-hoc in their outputs.

## Run it

1. On the cluster, clone the repository and check out `a1`.
2. Copy the canonical checkpoint from the laptop; it is not in git:
   `scp -r artifacts/models/transformer <cluster>:<repo>/artifacts/models/`
3. Run:

```bash
bash scripts/cluster_kit.sh
```

With a model server on the node (paraphrases and the real-model evaluation):

```bash
ollama serve &            # or vLLM / any OpenAI-compatible server
ollama pull qwen3:4b-instruct
LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen3:4b-instruct bash scripts/cluster_kit.sh
```

On exit — success or failure — everything that exists is packed into
`llmsentinel_cluster_outputs.tgz`. Bring it back and unpack it in the project folder.

## What each step is for

| Step | Produces | Answers | Protocol |
|---|---|---|---|
| 0 | — | Is the canonical checkpoint there? | Stops with instructions if not |
| 2 | — | Is the augmentation file the committed one? | Digest check; the run stops on mismatch |
| 3 | `transformer_hardening_{bipia,injecagent}` | Needed for per-source calibration (B1/F7) | Train only; held-out sets not scored. A single-seed retrain, not the §16a model |
| 4 | `transformer_augmented_seed*`, `transformer_control_seed*`, dev reports | Does embedded-injection (position) augmentation help? (B4 as redefined in REMAINING_THINGS, not paraphrase retraining) | Same seeds, config and machine with and without augmentation; dev only; test not read |
| 5 | `artifacts/results/calibration/per_source.json` | Does a threshold from clean target pages fix transfer? | Post-hoc on spent held-out sets; calibration half's clean pages only |
| 6 | `artifacts/results/fresh_v3/` | Augmented vs control (3 seeds each) and the canonical model, on data written before the augmentation | **Once.** Entered in `artifacts/results/fresh_runs.json` before scoring starts; any later attempt on v3 is refused. Augmented-vs-control tests are pre-registered (`--compare`) |
| 7 | `data/processed/paraphrase/`, `artifacts/results/paraphrase/robustness.json` | How much detection survives real paraphrase (B2)? | Rewrites validated automatically; post-hoc on spent fresh sets |
| 8 | `artifacts/results/real_model/` | Attack success with no defence, a prompt-only defence and LLMSentinel; cost on clean inputs (F3/F4/B7) | Objective success signals from the dataset; post-hoc on v1/v2 |

Rough cost on one modern GPU: steps 3–4 train 2 + 6 models (a few minutes each); step 6
scores seven checkpoints with segment scoring; steps 7–8 depend on the model server
(hundreds of short generations; on a laptop CPU one case took 8–15 minutes).

## Why the augmentation, and what it cannot show

In the canonical train split 277 of 315 document injections sit at the *end* of their
document and only 14 in the middle; the model learned that position and missed
instructions placed inside benign paragraphs (fresh v1). `data/processed/augmented/`
inserts train payloads into train hosts at the start, middle and end in equal shares
(`scripts/augment_embedded.py`; digest and diversity in its `manifest.json`). Nothing
outside the train split is read.

Stated limits, so the result is not over-read:

- **Not only position differs.** The augmented run also has 900 more positives (61% more
  records, more optimiser steps, different class balance). The control isolates
  "augmentation vs none", not "position vs everything else".
- **Low payload diversity.** The 900 records use 125 distinct payload texts (the train
  split has only 128 after filtering); one text is used up to 30 times. The augmentation
  teaches positions, not new wordings — paraphrased training data (step 7, `--source
  train`) is the follow-up.
- **v3 is authored by this project**, like v1 and v2.
