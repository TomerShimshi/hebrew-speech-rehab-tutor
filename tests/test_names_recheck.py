"""The names game rechecked from the session's recording, after the session: one model call, only
confident disagreements change the score. Invented names and answers only."""

import datetime as dt

from app import check_in_set, llm
from app.audio_store import InMemoryAudioStore
from app.config import Settings
from app.names_recheck import recheck_names_game
from app.schemas import CheckInItem, NameHeard, NamesHeard
from app.store import InMemorySessionStore
from app.transcripts import EndReason
from conftest import DAD, auth
from fake_llm import FakeClient, server_error, text, tool_calls
from plan_helpers import a_plan

TODAY = dt.date(2026, 10, 20)
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
AUDIO = b"\x1aE\xdf\xa3" + b"0" * 500  # invented bytes that look like a small webm file
GAME = [("שולחן", "על מה אוכלים ארוחת ערב?"), ("מנורה", "מה מדליקים כשחושך בחדר?"),
        ("מטריה", "מה פותחים כשיורד גשם?")]


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


def heard(*names):
    """The model's structured reply: (target, heard, found, confident) per name."""
    parsed = NamesHeard(names=[NameHeard(target=t, heard=h, found=f, confident=c) for t, h, f, c in names])
    return text(parsed.model_dump_json(), parsed=parsed)


def game_plan(game=GAME):
    steps = [{"kind": "opening"}]
    if game:
        steps.append({"kind": "names_game", "items": [
            {"target": t, "kind": "untreated", "elicit": q} for t, q in game]})
    return a_plan(steps=steps).model_dump(mode="json")


def a_session(*, results=(("שולחן", "failed"),), game=GAME, recording=True, memory="done"):
    """An ended session with a names game, its live results (memory update done) and its recording."""
    store, audio = InMemorySessionStore(), InMemoryAudioStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"class_plan": game_plan(game)})
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    probe_results = [{"word": w, "result": r, "kind": "untreated", "low_confidence": False} for w, r in results]
    store.update_session(DAD, sid, {"memory_status": memory, "probe_results": probe_results})
    current = check_in_set.new_set([CheckInItem(target=t, question=q) for t, q in GAME], "sid00000", TODAY)
    check_in_set.record_results(current, probe_results, sid, TODAY)
    store.save_check_in_set(DAD, current)
    if recording:
        uri = audio.save(DAD, sid, AUDIO, "audio/webm")
        store.update_session(DAD, sid, {"audio_uri": uri, "audio_type": "audio/webm"})
    return store, audio, sid


def misheard_flags(store):
    return [f for f in store.list_flags(DAD) if f.get("issue") == "misheard"]


def test_a_confident_disagreement_corrects_the_result_and_flags_misheard():
    store, audio, sid = a_session()
    client = FakeClient(heard(("שולחן", "שולחן", True, True)))
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "changed"
    session = store.get_session(DAD, sid)
    r = session["probe_results"][0]
    assert (r["result"], r["live_result"], r["rechecked"]) == ("uncued", "failed", True)
    assert session["names_recheck"] == "changed"
    assert session["names_recheck_heard"][0]["heard"] == "שולחן"
    assert store.get_check_in_set(DAD)["items"][0]["results"][-1]["result"] == "uncued"
    flags = misheard_flags(store)
    assert len(flags) == 1 and "שולחן" in flags[0]["names"] and flags[0]["kind"] == "tutor_issue"
    # the one call: the recording as an audio part, and an English instruction with the game's questions
    request = client.requests[0]
    parts = request["contents"]
    assert any(getattr(p, "inline_data", None) and p.inline_data.data == AUDIO
               and p.inline_data.mime_type == "audio/webm" for p in parts)
    instruction = next(p for p in parts if isinstance(p, str))
    assert "על מה אוכלים ארוחת ערב?" in instruction and "שולחן" in instruction
    assert request["config"].response_schema is NamesHeard and request["config"].temperature == 0


def test_an_unconfident_disagreement_keeps_the_live_result():  # Review Focus 1
    store, audio, sid = a_session()
    client = FakeClient(heard(("שולחן", "שולחן?", True, False)))
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "agreed"
    r = store.get_session(DAD, sid)["probe_results"][0]
    assert r["result"] == "failed" and "rechecked" not in r
    assert store.get_check_in_set(DAD)["items"][0]["results"][-1]["result"] == "failed"
    assert misheard_flags(store) == []


def test_a_name_with_no_answer_in_the_recording_keeps_its_live_result():  # the recording ended early
    store, audio, sid = a_session(results=(("שולחן", "failed"), ("מנורה", "uncued"), ("מטריה", "failed")))
    client = FakeClient(heard(("שולחן", "שולחן", True, True), ("מנורה", "מנורה", True, True)))
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "changed"
    results = {r["word"]: r for r in store.get_session(DAD, sid)["probe_results"]}
    assert results["מטריה"]["result"] == "failed" and "rechecked" not in results["מטריה"]
    assert "rechecked" not in results["מנורה"]  # agreed: unchanged
    assert results["שולחן"]["result"] == "uncued"


def test_a_lenient_yes_the_recording_disagrees_with_is_corrected_too():
    store, audio, sid = a_session(results=(("מנורה", "uncued"),))
    client = FakeClient(heard(("מנורה", "מגירה", False, True)))
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "changed"
    r = store.get_session(DAD, sid)["probe_results"][0]
    assert (r["result"], r["live_result"]) == ("failed", "uncued")


def test_no_recording_or_no_game_makes_no_model_call():
    client = FakeClient()
    store, audio, sid = a_session(recording=False)
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "not_ready"
    assert "names_recheck" not in store.get_session(DAD, sid)
    store, audio, sid = a_session(memory="processing")
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "not_ready"
    store, audio, sid = a_session(results=(), game=None)
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "skipped"
    assert store.get_session(DAD, sid)["names_recheck"] == "skipped"
    assert len(client.requests) == 0


def test_it_runs_once_even_if_called_three_times():  # Review Focus 2
    store, audio, sid = a_session()
    client = FakeClient(heard(("שולחן", "שולחן", True, True)))
    statuses = [recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) for _ in range(3)]
    assert statuses == ["changed", "not_claimed", "not_claimed"]
    assert len(client.requests) == 1 and len(misheard_flags(store)) == 1


def test_a_stale_claim_can_be_taken_again():
    store, _, sid = a_session()
    assert store.claim_names_recheck(DAD, sid) and not store.claim_names_recheck(DAD, sid)
    store.update_session(DAD, sid, {"names_recheck_claimed_at": dt.datetime.now(dt.timezone.utc)
                                    - dt.timedelta(hours=1)})
    assert store.claim_names_recheck(DAD, sid)


def test_a_model_failure_is_recorded_not_raised():
    store, audio, sid = a_session()
    client = FakeClient(*[server_error() for _ in range(4)])
    assert recheck_names_game(store, client, audio, SETTINGS, DAD, sid, generate_fn=gen) == "failed"
    session = store.get_session(DAD, sid)
    assert session["names_recheck"] == "failed" and session["probe_results"][0]["result"] == "failed"


# ---- wired into /audio/finish, /end and the sweep -----------------------------------------------------

def _start_with_game(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    env.store.update_session(DAD, sid, {"class_plan": game_plan()})
    env.client.post(f"/api/session/{sid}/audio/part?n=0", headers={**auth(), "Content-Type": "audio/webm"},
                    content=AUDIO)
    return sid


def test_audio_finish_runs_the_recheck_when_the_memory_is_done(env):
    env.llm = FakeClient(heard(("שולחן", "שולחן", True, True)))
    env.configure()
    sid = _start_with_game(env)
    env.store.end_session(DAD, sid, EndReason.tutor_goodbye)
    env.store.update_session(DAD, sid, {"memory_status": "done", "probe_results": [
        {"word": "שולחן", "result": "failed", "kind": "untreated", "low_confidence": False}]})
    assert env.client.post(f"/api/session/{sid}/audio/finish?parts=1", headers=auth()).status_code == 200
    assert env.store.get_session(DAD, sid)["names_recheck"] == "changed"


def test_end_runs_the_recheck_when_the_recording_was_joined_first(env):
    from plan_helpers import builder_rounds
    memory_rounds = [tool_calls(("record_word_result", {"word": "שולחן", "result": "failed",
                                                        "asr_confidence": "high", "probe": True}),
                                ("save_session_summary", {"summary": "A short game.", "topics": [], "mood": "good"})),
                     text("done")]
    env.llm = FakeClient(*memory_rounds, *builder_rounds(names=("טבריה", "עכו")),
                         heard(("שולחן", "שולחן", True, True)))
    env.configure()
    env.store.save_profile(DAD, "Man, 70.", "uploaded", "tomer@example.com")
    sid = _start_with_game(env)
    env.client.post(f"/api/session/{sid}/turns", headers=auth(), json={"turns": [
        {"seq": 0, "speaker": "tutor", "text": "על מה אוכלים ארוחת ערב?", "t_start_s": 1},
        {"seq": 1, "speaker": "patient", "text": "שוקן", "live_text": "שוקן", "t_start_s": 4},
        {"seq": 2, "speaker": "tutor", "text": "שולחן! נמשיך.", "t_start_s": 8},
        {"seq": 3, "speaker": "patient", "text": "כן נמשיך", "live_text": "כן נמשיך", "t_start_s": 12}]})
    env.client.post(f"/api/session/{sid}/audio/finish?parts=1", headers=auth())
    assert "names_recheck" not in env.store.get_session(DAD, sid)  # the memory isn't done yet: not_ready
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye"})
    assert r.json()["memory_status"] == "done"
    session = env.store.get_session(DAD, sid)
    assert session["names_recheck"] == "changed" and session["probe_results"][0]["result"] == "uncued"
    assert env.llm.script == []  # every scripted reply used: exactly one recheck call


def test_the_sweep_rechecks_what_both_hooks_missed(env):
    env.llm = FakeClient(heard(("שולחן", "שולחן", True, False)))
    env.configure()
    sid = _start_with_game(env)
    env.client.post(f"/api/session/{sid}/audio/finish?parts=1", headers=auth())
    env.store.end_session(DAD, sid, EndReason.tutor_goodbye)
    env.store.update_session(DAD, sid, {"memory_status": "done", "plan_status": "done", "probe_results": [
        {"word": "שולחן", "result": "failed", "kind": "untreated", "low_confidence": False}]})
    r = env.client.post("/internal/memory/sweep", headers={"Authorization": "Bearer oidc-scheduler"})
    assert r.json()["processed"][f"names:{sid}"] == "agreed"
    assert env.store.get_session(DAD, sid)["names_recheck"] == "agreed"
    r = env.client.post("/internal/memory/sweep", headers={"Authorization": "Bearer oidc-scheduler"})
    assert f"names:{sid}" not in r.json()["processed"]  # once only


def test_joining_a_recording_never_needs_gemini(env):
    """No Gemini key (or Gemini down): the recording is still joined; only the recheck waits."""
    from app.deps import get_optional_text_client, get_text_client
    from app.main import app
    env.configure()
    sid = _start_with_game(env)
    env.store.end_session(DAD, sid, EndReason.tutor_goodbye)
    env.configure(gemini_api_key="")
    for dep in (get_text_client, get_optional_text_client):  # the real dependencies, without a key
        app.dependency_overrides.pop(dep, None)
    assert env.client.post(f"/api/session/{sid}/audio/finish?parts=1", headers=auth()).status_code == 200
    assert env.store.get_session(DAD, sid).get("audio_uri")
