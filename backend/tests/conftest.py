"""Pytest configuration ensuring backend packages are on sys.path."""

import sys
from pathlib import Path

import pytest

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent of a local Ollama: the model call reports 'unavailable'.

    Tests that exercise the model path stub ``proposal_service.query_llm`` themselves.
    """
    from app.services import llm_service, proposal_service

    def unavailable(prompt: str, *args: object, **kwargs: object) -> llm_service.LLMResult:
        return llm_service.LLMResult(
            parsed=None,
            raw="",
            model="test-stub",
            prompt_version="test",
            duration_seconds=0.0,
            error="LLM disabled in tests",
        )

    monkeypatch.setattr(proposal_service, "query_llm", unavailable)
