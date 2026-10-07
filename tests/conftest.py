"""Shared fakes: sign-in, Gemini token minting, Firestore (in-memory), patient profile."""

import os
from types import SimpleNamespace

# Settings() also reads the developer's .env (even in module-level test constants, created
# before any fixture runs): tests must never use the real Tavily key. Env vars beat .env.
os.environ["TAVILY_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.auth import get_oidc_verifier, get_token_verifier
from app.config import Settings, get_settings
from app.audio_store import InMemoryAudioStore
from app.main import (
    app, get_audio_store, get_games_reader, get_genai_client, get_profile_loader, get_prompt_archive, get_store,
    get_text_client, get_token_limiter,
)
from app.prompt_archive import PromptArchive
from app.patient_profile import PatientProfileLoader
from app.rate_limit import SlidingWindowLimiter
from app.store import InMemorySessionStore
from fake_llm import FakeClient

@pytest.fixture(autouse=True)
def no_model_cooldowns():
    """app.llm remembers overloaded models for 10 minutes; tests must not leak that."""
    from app import llm
    llm.reset_cooldowns()
    yield
    llm.reset_cooldowns()


DAD = "dad@example.com"
TOMER = "tomer@example.com"
STRANGER = "stranger@example.com"
SECRET = "real-secret-key"

# token string -> claims the fake verifier returns
TOKENS = {
    "tok-dad": {"email": DAD, "email_verified": True, "user_id": "u-dad"},
    "tok-tomer": {"email": TOMER, "email_verified": True, "user_id": "u-tomer"},
    "tok-stranger": {"email": STRANGER, "email_verified": True, "user_id": "u-x"},
    "tok-unverified": {"email": DAD, "email_verified": False, "user_id": "u-dad"},
}


SWEEPER = "memory-sweeper@heb-practice.iam.gserviceaccount.com"
SWEEP_AUDIENCE = "https://tutor.example"
OIDC_TOKENS = {
    "oidc-scheduler": {"email": SWEEPER, "email_verified": True},
    "oidc-other": {"email": "someone@heb-practice.iam.gserviceaccount.com", "email_verified": True},
}


def fake_oidc_verifier(token: str, audience: str) -> dict:
    if token not in OIDC_TOKENS or audience != SWEEP_AUDIENCE:
        raise ValueError("bad token")
    return OIDC_TOKENS[token]


def fake_verifier(token: str, project_id: str) -> dict:
    if token not in TOKENS:
        raise ValueError("bad token")
    return TOKENS[token]


class FakeAuthTokens:
    last_config = None

    def create(self, *, config):
        FakeAuthTokens.last_config = config
        return SimpleNamespace(name="auth_tokens/fake")


def auth(token: str = "tok-dad") -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.llm.time.sleep", lambda s: None)  # no real backoff waits in tests
    """Wires the app with fakes; returns (client, store, settings). Tune via env.configure()."""
    # llm: the text client used by the memory update (scripted per test; empty = must not be called)
    # archived: uri -> text the prompt archive "uploaded"
    # games_reader: a fake Upstash (None = games not configured); tests NEVER reach the real one
    state = SimpleNamespace(store=InMemorySessionStore(), limit=5, key=SECRET, llm=FakeClient(), archived={},
                            games_reader=None, audio=InMemoryAudioStore())

    def configure(**overrides):
        fields = {
            "gemini_api_key": state.key,
            "allowed_emails": f"{DAD},{TOMER}",
            "caregiver_emails": TOMER,
            "patient_profile_uri": None,
            "patient_profile_path": tmp_path / "none.md",
            "sweeper_sa_email": SWEEPER,
            "sweep_audience": SWEEP_AUDIENCE,
            "summary_model": "primary",
            "summary_fallback_models": "fallback",
        }
        settings = Settings(**{**fields, **overrides})
        limiter = SlidingWindowLimiter(state.limit, window_s=3600)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_token_limiter] = lambda: limiter
        app.dependency_overrides[get_profile_loader] = lambda: PatientProfileLoader(settings)
        app.dependency_overrides[get_store] = lambda: state.store
        app.dependency_overrides[get_token_verifier] = lambda: fake_verifier
        app.dependency_overrides[get_oidc_verifier] = lambda: fake_oidc_verifier
        app.dependency_overrides[get_text_client] = lambda: state.llm
        app.dependency_overrides[get_games_reader] = lambda: state.games_reader
        app.dependency_overrides[get_audio_store] = lambda: state.audio  # never the real bucket
        app.dependency_overrides[get_prompt_archive] = lambda: PromptArchive(
            settings.prompt_archive_uri, upload=lambda uri, text: state.archived.__setitem__(uri, text))
        if state.key:
            app.dependency_overrides[get_genai_client] = lambda: SimpleNamespace(
                auth_tokens=FakeAuthTokens()
            )
        else:
            app.dependency_overrides.pop(get_genai_client, None)
        state.settings = settings
        return TestClient(app)

    state.configure = configure
    state.client = configure()
    yield state
    app.dependency_overrides.clear()
