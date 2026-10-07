"""09: automatic voice settings per account -- measured from the transcript, in code."""

from app.config import Settings
from app.schemas import VoiceSettings
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from app.voice_tuning import adjust_after_session, decide, measure

PID = "dad@example.com"
SETTINGS = Settings(vad_silence_ms=3000)


def turn(seq, speaker, t, text="", interrupted=False):
    return {"seq": seq, "speaker": speaker, "t_start_s": t, "text": text, "interrupted": interrupted}


def test_measure_tells_cut_offs_from_noise_and_deliberate_interruptions():
    turns = [
        turn(0, "tutor", 0.0, "שלום, איך אתה?", interrupted=True),
        turn(1, "patient", 1.2, "רגע אני עוד לא סיימתי"),            # cut-off: he continues within 2.5 s
        turn(2, "tutor", 5.0, "סליחה, תמשיך", interrupted=True),
        turn(3, "tutor", 7.0, "אז ספר לי"),                            # noise: he said nothing
        turn(4, "tutor", 9.0, "על הטיול", interrupted=True),
        turn(5, "patient", 9.5, "כן"),                                  # noise: one word
        turn(6, "tutor", 12.0, "ומה עוד היה שם?", interrupted=True),
        turn(7, "patient", 18.0, "רגע, אני רוצה לספר משהו אחר"),       # deliberate: long after she started
    ]
    assert measure(turns) == {"cut_offs": 1, "noise_interruptions": 2}
    assert measure(turns, cutoff_reports=2)["cut_offs"] == 3  # tutor-issue "cut_off" reports count too


def test_rules_raise_on_two_events_and_lower_after_three_clean_sessions():
    v = VoiceSettings()
    v2, st, ch = decide(v, {}, {"cut_offs": 2, "noise_interruptions": 3})
    assert (v2.silence_ms, v2.noise_level) == (3500, 1) and len(ch) == 2
    v3, st, ch = decide(v2, st, {"cut_offs": 1, "noise_interruptions": 1})  # 1 event: no change, no clean streak
    assert (v3.silence_ms, v3.noise_level, ch) == (3500, 1, [])
    for _ in range(2):
        v3, st, ch = decide(v3, st, {"cut_offs": 0, "noise_interruptions": 0})
        assert ch == []
    v4, st, ch = decide(v3, st, {"cut_offs": 0, "noise_interruptions": 0})  # the 3rd clean session
    assert (v4.silence_ms, v4.noise_level) == (3000, 0)
    assert "3 sessions without cut-offs" in ch[0]


def test_bounds_fixed_values_and_the_tap_to_talk_suggestion():
    top = VoiceSettings(silence_ms=6000, noise_level=3)
    v, st, ch = decide(top, {}, {"cut_offs": 5, "noise_interruptions": 4})
    assert (v.silence_ms, v.noise_level, ch) == (6000, 3, [])  # already at the maximum
    assert st["suggest_tap_to_talk"] is True
    fixed = VoiceSettings(silence_ms=4000, silence_auto=False, noise_level=1, noise_auto=False)
    v, st, ch = decide(fixed, {}, {"cut_offs": 5, "noise_interruptions": 5})
    assert (v.silence_ms, v.noise_level, ch) == (4000, 1, [])  # the family's fixed values are never touched
    low = VoiceSettings(silence_ms=2500)
    v, st, _ = decide(low, {"silence_clean": 2}, {"cut_offs": 0, "noise_interruptions": 0})
    assert v.silence_ms == 2500  # minimum


def _session(store, lines):
    sid = store.create_session(PID, user_email=PID, model="m", prompt_version="v")
    store.upsert_turns(PID, sid, [TurnIn(seq=i, speaker=sp, text=tx, t_start_s=t, interrupted=it)
                                  for i, (sp, t, tx, it) in enumerate(lines)])
    store.end_session(PID, sid, EndReason.tutor_goodbye)
    return sid


NOISY = [("tutor", 0, "שלום", True), ("tutor", 3, "איך אתה?", True), ("tutor", 6, "ספר לי", False),
         ("patient", 9, "אני בסדר גמור היום", False), ("tutor", 12, "יופי", False)]


def test_after_a_session_the_decision_is_saved_logged_and_made_once(capsys):
    store = InMemorySessionStore()
    sid = _session(store, NOISY)
    decision = adjust_after_session(store, SETTINGS, PID, sid)
    assert decision["measured"] == {"cut_offs": 0, "noise_interruptions": 2}
    assert decision["changes"] == ["noise filter 0 -> 1 (2 noise interruptions)"]
    assert store.get_settings(PID)["noise_level"] == 1
    assert store.get_settings(PID)["auto_state"]["last"]["session_id"] == sid
    assert store.get_session(PID, sid)["voice_decision"] == decision
    assert '"event": "voice_adjust"' in capsys.readouterr().out  # one JSON line for Cloud Logging
    adjust_after_session(store, SETTINGS, PID, sid)  # the sweep runs it again: no second step
    assert store.get_settings(PID)["noise_level"] == 1


def test_short_and_tap_to_talk_sessions_are_skipped():
    store = InMemorySessionStore()
    sid = _session(store, NOISY[:2])
    assert adjust_after_session(store, SETTINGS, PID, sid) == {"skipped": "too short (2 lines)"}
    store.save_settings(PID, {"tap_to_talk": True}, "tomer")
    sid = _session(store, NOISY)
    assert "tap-to-talk" in adjust_after_session(store, SETTINGS, PID, sid)["skipped"]


def test_session_end_runs_it_and_the_next_token_uses_it(env):
    from conftest import DAD, FakeAuthTokens, auth
    from fake_llm import FakeClient, text
    sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
    assert env.store.get_session(DAD, sid)["voice_used"]["noise_level"] == 0
    env.client.post(f"/api/session/{sid}/turns", headers=auth("tok-dad"), json={"turns": [
        {"seq": i, "speaker": sp, "text": tx, "t_start_s": t, "interrupted": it} for i, (sp, t, tx, it) in enumerate(NOISY)]})
    env.llm = FakeClient(*[text("x")] * 10)  # memory update fails harmlessly; tuning still runs
    env.client.post(f"/api/session/{sid}/end", headers=auth("tok-dad"), json={"reason": "end_button"})
    assert env.store.get_session(DAD, sid)["voice_decision"]["changes"] == ["noise filter 0 -> 1 (2 noise interruptions)"]
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).json()["voice"]["noise_level"] == 1
    # caregiver page: current values, the last decision, and a manual change keeps the automatic state
    ov = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["settings"]
    assert ov["noise_level"] == 1 and ov["auto_state"]["last"]["session_id"] == sid
    env.client.put(f"/api/caregiver/{DAD}/settings", headers=auth("tok-tomer"),
                   json={"voice": {**VoiceSettings().model_dump(), "noise_level": 3, "noise_auto": False}})
    saved = env.store.get_settings(DAD)
    assert (saved["noise_level"], saved["noise_auto"], saved["auto_state"]["last"]["session_id"]) == (3, False, sid)
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    vad = FakeAuthTokens.last_config.live_connect_constraints.config.realtime_input_config.automatic_activity_detection
    assert vad.start_of_speech_sensitivity.name == "START_SENSITIVITY_LOW"  # level 3
