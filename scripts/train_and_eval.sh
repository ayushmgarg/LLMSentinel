#!/usr/bin/env bash
# LLMSentinel — one-shot training + evaluation (macOS / Linux)
#
# Retrains the transformer from the committed corpus (no dataset download),
# scores the held-out test split once, and regenerates the report figures.
# Run from the project root:
#
#     bash scripts/train_and_eval.sh
#
# See docs/TRAINING_HANDOFF.md for what to send back.
set -euo pipefail
cd "$(dirname "$0")/.."   # project root

echo "== 1/5  Creating virtual environment (.venv) =="
[ -d .venv ] || python3 -m venv .venv
py=".venv/bin/python"

echo "== 2/5  Installing core dependencies =="
"$py" -m pip install --upgrade pip
"$py" -m pip install -r requirements.txt -e .

echo "== 3/5  Installing transformer extra (CPU wheels) =="
"$py" -m pip install -r requirements-transformer.txt --index-url https://download.pytorch.org/whl/cpu

echo "== 4/5  Training the transformer (~1 hr on CPU) =="
"$py" scripts/train_transformer.py --epochs 3

echo "== 5/5  Evaluating on test (once) and drawing figures =="
"$py" -m llmsentinel.cli evaluate --test
"$py" scripts/make_figures.py

echo ""
echo "DONE. Send these back to Ayush:"
echo "  artifacts/models/transformer/   (the trained checkpoint)"
echo "  artifacts/results/results_dev.json"
echo "  artifacts/results/results_test.json"
echo "  artifacts/figures/*.png"
