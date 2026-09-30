from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_genai_client, get_profile_loader, get_token_limiter
from app.patient_profile import PatientProfileLoader
from app.rate_limit import SlidingWindowLimiter

SECRET = "real-secret-key"


class FakeAuthTokens:
    last_config = None

    def create(self, *, config):
        FakeAuthTokens.last_config = config
        return SimpleNamespace(name="auth_tokens/fake")


def _client(tmp_path, key=SECRET, limit=5) -> TestClient:
    settings = Settings(gemini_api_key=key, patient_profile_path=tmp_path / "none.md")
    limiter = SlidingWindowLimiter(limit, window_s=3600)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_token_limiter] = lambda: limiter
    app.dependency_overrides[get_profile_loader] = lambda: PatientProfileLoader(settings)
    if key:
        app.dependency_overrides[get_genai_client] = lambda: SimpleNamespace(
            auth_tokens=FakeAuthTokens()
        )
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_start_session_returns_ephemeral_token_not_api_key(tmp_path):
    response = _client(tmp_path).post("/api/session/start")
    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "auth_tokens/fake"
    assert body["ws_url"].startswith("wss://")
    assert body["prompt_version"]
    assert SECRET not in response.text


def test_start_session_without_key_is_503(tmp_path):
    response = _client(tmp_path, key=None).post("/api/session/start")
    assert response.status_code == 503


def test_start_session_is_rate_limited(tmp_path):
    client = _client(tmp_path, limit=2)
    codes = [client.post("/api/session/start").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_resume_handle_is_baked_into_token(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/session/start").status_code == 200  # no body: fresh session
    assert FakeAuthTokens.last_config.live_connect_constraints.config.session_resumption.handle is None
    response = client.post("/api/session/start", json={"resume_handle": "handle-123"})
    assert response.status_code == 200
    resumption = FakeAuthTokens.last_config.live_connect_constraints.config.session_resumption
    assert resumption.handle == "handle-123"
