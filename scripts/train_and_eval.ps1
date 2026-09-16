# LLMSentinel — one-shot training + evaluation (Windows PowerShell)
#
# Retrains the transformer from the committed corpus (no dataset download),
# scores the held-out test split once, and regenerates the report figures.
# Run from the project root:
#
#     powershell -ExecutionPolicy Bypass -File scripts\train_and_eval.ps1
#
# See docs/TRAINING_HANDOFF.md for what to send back.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # project root

Write-Host "== 1/5  Creating virtual environment (.venv) ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"

Write-Host "== 2/5  Installing core dependencies ==" -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -e .

Write-Host "== 3/5  Installing transformer extra ==" -ForegroundColor Cyan
$gpu = $false
try { nvidia-smi *> $null; if ($LASTEXITCODE -eq 0) { $gpu = $true } } catch {}
# torch first, from the PyTorch index (its --index-url replaces PyPI, so it must
# be its own step); then transformers/datasets from PyPI.
if ($gpu) {
  Write-Host "   NVIDIA GPU detected -> installing CUDA build (cu121)" -ForegroundColor Green
  & $py -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121
} else {
  Write-Host "   No NVIDIA GPU found -> installing CPU build" -ForegroundColor Yellow
  & $py -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu
}
& $py -m pip install "transformers>=4.40" "datasets>=2.19"

Write-Host "== 4/5  Training 3 seeds on the stratified corpus (minutes on a GPU) ==" -ForegroundColor Cyan
& $py scripts\train_seeds.py --seeds 20250909,20250910,20250911 --device auto

Write-Host "== 5/5  Evaluating on test (once) and drawing figures ==" -ForegroundColor Cyan
& $py -m llmsentinel.cli evaluate --test
& $py scripts\make_figures.py

Write-Host ""
Write-Host "DONE. Send these back to Ayush:" -ForegroundColor Green
Write-Host "  artifacts\models\transformer\      (canonical checkpoint, seed 20250909)"
Write-Host "  artifacts\results\results_dev.json"
Write-Host "  artifacts\results\results_test.json"
Write-Host "  artifacts\results\seed_variance.json   (the 3-seed spread)"
Write-Host "  artifacts\figures\*.png"
