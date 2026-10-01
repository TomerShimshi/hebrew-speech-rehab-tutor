"""Shared fakes: sign-in, Gemini token minting, Firestore (in-memory), patient profile."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import get_token_verifier
from app.config import Settings, get_settings
from app.main import app, get_genai_client, get_profile_loader, get_store, get_token_limiter
from app.patient_profile import PatientProfileLoader
from app.rate_limit import SlidingWindowLimiter
from app.store import InMemorySessionStore

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
def env(tmp_path):
    """Wires the app with fakes; returns (client, store, settings). Tune via env.configure()."""
    state = SimpleNamespace(store=InMemorySessionStore(), limit=5, key=SECRET)

    def configure(**overrides):
        fields = {
            "gemini_api_key": state.key,
            "allowed_emails": f"{DAD},{TOMER}",
            "caregiver_emails": TOMER,
            "patient_profile_uri": None,
            "patient_profile_path": tmp_path / "none.md",
        }
        settings = Settings(**{**fields, **overrides})
        limiter = SlidingWindowLimiter(state.limit, window_s=3600)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_token_limiter] = lambda: limiter
        app.dependency_overrides[get_profile_loader] = lambda: PatientProfileLoader(settings)
        app.dependency_overrides[get_store] = lambda: state.store
        app.dependency_overrides[get_token_verifier] = lambda: fake_verifier
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
