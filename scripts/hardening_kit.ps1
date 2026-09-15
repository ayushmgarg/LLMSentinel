# LLMSentinel — section 16a hardening / out-of-distribution run (Windows PowerShell)
#
# For each held-out source (InjecAgent, then BIPIA) trains the transformer (3 seeds)
# on that direction's HARDENED in-distribution train split and scores its test split
# and its held-out OOD set once.
# Uses only the committed data/processed/hardening files: no benchmark download.
# Run from the project root:
#
#     powershell -ExecutionPolicy Bypass -File scripts\hardening_kit.ps1
#
# See docs/TRAINING_HANDOFF.md ("Hardening / OOD run") for what to send back.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "== 1/5  Virtual environment ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"

Write-Host "== 2/5  Core dependencies ==" -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -e .

Write-Host "== 3/5  Transformer extra (torch from the PyTorch index, then the rest) ==" -ForegroundColor Cyan
$gpu = $false
try { nvidia-smi *> $null; if ($LASTEXITCODE -eq 0) { $gpu = $true } } catch {}
if ($gpu) {
  Write-Host "   NVIDIA GPU detected -> CUDA build (cu121)" -ForegroundColor Green
  & $py -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121
} else {
  Write-Host "   No NVIDIA GPU -> CPU build (this run will take hours on CPU)" -ForegroundColor Yellow
  & $py -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu
}
& $py -m pip install "transformers>=4.40" "datasets>=2.19"

Write-Host "== 4/5  Baselines on both hardening sets (fast) ==" -ForegroundColor Cyan
& $py scripts\ood_eval.py eval --held-out both --systems baselines

Write-Host "== 5/5  Transformer, 3 seeds x 2 held-out sources (InjecAgent, BIPIA) ==" -ForegroundColor Cyan
& $py scripts\ood_eval.py eval --held-out both --systems transformer --seeds 20250909,20250910,20250911 --device auto

Write-Host ""
Write-Host "DONE. Send this whole folder back to Ayush:" -ForegroundColor Green
Write-Host "  artifacts\results\ood\   (injecagent\ and bipia\ JSON results)"
