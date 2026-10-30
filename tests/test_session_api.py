from conftest import DAD, SECRET, FakeAuthTokens, auth


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


# ---- a clean goodbye (20): the page's refused end_session calls are counted ------------------

def test_end_saves_goodbye_refusals(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye", "goodbye_refusals": 1})
    assert env.store.get_session(DAD, sid)["goodbye_refusals"] == 1


def test_end_without_goodbye_refusals_saves_nothing_new(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    assert env.client.post(f"/api/session/{sid}/end", headers=auth(),
                           json={"reason": "tutor_goodbye", "goodbye_refusals": 21}).status_code == 422  # capped
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye", "goodbye_refusals": 0})
    assert "goodbye_refusals" not in env.store.get_session(DAD, sid)


# ---- catching his names-game answer live (20) ---------------------------------------------------

def test_start_sends_the_names_games_names(env):
    from plan_helpers import a_plan, practice
    from test_names_game import a_set
    assert env.client.post("/api/session/start", headers=auth()).json()["agenda"]["game_names"] == []  # no game
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He likes the sea."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan(steps=[
        {"kind": "opening"}, {"kind": "names_game"}, {"kind": "practice", **practice("כרמיאל")}]).model_dump(mode="json"))
    env.store.save_check_in_set(DAD, a_set(("עכו", "untreated"), ("חיפה", "treated")))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert sorted(body["agenda"]["game_names"]) == ["חיפה", "עכו"]  # the game's names, not practice's


def test_end_saves_names_live(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye", "names_live": [
        {"target": "חיפה", "live": "חיפה", "matched_by": "caption", "corrected": True}]})
    saved = env.store.get_session(DAD, sid)["names_live"]
    assert saved[0]["corrected"] is True and saved[0]["matched_by"] == "caption" and saved[0]["gem"] == ""


def test_a_turn_keeps_the_pages_match(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    env.client.post(f"/api/session/{sid}/turns", headers=auth(), json={"turns": [
        {"seq": 0, "speaker": "patient", "text": "היפה", "live_text": "חיפה", "t_start_s": 3, "matched_target": "חיפה"}]})
    assert env.store.list_turns(DAD, sid)[0]["matched_target"] == "חיפה"
