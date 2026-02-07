"""Application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings."""

    app_name: str = "IATS"
    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/iats"
    redis_url: str = "redis://redis:6379/0"

    llm_provider: Literal["openai", "local"] = "local"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.3-codex"
    local_llm_model: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://ollama:11434"
    local_llm_timeout_seconds: int = 300

    aws_region: str = "us-east-1"
    fixture_mode: bool = True
    slack_webhook_url: str | None = None
    repo_base_path: str = "/repos"
    service_registry_path: str = "app/config/service_registry.yaml"
    allow_raw_storage: bool = False
    triage_window_minutes: int = 10
    max_repo_snippets: int = 5
    celery_task_always_eager: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor."""

    return Settings()


def project_root() -> Path:
    """Return the backend project root."""

    return Path(__file__).resolve().parents[1]
