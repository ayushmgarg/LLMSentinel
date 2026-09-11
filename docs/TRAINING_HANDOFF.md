# Training handoff — run this on a spare machine

This kit retrains LLMSentinel's transformer detector and regenerates the results
and figures. It runs **entirely from the committed corpus** — no benchmark
download, no credentials, no network beyond installing Python packages.

## What it does

1. Creates a virtual environment and installs dependencies (CPU-only PyTorch).
2. Trains the `distilroberta-base` detector on the committed corpus
   (`data/processed/corpus.jsonl`, ~1,669 records).
3. Scores the held-out test split **once** and writes the results tables.
4. Regenerates the report figures.

It is deterministic (fixed seed `20250909`), so a re-run reproduces the same
checkpoint.

## Prerequisites

- **Python 3.10–3.13** (3.14 also works). Check with `python --version`.
- **~3 GB free disk** (model weights + wheels) and **internet for the first
  install only**.
- **~1 hour** on a typical laptop CPU. No GPU needed. A GPU is not required and
  not used by default.

## Steps

Unzip the project, open a terminal **in the project folder**, then:

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\train_and_eval.ps1
```

**macOS / Linux:**
```bash
bash scripts/train_and_eval.sh
```

Let it run to the end. The last lines print exactly what to send back.

## What to send back to Ayush

Zip and return these (everything the retrain produced):

- `artifacts/models/transformer/` — the trained checkpoint (~300 MB)
- `artifacts/results/results_dev.json`
- `artifacts/results/results_test.json`
- `artifacts/figures/*.png`

That's it — no source changes, nothing else.

## If something goes wrong

- **`python` not found:** install Python from python.org (tick "Add to PATH"),
  reopen the terminal.
- **PyTorch install fails:** re-run the script; the CPU wheel index
  (`--index-url https://download.pytorch.org/whl/cpu`) is already set.
- **"test was already scored" message:** harmless — it means test was scored for
  this corpus before. Re-run with the training step only, or ignore; the results
  files are already written.
- **Out of memory / very slow:** lower the batch size —
  `.venv\Scripts\python.exe scripts\train_transformer.py --epochs 3 --batch-size 4`
  then re-run the evaluate + figures steps.

## Notes

- Nothing here contacts a live service or handles real secrets; the corpus uses
  reserved `.invalid` destinations and placeholder credentials.
- To train on a *larger* dataset (raising the BIPIA/InjecAgent caps) you would
  need to clone those benchmarks first — that is a separate, bigger job and is
  **not** what this kit does.
