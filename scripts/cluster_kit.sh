#!/usr/bin/env bash
# LLMSentinel cluster run (GPU). Everything heavy. Steps 5 and 7-8 analyse sets that were
# already scored once, post-hoc and labelled as such; step 6 is the single scoring of v3.
#
#     bash scripts/cluster_kit.sh                 # steps 0-6
#     LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen3:4b-instruct bash scripts/cluster_kit.sh
#                                                 # also steps 7-8 (needs a model server on the node)
#
# What it produces, and why (docs/CLUSTER_RUN.md):
#   3  transformer_hardening_{bipia,injecagent}   -> per-source calibration rows (B1/F7)
#   4  transformer_{augmented,control}_seed*      -> does position augmentation help (B4, redefined)?
#   5  calibration with the transformer           -> artifacts/results/calibration/
#   6  ONE scoring of fresh set v3: canonical + 3 augmented + 3 control, with pre-registered
#      augmented-vs-control tests                 -> artifacts/results/fresh_v3/
#   7  paraphrases of fresh and train payloads    -> data/processed/paraphrase/  (B2)
#   8  real-model attack success and cost         -> artifacts/results/real_model/ (F3/F4/B7)
# On exit -- success or failure -- everything that exists is packed into
# llmsentinel_cluster_outputs.tgz.
set -euo pipefail
cd "$(dirname "$0")/.."

pack() {
  echo "== Packing outputs =="
  local items=()
  for item in artifacts/models/transformer_hardening_* artifacts/models/transformer_augmented_seed* \
              artifacts/models/transformer_control_seed* artifacts/results/augmented artifacts/results/calibration \
              artifacts/results/fresh_v3 artifacts/results/fresh_runs.json artifacts/results/real_model \
              artifacts/results/paraphrase data/processed/paraphrase; do
    if [ -e "$item" ]; then items+=("$item"); fi
  done
  if [ ${#items[@]} -gt 0 ]; then
    tar czf llmsentinel_cluster_outputs.tgz "${items[@]}"
    echo "   llmsentinel_cluster_outputs.tgz: ${#items[@]} item(s). Bring it back and unpack it in the project folder."
  else
    echo "   nothing to pack"
  fi
}
trap pack EXIT

echo "== 0/8  Preflight =="
if [ ! -f artifacts/models/transformer/llmsentinel_config.json ]; then
  echo "   MISSING artifacts/models/transformer (the canonical checkpoint is not in git)."
  echo "   Copy it from the laptop first, e.g.:  scp -r artifacts/models/transformer <cluster>:<repo>/artifacts/models/"
  exit 1
fi
if [ -n "$(git status --porcelain -- src scripts data/processed/augmented data/fresh 2>/dev/null)" ]; then
  echo "   WARNING: uncommitted changes under src/, scripts/ or data/; the run may not match the repository."
fi

echo "== 1/8  Environment =="
[ -d .venv ] || python3 -m venv .venv
py=".venv/bin/python"
"$py" -m pip install --upgrade pip
"$py" -m pip install -r requirements.txt -e .
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121
else
  echo "   WARNING: no NVIDIA GPU visible; training will be very slow"
  "$py" -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu
fi
"$py" -m pip install "transformers>=4.40" "datasets>=2.19"

echo "== 2/8  Verify the committed augmentation (must print OK) =="
"$py" scripts/augment_embedded.py --check

echo "== 3/8  Hardening checkpoints (train only; held-out sets are NOT scored) =="
"$py" scripts/ood_eval.py train --held-out both --device auto

echo "== 4/8  Augmented and control transformers, 3 seeds each =="
"$py" scripts/train_augmented.py --seeds 20250909,20250910,20250911 --control --device auto

echo "== 5/8  Per-source calibration with the hardening checkpoints (post-hoc) =="
"$py" scripts/calibrate_per_source.py --transformer

echo "== 6/8  Fresh set v3: scored ONCE, all checkpoints together =="
# fresh_eval.py refuses a digest already entered in artifacts/results/fresh_runs.json.
"$py" scripts/fresh_eval.py --fresh data/fresh/fresh_eval_v3.yaml --out artifacts/results/fresh_v3 \
  --extra augmented_s1=artifacts/models/transformer_augmented_seed20250909 \
  --extra augmented_s2=artifacts/models/transformer_augmented_seed20250910 \
  --extra augmented_s3=artifacts/models/transformer_augmented_seed20250911 \
  --extra control_s1=artifacts/models/transformer_control_seed20250909 \
  --extra control_s2=artifacts/models/transformer_control_seed20250910 \
  --extra control_s3=artifacts/models/transformer_control_seed20250911 \
  --compare augmented_s1:control_s1 --compare augmented_s2:control_s2 --compare augmented_s3:control_s3

if [ -n "${LLM_BASE_URL:-}" ]; then
  echo "== 7/8  Paraphrases (model: ${LLM_MODEL:-qwen3:4b-instruct}) =="
  "$py" scripts/paraphrase_attacks.py generate --source fresh --variants 3
  "$py" scripts/paraphrase_attacks.py generate --source train --variants 2
  "$py" scripts/paraphrase_attacks.py measure

  echo "== 8/8  Real-model attack success and cost (post-hoc on v1/v2) =="
  "$py" scripts/real_model_eval.py
else
  echo "== 7-8/8  skipped: set LLM_BASE_URL (and LLM_MODEL) to run paraphrases and the real-model evaluation =="
fi

echo ""
echo "DONE (the archive is written on exit)."
