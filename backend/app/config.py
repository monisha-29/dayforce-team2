"""Application configuration settings using Pydantic Settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repository root (overridable for containers)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite:///./timecard.db"
    OLLAMA_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen2.5:7b"
    LLM_FALLBACK_MODEL: str = "qwen2.5:3b"
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT_SECONDS: float = 300.0
    LLM_KEEP_ALIVE: str = "30m"  # keep the model loaded between proposals
    LLM_NUM_PREDICT: int = 700  # a proposal is a small JSON object; cap runaway output
    POLICIES_DIR: str = str(_REPO_ROOT / "policies")
    PROMPTS_DIR: str = str(_REPO_ROOT / "prompts")
    SEED_ON_START: bool = False  # load SEED_FILE when the database has no exceptions
    SEED_FILE: str = str(_REPO_ROOT / "data" / "demo_attendance.json")
    PROMPT_VERSION: str = "v1"
    LOG_LEVEL: str = "INFO"


settings = Settings()
