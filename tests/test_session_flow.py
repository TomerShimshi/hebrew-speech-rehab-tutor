"""Start -> save turns -> end, against the in-memory store (no LLM anywhere)."""

from conftest import DAD, auth


def turn(seq, speaker="patient", text="", live_text="", t=0.0, **extra):
    return {"seq": seq, "speaker": speaker, "text": text, "live_text": live_text, "t_start_s": t, **extra}


def start(env, token="tok-dad"):
    return env.client.post("/api/session/start", headers=auth(token)).json()["session_id"]


def test_full_flow_saves_transcript_in_order(env):
    sid = start(env)
    pid = DAD
    r = env.client.post(f"/api/session/{sid}/turns", headers=auth(), json={"turns": [
        turn(0, "tutor", "שלום, איך אתה מרגיש?", t=1.2),
        turn(1, "patient", "", live_text="אני מרגיש", t=5.0),
    ]})
    assert r.status_code == 200 and r.json() == {"saved": 2}
    # the lines grew: her next line, and Gemini's transcript for his line
    env.client.post(f"/api/session/{sid}/turns", headers=auth(), json={"turns": [
        turn(1, "patient", "אני מרגיש טוב", live_text="אני מרגיש טוב", t=5.0),
        turn(2, "tutor", "יופי!", t=9.0, interrupted=True),
    ]})
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye"})
    assert r.status_code == 200

    turns = env.store.list_turns(pid, sid)
    assert [t["seq"] for t in turns] == [0, 1, 2]  # ordered, no duplicates after the re-send
    assert turns[1]["text"] == "אני מרגיש טוב"
    assert turns[1]["live_text"] == "אני מרגיש טוב"
    assert turns[2]["interrupted"] is True
    session = env.store.get_session(pid, sid)
    assert session["status"] == "ended"
    assert session["end_reason"] == "tutor_goodbye"
    assert session["turn_count"] == 3
    assert session["user_email"] == DAD


def test_retrying_a_flush_is_idempotent(env):
    sid = start(env)
    payload = {"turns": [turn(0, "tutor", "שלום"), turn(1, "patient", "היי")]}
    for _ in range(3):
        env.client.post(f"/api/session/{sid}/turns", headers=auth(), json=payload)
    assert len(env.store.list_turns(DAD, sid)) == 2


def test_another_user_cannot_write_to_the_session(env):
    sid = start(env, "tok-dad")
    r = env.client.post(f"/api/session/{sid}/turns", headers=auth("tok-tomer"),
                        json={"turns": [turn(0, "tutor", "x")]})
    assert r.status_code == 404
    assert env.client.post(f"/api/session/{sid}/end", headers=auth("tok-tomer"), json={}).status_code == 404


def test_no_writes_after_end(env):
    sid = start(env)
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "end_button"})
    r = env.client.post(f"/api/session/{sid}/turns", headers=auth(), json={"turns": [turn(0)]})
    assert r.status_code == 409


def test_unknown_session_is_404(env):
    r = env.client.post("/api/session/nope/turns", headers=auth(), json={"turns": [turn(0)]})
    assert r.status_code == 404


def test_closed_tab_session_is_marked_abandoned_on_next_start(env):
    first = start(env)
    env.client.post(f"/api/session/{first}/turns", headers=auth(), json={"turns": [turn(0, "tutor", "שלום")]})
    second = start(env)  # the first was never ended
    pid = DAD
    assert env.store.get_session(pid, first)["end_reason"] == "abandoned"
    assert env.store.list_turns(pid, first)  # its transcript is kept
    assert env.store.get_session(pid, second)["status"] == "active"


def test_turn_validation(env):
    sid = start(env)
    bad = [
        {"turns": [turn(-1)]},
        {"turns": [turn(0, speaker="narrator")]},
        {"turns": [turn(0, text="x" * 5001)]},
        {"turns": [turn(i) for i in range(51)]},
    ]
    for payload in bad:
        assert env.client.post(f"/api/session/{sid}/turns", headers=auth(), json=payload).status_code == 422
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "whatever"})
    assert r.status_code == 422
