$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "`nBackend ready. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "Next: ollama pull qwen2.5:7b ; ollama pull qwen2.5:3b ; .\scripts\check-env.ps1"
