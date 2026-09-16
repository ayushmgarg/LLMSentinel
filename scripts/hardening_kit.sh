#!/usr/bin/env bash
# LLMSentinel — section 16a hardening / out-of-distribution run (macOS / Linux)
#
# For each held-out source (InjecAgent, then BIPIA) trains the transformer (3 seeds)
# on that direction's HARDENED in-distribution train split and scores its test split
# and its held-out OOD set once.
# Uses only the committed data/processed/hardening files: no benchmark download.
#
#     bash scripts/hardening_kit.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/5  Virtual environment =="
[ -d .venv ] || python3 -m venv .venv
py=".venv/bin/python"

echo "== 2/5  Core dependencies =="
"$py" -m pip install --upgrade pip
"$py" -m pip install -r requirements.txt -e .

echo "== 3/5  Transformer extra (torch from the PyTorch index, then the rest) =="
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "   NVIDIA GPU detected -> CUDA build (cu121)"
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121
else
  echo "   No NVIDIA GPU -> CPU build (this run will take hours on CPU)"
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu
fi
"$py" -m pip install "transformers>=4.40" "datasets>=2.19"

echo "== 4/5  Baselines on both hardening sets (fast) =="
"$py" scripts/ood_eval.py eval --held-out both --systems baselines

echo "== 5/5  Transformer, 3 seeds x 2 held-out sources (InjecAgent, BIPIA) =="
"$py" scripts/ood_eval.py eval --held-out both --systems transformer --seeds 20250909,20250910,20250911 --device auto

echo ""
echo "DONE. Send this whole folder back to Ayush:"
echo "  artifacts/results/ood/   (injecagent/ and bipia/ JSON results)"
