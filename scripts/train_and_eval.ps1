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

Write-Host "== 3/5  Installing transformer extra (CPU wheels) ==" -ForegroundColor Cyan
& $py -m pip install -r requirements-transformer.txt --index-url https://download.pytorch.org/whl/cpu

Write-Host "== 4/5  Training the transformer (~1 hr on CPU; go get a coffee) ==" -ForegroundColor Cyan
& $py scripts\train_transformer.py --epochs 3

Write-Host "== 5/5  Evaluating on test (once) and drawing figures ==" -ForegroundColor Cyan
& $py -m llmsentinel.cli evaluate --test
& $py scripts\make_figures.py

Write-Host ""
Write-Host "DONE. Send these back to Ayush:" -ForegroundColor Green
Write-Host "  artifacts\models\transformer\   (the trained checkpoint)"
Write-Host "  artifacts\results\results_dev.json"
Write-Host "  artifacts\results\results_test.json"
Write-Host "  artifacts\figures\*.png"
