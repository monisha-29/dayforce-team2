#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e "backend[dev]"
[ -f .env ] || cp .env.example .env
echo "Backend ready. Activate with: source .venv/bin/activate"
echo "Next: ollama pull qwen2.5:7b && ollama pull qwen2.5:3b && ./scripts/check-env.sh"
