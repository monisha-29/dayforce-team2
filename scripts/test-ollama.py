"""Phase 0 check: the local model must return valid JSON when JSON mode is enforced."""

import json
import os
import sys

import httpx

url = os.getenv("OLLAMA_URL", "http://localhost:11434")
model = os.getenv("LLM_MODEL", "qwen2.5:7b")

resp = httpx.post(
    f"{url}/api/chat",
    json={
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "user", "content": 'Reply with JSON only: {"status": "ok", "model": "<your name>"}'}
        ],
    },
    timeout=120,
)
resp.raise_for_status()
content = resp.json()["message"]["content"]
try:
    print("OK, valid JSON:", json.loads(content))
except json.JSONDecodeError:
    print("FAIL, not JSON:", content)
    sys.exit(1)
