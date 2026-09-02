from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"

    api_key: str
    database_url: str = (
        "postgresql+psycopg://autopatch:autopatch@localhost:5432/autopatch"
    )
    redis_url: str = "redis://localhost:6379/0"

    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_webhook_secret: str

    sentry_webhook_secret: str = ""
    datadog_webhook_secret: str = ""

    e2b_api_key: str = ""
    e2b_template: str = "autopatch-sandbox"

    # Temporary audit stop: after reproduction, skip LLM patch / PR.
    # Default OFF. Production must leave this false.
    autopatch_stop_after_repro: bool = False

    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_api_base: str = ""
    llm_token_budget: int = 50_000
    llm_timeout_seconds: float = 60.0
    embedding_model: str = "text-embedding-3-small"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"


settings = Settings()