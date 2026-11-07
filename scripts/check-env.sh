#!/usr/bin/env bash
cd "$(dirname "$0")/.."
chk() { if eval "$2" >/dev/null 2>&1; then echo "[ OK ] $1"; else echo "[FAIL] $1 -> $3"; fi; }

for t in git python3 node ollama docker; do chk "$t" "command -v $t" "install $t"; done
chk ".env present" "test -f .env" "cp .env.example .env"
chk "Ollama running" "curl -sf http://localhost:11434/api/tags" "start Ollama"
chk "model qwen2.5:7b" "ollama list | grep -q qwen2.5:7b" "ollama pull qwen2.5:7b"
chk "model qwen2.5:3b" "ollama list | grep -q qwen2.5:3b" "ollama pull qwen2.5:3b"
[ -d .venv ] && .venv/bin/python -c "import fastapi, pydantic, sqlalchemy; print('[ OK ] backend dependencies')"
