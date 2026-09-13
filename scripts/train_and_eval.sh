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

echo "== 3/5  Installing transformer extra =="
# torch first, from the PyTorch index (its --index-url replaces PyPI, so it must
# be its own step); then transformers/datasets from PyPI.
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "   NVIDIA GPU detected -> installing CUDA build (cu121)"
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121
else
  echo "   No NVIDIA GPU found -> installing CPU build"
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu
fi
"$py" -m pip install "transformers>=4.40" "datasets>=2.19"

echo "== 4/5  Training 3 seeds on the stratified corpus (minutes on a GPU) =="
"$py" scripts/train_seeds.py --seeds 20250909,20250910,20250911 --device auto

echo "== 5/5  Evaluating on test (once) and drawing figures =="
"$py" -m llmsentinel.cli evaluate --test
"$py" scripts/make_figures.py

echo ""
echo "DONE. Send these back to Ayush:"
echo "  artifacts/models/transformer/       (canonical checkpoint, seed 20250909)"
echo "  artifacts/results/results_dev.json"
echo "  artifacts/results/results_test.json"
echo "  artifacts/results/seed_variance.json    (the 3-seed spread)"
echo "  artifacts/figures/*.png"
