"""09: session recordings -- uploaded by the browser, played on the caregiver page only."""

from conftest import DAD, TOMER, auth

WEBM = b"\x1aE\xdf\xa3" + b"0" * 2000  # looks like a small webm file


def start(env, token="tok-dad"):
    return env.client.post("/api/session/start", headers=auth(token)).json()


def upload(env, sid, data=WEBM, ctype="audio/webm;codecs=opus", token="tok-dad"):
    return env.client.post(f"/api/session/{sid}/audio", headers={**auth(token), "Content-Type": ctype}, content=data)


def test_record_upload_and_play_on_the_caregiver_page(env):
    body = start(env)
    assert body["voice"]["record_audio"] is True
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["recording"] is True  # start screen notice
    sid = body["session_id"]
    assert upload(env, sid).json() == {"ok": True, "bytes": len(WEBM)}
    row = env.client.get(f"/api/caregiver/{DAD}/sessions", headers=auth("tok-tomer")).json()["sessions"][0]
    assert (row["audio_bytes"], row["audio_type"]) == (len(WEBM), "audio/webm")
    played = env.client.get(f"/api/caregiver/{DAD}/sessions/{sid}/audio", headers=auth("tok-tomer"))
    assert played.status_code == 200 and played.content == WEBM and played.headers["content-type"] == "audio/webm"
    usage = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["audio"]
    assert usage == {"enabled": True, "files": 1, "bytes": len(WEBM)}


def test_only_caregivers_play_and_only_the_owner_uploads(env):
    sid = start(env)["session_id"]
    upload(env, sid)
    assert env.client.get(f"/api/caregiver/{DAD}/sessions/{sid}/audio", headers=auth("tok-dad")).status_code == 403
    assert env.client.get(f"/api/caregiver/{TOMER}/sessions/{sid}/audio", headers=auth("tok-tomer")).status_code == 404
    assert upload(env, sid, token="tok-tomer").status_code == 404  # not Tomer's session


def test_upload_rules(env):
    sid = start(env)["session_id"]
    assert upload(env, sid, ctype="video/mp4").status_code == 415
    assert upload(env, sid, data=b"").status_code == 413
    assert upload(env, sid, data=b"0" * (15 * 1024 * 1024 + 1)).status_code == 413
    assert upload(env, sid, ctype="audio/mp4").status_code == 200  # Safari
    assert upload(env, sid).status_code == 409  # one recording per session


def test_recording_switched_off(env):
    env.client.put(f"/api/caregiver/{DAD}/settings", headers=auth("tok-tomer"),
                   json={"voice": {"record_audio": False}})
    body = start(env)
    assert body["voice"]["record_audio"] is False
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["recording"] is False  # no notice
    assert upload(env, body["session_id"]).status_code == 409
    assert env.client.get("/api/me", headers=auth("tok-tomer")).json()["recording"] is True  # per account



def test_recordings_are_named_by_the_session_start_in_israel_time(env):
    import datetime as dt
    from app.audio_store import recording_name
    started = dt.datetime(2026, 10, 7, 7, 37, tzinfo=dt.timezone.utc)  # 10:37 in Israel (summer time)
    assert recording_name("t9OAQMT1mgTUs3f2NAR0", "audio/webm", started) == "2026-10-07_10-37_t9OAQMT1.webm"
    assert recording_name("abcdefgh123", "audio/mp4", started).endswith("_abcdefgh.m4a")
    sid = start(env)["session_id"]
    env.store.update_session(DAD, sid, {"started_at": started})
    upload(env, sid)
    uri = env.store.get_session(DAD, sid)["audio_uri"]
    assert uri == f"mem://audio/{DAD}/2026-10-07_10-37_{sid[:8]}.webm"
    played = env.client.get(f"/api/caregiver/{DAD}/sessions/{sid}/audio", headers=auth("tok-tomer"))
    assert played.content == WEBM  # found by the stored name
