from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CI_OBS_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///:memory:"
    webhook_secret: str = Field(default="", repr=False)
    gcp_project_id: str | None = None
    pubsub_topic: str = "ci-observability-ingestion"
    github_api_url: str = "https://api.github.com"
    github_app_id: str = ""
    github_app_private_key: str = Field(default="", repr=False)
    initial_fetch_delay_seconds: float = 10.0
    github_fetch_retry_attempts: int = 5
    github_fetch_retry_interval_seconds: float = 10.0
    max_webhook_body_bytes: int = 262_144
    max_pubsub_body_bytes: int = 65_536

    def model_post_init(self, __context) -> None:
        if self.environment != "development":
            if not self.database_url:
                raise ValueError("CI_OBS_DATABASE_URL must be set outside development")
            if not self.webhook_secret:
                raise ValueError("CI_OBS_WEBHOOK_SECRET must be set outside development")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
