from conftest import SECRET, FakeAuthTokens, auth


def test_start_session_returns_ephemeral_token_and_session(env):
    response = env.client.post("/api/session/start", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "auth_tokens/fake"
    assert body["ws_url"].startswith("wss://")
    assert body["prompt_version"]
    assert body["session_id"]
    assert SECRET not in response.text


def test_start_session_without_key_is_503(env):
    env.key = None
    client = env.configure()
    assert client.post("/api/session/start", headers=auth()).status_code == 503


def test_start_session_is_rate_limited(env):
    env.limit = 2
    client = env.configure()
    codes = [client.post("/api/session/start", headers=auth()).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_resume_handle_is_baked_into_token_and_keeps_the_session(env):
    first = env.client.post("/api/session/start", headers=auth()).json()
    assert FakeAuthTokens.last_config.live_connect_constraints.config.session_resumption.handle is None
    resumed = env.client.post(
        "/api/session/start",
        headers=auth(),
        json={"resume_handle": "handle-123", "session_id": first["session_id"]},
    )
    assert resumed.status_code == 200
    assert resumed.json()["session_id"] == first["session_id"]  # same session doc
    resumption = FakeAuthTokens.last_config.live_connect_constraints.config.session_resumption
    assert resumption.handle == "handle-123"
    assert len(env.store.sessions) == 1


def test_public_config_needs_no_sign_in(env):
    env.configure(firebase_api_key="pub-key", firebase_auth_domain="x.firebaseapp.com")
    body = env.client.get("/api/config").json()
    assert body["firebase"]["apiKey"] == "pub-key"
    assert body["firebase"]["projectId"] == "heb-practice"
