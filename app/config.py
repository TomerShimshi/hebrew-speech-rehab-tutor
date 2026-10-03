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

    # Second guard behind sign-in: caps Live sessions even for allowed users.
    token_rate_limit_per_hour: int = 30

    # Sign-in (Firebase Auth, Google provider). The emails live in .env / Cloud Run env vars,
    # never in the (public) repo. Comma-separated.
    allowed_emails: str = ""
    caregiver_emails: str = ""
    gcp_project_id: str = "heb-practice"  # Firebase ID tokens are issued for this project
    # Public Firebase web config (designed to be public; access is enforced server-side).
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_app_id: str = ""

    # Debug archive of each session's full tutor prompt (private bucket); empty = off.
    prompt_archive_uri: str = ""  # e.g. gs://heb-practice-private/debug/prompts

    # Hourly memory sweep (Cloud Scheduler -> POST /internal/memory/sweep with an OIDC token).
    sweeper_sa_email: str = ""  # the only caller allowed
    sweep_audience: str = ""  # the service URL the token is minted for
    memory_sweep_batch: int = 3  # sessions per sweep
    memory_end_deadline_s: int = 300  # time budget for memory update + next plan inside /end

    # Agent calls (memory update etc.): primary model + fallbacks for 503 "high demand".
    summary_model: str = "gemini-3.8-flash"
    # (gemini-2.5-flash is listed but returns 404 "no longer available to new users".)
    summary_fallback_models: str = (
        "gemini-3.7-flash,gemini-3.6-flash,gemini-flash-latest,gemini-3.5-flash-lite"
    )
    memory_max_tool_rounds: int = 8

    @property
    def allowed_email_set(self) -> frozenset[str]:
        return _email_set(self.allowed_emails)

    @property
    def caregiver_email_set(self) -> frozenset[str]:
        return _email_set(self.caregiver_emails)

    # Private, de-identified patient profile, never committed (the repo is public).
    # Its home is a private Cloud Storage object; the gitignored local file is only a
    # fallback for development without bucket access.
    patient_profile_uri: str | None = None  # e.g. gs://heb-practice-private/patient_profile.md
    patient_profile_path: Path | None = REPO_ROOT / "prompts" / "patient_profile.local.md"


def _email_set(raw: str) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
