"""Application configuration settings using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    PROMPT_VERSION: str = "v1"
    LOG_LEVEL: str = "INFO"


settings = Settings()
