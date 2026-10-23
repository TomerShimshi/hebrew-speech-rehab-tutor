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


# ---- in parts while the session runs (23.10) --------------------------------------------------------

def part(env, sid, n, data, token="tok-dad"):
    return env.client.post(f"/api/session/{sid}/audio/part?n={n}", headers={**auth(token), "Content-Type": "audio/webm"},
                           content=data)


def test_parts_are_joined_in_order_and_a_retry_is_harmless(env):
    sid = start(env)["session_id"]
    pieces = [b"\x1aE\xdf\xa3head", b"-middle-", b"-tail"]
    for n in (0, 2, 1):  # out of order
        assert part(env, sid, n, pieces[n]).status_code == 200
    assert part(env, sid, 1, b"again").status_code == 200  # a retry: the first copy stays
    done = env.client.post(f"/api/session/{sid}/audio/finish?parts=3", headers=auth()).json()
    assert done["parts"] == 3 and done["bytes"] == len(b"".join(pieces))
    played = env.client.get(f"/api/caregiver/{DAD}/sessions/{sid}/audio", headers=auth("tok-tomer"))
    assert played.content == b"".join(pieces)
    assert part(env, sid, 3, b"late").json() == {"ok": True, "done": True}  # after the join: changes nothing


def test_only_the_owner_and_only_while_recording(env):
    sid = start(env)["session_id"]
    assert part(env, sid, 0, b"x", token="tok-tomer").status_code == 404
    assert part(env, sid, 9999, b"x").status_code == 422
    env.client.put(f"/api/caregiver/{DAD}/settings", headers=auth("tok-tomer"), json={"voice": {"record_audio": False}})
    assert part(env, sid, 0, b"x").status_code == 409


def test_the_sweep_joins_what_arrived_when_the_app_closed_first(env):
    import datetime as dt
    from test_memory_wiring import sweep
    sid = start(env)["session_id"]
    part(env, sid, 0, b"\x1aE\xdf\xa3only-part")
    env.store.end_session(DAD, sid, __import__("app.transcripts", fromlist=["EndReason"]).EndReason.end_button)
    env.store.update_session(DAD, sid, {"ended_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)})
    body = sweep(env).json()
    assert body["recordings_joined"] == [sid]
    assert env.store.get_session(DAD, sid)["audio_parts"] == 1
