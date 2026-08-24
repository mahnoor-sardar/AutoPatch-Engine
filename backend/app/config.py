from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


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

    e2b_api_key: str = ""


settings = Settings()