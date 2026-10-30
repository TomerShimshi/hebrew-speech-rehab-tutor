"""Leaving a conversation out (20.5): it stays visible and marked, but nothing that learns reads it.
Invented sessions, words and names only."""

import datetime as dt

import pytest

from app.agent.next_class import grounding_text, speaking_pace
from app.main import join_left_recordings, live_minutes_today
from app.reminders import practiced_on
from app.transcripts import TurnIn
from app.session_prompt import session_timing
from app.store import ENDED, MEM_DONE, MEM_PENDING, PLAN_PENDING, InMemorySessionStore
from app.audio_store import InMemoryAudioStore
from conftest import DAD, auth

NOW = dt.datetime(2026, 10, 20, 9, 0, tzinfo=dt.timezone.utc)
LEFT_OUT_WORD = "פרפרזה"  # only in the left-out session's transcript


def _session(store, started: dt.datetime, *, words: str, minutes: int = 10, **fields) -> str:
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.upsert_turns(DAD, sid, [
        TurnIn(seq=i, speaker="tutor" if i % 2 == 0 else "patient",
               text="מה שלומך היום?" if i % 2 == 0 else f"{words} מילה נוספת אחת", t_start_s=i * 5)
        for i in range(8)])
    store.end_session(DAD, sid, __import__("app.transcripts", fromlist=["EndReason"]).EndReason.end_button)
    store.update_session(DAD, sid, {"started_at": started, "ended_at": started + dt.timedelta(minutes=minutes),
                                    **fields})
    return sid


@pytest.fixture
def three():
    """old (5 days ago), mid (left out, 1 day ago), new (today) -- all processed."""
    store = InMemorySessionStore()
    old = _session(store, NOW - dt.timedelta(days=5), words="גינה", memory_status=MEM_DONE,
                   class_plan={"title": "old plan"})
    mid = _session(store, NOW - dt.timedelta(days=1), words=LEFT_OUT_WORD, memory_status=MEM_PENDING,
                   class_plan={"title": "mid plan"}, plan_status=PLAN_PENDING, excluded=True)
    new = _session(store, NOW - dt.timedelta(hours=1), words="ים", memory_status=MEM_DONE,
                   class_plan={"title": "new plan"})
    return store, old, mid, new


def test_left_out_sessions_feed_nothing_that_learns(three):
    store, old, mid, new = three
    assert [s["id"] for s in store.list_sessions(DAD)] == [new, old]
    assert LEFT_OUT_WORD not in grounding_text(store, DAD, {}, "", "")
    assert {"title": "mid plan"} not in store.recent_session_plans(DAD)
    assert len(speaking_pace(store, DAD)) == 2
    assert store.pending_memory_sessions(DAD) == [] and not store.claim_for_memory(DAD, mid)
    assert store.pending_plan_sessions(DAD) == []


def test_when_you_last_spoke_skips_a_left_out_newest_session(three):
    store, old, mid, new = three
    store.update_session(DAD, new, {"excluded": True})
    store.update_session(DAD, mid, {"excluded": False})
    assert session_timing(store, DAD, now=NOW).last_he_en == "yesterday"
    store.update_session(DAD, mid, {"excluded": True})
    assert session_timing(store, DAD, now=NOW).last_he_en == "5 days ago"


def test_left_out_sessions_still_count_as_talking(three, env, monkeypatch):
    store, old, mid, new = three
    assert [s["id"] for s in store.list_sessions(DAD, left_out=True)] == [new, mid, old]
    assert practiced_on(store, DAD, (NOW - dt.timedelta(days=1)).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Jerusalem")).date())
    store.update_session(DAD, new, {"excluded": True})  # today's only session, left out: still counted
    monkeypatch.setattr("app.main.now_utc", lambda: NOW)
    assert live_minutes_today(store, env.settings, DAD) == pytest.approx(10)


def test_list_sessions_still_returns_n_counted_ones():  # Review Focus 3
    store = InMemorySessionStore()
    sids = [_session(store, NOW - dt.timedelta(days=d), words="שמש") for d in range(6)]
    store.update_session(DAD, sids[1], {"excluded": True})
    got = [s["id"] for s in store.list_sessions(DAD, 5)]
    assert len(got) == 5 and sids[1] not in got


def test_the_sweep_still_joins_a_left_out_sessions_recording():  # Review Focus 5
    store, audio = InMemorySessionStore(), InMemoryAudioStore()
    sid = _session(store, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), words="שמש",
                   excluded=True, audio_type="audio/webm")
    audio.save_part(DAD, sid, 0, b"\x1aE\xdf\xa3only-part", "audio/webm")
    assert join_left_recordings(store, audio) == [sid]


def test_the_caregiver_list_shows_left_out_sessions_marked(env):
    old = _session(env.store, NOW - dt.timedelta(days=2), words="שמש")
    mid = _session(env.store, NOW - dt.timedelta(days=1), words="ירח", excluded=True)
    rows = env.client.get(f"/api/caregiver/{DAD}/sessions", headers=auth("tok-tomer")).json()["sessions"]
    by_id = {r["id"]: r for r in rows}
    assert by_id[mid]["excluded"] is True and not by_id[old].get("excluded")


def test_progress_shows_left_out_sessions_only_when_asked(env):
    _session(env.store, NOW - dt.timedelta(days=2), words="שמש", mood="good")
    _session(env.store, NOW - dt.timedelta(days=1), words="ירח", mood="good", excluded=True)
    url = f"/api/caregiver/{DAD}/progress"
    counted = env.client.get(url, headers=auth("tok-tomer")).json()
    everything = env.client.get(f"{url}?left_out=1", headers=auth("tok-tomer")).json()
    assert len(counted["points"]) == 1 and len(everything["points"]) == 2


def test_the_names_recheck_skips_a_left_out_session(three):
    from app.names_recheck import recheck_names_game
    store, old, mid, new = three
    store.update_session(DAD, mid, {"memory_status": MEM_DONE, "audio_uri": "mem://x"})
    assert recheck_names_game(store, None, None, None, DAD, mid) == "skipped"
    assert "names_recheck" not in store.get_session(DAD, mid)


# ---- Task 2: leaving out and putting back -------------------------------------------------------

from app.check_in_set import new_set  # noqa: E402
from app.leave_out import LeaveOutBusy, leave_out, put_back  # noqa: E402
from app.schemas import CheckInItem  # noqa: E402


def _results_for(store, sid):
    return [r for i in store.get_check_in_set(DAD)["items"] for r in i.get("results", []) if r["session_id"] == sid]


@pytest.fixture
def processed():
    """Two processed sessions (old, mid); each left a summary, check-in results, needs entries; the
    memory was last updated after mid, the plan built after mid."""
    store = InMemorySessionStore()
    old = _session(store, NOW - dt.timedelta(days=3), words="גינה", memory_status=MEM_DONE,
                   summary="Talked about the garden.", mood="good")
    mid = _session(store, NOW - dt.timedelta(days=1), words="ים", memory_status=MEM_DONE,
                   summary="Talked about the sea.", mood="ok")
    store.save_memory(DAD, mid, {"memory_prompt": "x", "last_session_id": mid, "recent_summaries": [
        {"date": "2026-10-17", "session_id": old, "mood": "good", "summary": "Talked about the garden."},
        {"date": "2026-10-19", "session_id": mid, "mood": "ok", "summary": "Talked about the sea."}]}, None)
    item = lambda t: CheckInItem(target=t, question=f"מה זה {t}?", kind="treated")  # noqa: E731
    cs = new_set([item("חיפה"), item("עכו")], old, NOW.date())
    for i in cs["items"]:
        i["asked"], i["last_asked"] = 2, "2026-10-19"
        i["results"] = [{"date": "2026-10-17", "session_id": old, "result": "uncued", "low_confidence": False},
                        {"date": "2026-10-19", "session_id": mid, "result": "cued", "low_confidence": False,
                         "rechecked": True, "live_result": "failed"}]
    cs["sessions_played"] = 2
    store.save_check_in_set(DAD, cs)
    store.save_needs(DAD, {"areas": {"naming": {"level": "mild", "history": [
        {"date": "2026-10-17", "session": old, "level": "moderate"},
        {"date": "2026-10-19", "session": mid, "level": "mild"}]}},
        "therapist_points": [{"id": f"{old}-0", "text": "a", "session": old},
                             {"id": f"{mid}-1", "text": "b", "session": mid}]})
    store.save_next_plan(DAD, mid, {"title": "next"})
    return store, old, mid


def test_leaving_out_a_processed_session_removes_exactly_its_traces(processed):
    store, old, mid = processed
    out = leave_out(store, DAD, old, "caregiver@test")
    assert out == {"was_processed": True, "is_latest": False, "rebuild": False}
    assert [r["session_id"] for r in store.get_memory(DAD)["recent_summaries"]] == [mid]
    assert _results_for(store, old) == [] and len(_results_for(store, mid)) == 2
    cs = store.get_check_in_set(DAD)
    assert cs["sessions_played"] == 1 and all(i["asked"] == 1 for i in cs["items"])
    needs = store.get_needs(DAD)
    assert [h["session"] for h in needs["areas"]["naming"]["history"]] == [mid]
    assert [p["session"] for p in needs["therapist_points"]] == [mid]
    s = store.get_session(DAD, old)
    assert s["excluded"] is True and s["excluded_by"] == "caregiver@test" and s["memory_status"] == MEM_DONE


def test_the_latest_processed_session_offers_an_exact_restore_and_a_rebuild(processed):  # Review Focus 4
    store, old, mid = processed
    assert leave_out(store, DAD, mid, "c@test") == {"was_processed": True, "is_latest": True, "rebuild": True}
    assert "sea" not in store.get_memory(DAD)["memory_prompt"]  # re-rendered: its summary is gone
    put_back(store, DAD, mid, restored_away=False)
    assert "sea" in store.get_memory(DAD)["memory_prompt"]


def test_leaving_out_a_never_processed_session_marks_its_memory_status(three):
    store, old, mid, new = three
    store.update_session(DAD, mid, {"excluded": False})
    out = leave_out(store, DAD, mid, "c@test")
    assert out["was_processed"] is False
    s = store.get_session(DAD, mid)
    assert s["memory_status"] == "excluded" and s["memory_status_before"] == MEM_PENDING


def test_leaving_out_while_processing_is_refused(processed):  # Review Focus 1
    store, old, mid = processed
    store.update_session(DAD, old, {"memory_status": "processing", "memory_claimed_at": dt.datetime.now(dt.timezone.utc)})
    with pytest.raises(LeaveOutBusy):
        leave_out(store, DAD, old, "c@test")
    assert not store.get_session(DAD, old).get("excluded")


def test_put_back_without_restore_brings_its_traces_back_once(processed):  # Review Focus 2
    store, old, mid = processed
    needs = lambda: {k: v for k, v in store.get_needs(DAD).items() if k != "updated_at"}  # noqa: E731
    before = (store.get_memory(DAD)["recent_summaries"], _results_for(store, old),
              needs(), store.get_check_in_set(DAD)["sessions_played"])
    import copy
    before = copy.deepcopy(before)
    leave_out(store, DAD, old, "c@test")
    leave_out(store, DAD, old, "c@test")  # pressed twice: still exact
    assert put_back(store, DAD, old, restored_away=False) == {"process": False}
    assert put_back(store, DAD, old, restored_away=False) == {"process": False}
    after = (store.get_memory(DAD)["recent_summaries"], _results_for(store, old),
             needs(), store.get_check_in_set(DAD)["sessions_played"])
    assert after == before
    assert not store.get_session(DAD, old).get("excluded")


def test_put_back_after_a_restore_or_never_processed_asks_to_process(processed, three):
    store, old, mid = processed
    leave_out(store, DAD, mid, "c@test")
    assert put_back(store, DAD, mid, restored_away=True) == {"process": True}
    assert store.get_session(DAD, mid)["memory_status"] == MEM_PENDING
    assert store.claim_for_memory(DAD, mid)  # the existing "process now" can run it again
    store3, _, never, _ = three
    store3.update_session(DAD, never, {"excluded": False})
    leave_out(store3, DAD, never, "c@test")
    assert put_back(store3, DAD, never, restored_away=False) == {"process": True}
    assert store3.get_session(DAD, never)["memory_status"] == MEM_PENDING


def test_the_endpoints(env):
    from app.store import MEM_PROCESSING
    sid = _session(env.store, NOW - dt.timedelta(days=1), words="ים", memory_status=MEM_PENDING)
    base = f"/api/caregiver/{DAD}/sessions/{sid}"
    assert env.client.post(f"{base}/leave-out", headers=auth()).status_code == 403  # caregivers only
    r = env.client.post(f"{base}/leave-out", headers=auth("tok-tomer"))
    assert r.status_code == 200 and r.json()["was_processed"] is False
    r = env.client.post(f"{base}/put-back", headers=auth("tok-tomer"), json={"restored_away": False})
    assert r.json() == {"process": True}
    env.store.update_session(DAD, sid, {"memory_status": MEM_PROCESSING,
                                        "memory_claimed_at": dt.datetime.now(dt.timezone.utc)})
    assert env.client.post(f"{base}/leave-out", headers=auth("tok-tomer")).status_code == 409
    assert env.client.post(f"/api/caregiver/{DAD}/sessions/nope/leave-out", headers=auth("tok-tomer")).status_code == 404


def test_restoring_the_memory_to_before_a_left_out_session_marks_it(env, processed):
    store, old, mid = processed
    env.store = store
    client = env.configure()
    leave_out(store, DAD, mid, "c@test")
    store.memory_history[(DAD, mid)] = {"memory_prompt": "before", "recent_summaries": []}
    assert client.post(f"/api/caregiver/{DAD}/memory/restore", headers=auth("tok-tomer"),
                       json={"version": mid}).status_code == 200
    assert store.get_session(DAD, mid)["memory_restored_away"] is True


def test_process_now_refuses_a_left_out_session(env):  # it would build the next lesson after it
    sid = _session(env.store, NOW - dt.timedelta(days=1), words="ים", memory_status=MEM_DONE,
                   plan_status=PLAN_PENDING, excluded=True)
    r = env.client.post(f"/api/caregiver/{DAD}/sessions/{sid}/process", headers=auth("tok-tomer"))
    assert r.status_code == 409


def test_a_session_left_out_while_active_is_processed_when_put_back():
    from app.transcripts import EndReason
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    leave_out(store, DAD, sid, "c@test")
    store.end_session(DAD, sid, EndReason.end_button)  # ends later: memory_status pending
    assert store.pending_memory_sessions(DAD) == []
    assert put_back(store, DAD, sid, restored_away=False) == {"process": True}
