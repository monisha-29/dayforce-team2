Set-Location (Split-Path $PSScriptRoot -Parent)

function Check($name, $ok, $hint) {
    if ($ok) { Write-Host "[ OK ] $name" -ForegroundColor Green }
    else { Write-Host "[FAIL] $name  -> $hint" -ForegroundColor Red }
}

foreach ($t in @(
    @("git", "install Git"), @("python", "install Python 3.11+"),
    @("node", "install Node 20+"), @("ollama", "install https://ollama.com"),
    @("docker", "optional: install Docker Desktop"))) {
    Check $t[0] ([bool](Get-Command $t[0] -ErrorAction SilentlyContinue)) $t[1]
}

Check ".env present" (Test-Path .env) "copy .env.example .env"
Check "backend installed" (Test-Path .venv) "run scripts\setup.ps1"

try {
    $tags = Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 3
    $names = $tags.models.name
    Check "Ollama running" $true ""
    Check "model qwen2.5:7b" ($names -contains "qwen2.5:7b") "ollama pull qwen2.5:7b"
    Check "model qwen2.5:3b" ($names -contains "qwen2.5:3b") "ollama pull qwen2.5:3b"
} catch { Check "Ollama running" $false "start Ollama" }

if (Test-Path .venv) {
    & .\.venv\Scripts\python.exe -c "import fastapi, pydantic, sqlalchemy; print('[ OK ] backend dependencies')"
}
