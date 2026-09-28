"""Runtime settings, read from environment variables (or a local .env file).

On Cloud Run, GEMINI_API_KEY is mounted from Secret Manager by deploy/deploy.sh.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
