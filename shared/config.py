from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CI_OBS_")

    service_name: str = "ci-observability-ingestion"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ci_observability"
    webhook_secret: str = Field(default="development-secret", repr=False)
    repository_allowlist: list[str] = Field(default_factory=list)
    pubsub_topic: str = "ci-observability-ingestion"
    pubsub_push_audience: str | None = None
    github_api_url: str = "https://api.github.com"
    github_app_id: str = ""
    github_app_private_key: str = Field(default="", repr=False)
    initial_fetch_delay_seconds: float = 10.0
    github_fetch_retry_attempts: int = 5
    github_fetch_retry_interval_seconds: float = 10.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
