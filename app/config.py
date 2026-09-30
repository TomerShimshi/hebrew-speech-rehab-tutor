"""Runtime settings, read from environment variables (or a local .env file).

On Cloud Run, GEMINI_API_KEY is mounted from Secret Manager and PATIENT_PROFILE_URI
points at the private bucket (deploy/deploy.sh).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = None

    # Gemini Live
    live_model: str = "gemini-3.8-live"
    # Pinned so the voice matches the tutor's female persona in the prompt (she speaks about
    # herself in the feminine). Other female voices to try: "Aoede", "Leda", "Zephyr".
    live_voice: str | None = "Kore"
    live_language: str = "he-IL"
    # Wait this long in silence before deciding he finished speaking (slow speech after stroke).
    vad_silence_ms: int = 3000
    token_ttl_minutes: int = 30

    # Quota guard until Google sign-in lands (sub-plan 03).
    token_rate_limit_per_hour: int = 30

    # Private, de-identified patient profile, never committed (the repo is public).
    # Its home is a private Cloud Storage object; the gitignored local file is only a
    # fallback for development without bucket access.
    patient_profile_uri: str | None = None  # e.g. gs://heb-practice-private/patient_profile.md
    patient_profile_path: Path | None = REPO_ROOT / "prompts" / "patient_profile.local.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()
