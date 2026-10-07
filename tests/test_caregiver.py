"""Caregiver page API (08): reading every allowlisted account and the caregiver actions."""

from conftest import DAD, TOMER, auth
from test_class_plan import a_plan

from app.transcripts import EndReason, TurnIn


def get(env, path, token="tok-tomer"):
    return env.client.get(path, headers=auth(token))


def seed(env, pid, words=("טבריה",)):
    sid = env.store.create_session(pid, user_email=pid, model="m", prompt_version="v")
    env.store.upsert_turns(pid, sid, [
        TurnIn(seq=0, speaker="tutor", text=f"שלום {pid}", t_start_s=0),
        TurnIn(seq=1, speaker="patient", text="שלום", live_text="שלום!", t_start_s=2),
    ])
    env.store.end_session(pid, sid, EndReason.end_button)
    env.store.update_session(pid, sid, {"summary": f"summary of {pid}", "mood": "good",
                                        "probe_results": [{"word": "עכו", "result": "cued", "kind": "untreated"}],
                                        "class_plan": a_plan().model_dump(mode="json")})
    env.store.save_memory(pid, sid, {"memory_prompt": f"memory of {pid}", "sessions_processed": 1,
                                     "sections": {"interests": [f"interest of {pid}"]},
                                     "word_bank": {w: {"attempts": 1, "failed": 1, "next_due": "2026-10-07"} for w in words}},
                          {"memory_prompt": f"older memory of {pid}", "updated_at": None})
    env.store.save_next_plan(pid, sid, {**a_plan().model_dump(mode="json"), "prompt_version": "0.6",
                                        "research": {"status": "not_needed", "reason": "covered", "question": None,
                                                     "techniques": []}})
    env.store.add_flag(pid, sid, {"kind": "distress", "severity": "high", "evidence": f"flag of {pid}"})
    env.store.add_games_recommendation(pid, sid, {"game_id": "scramble", "kind": "ux", "title": f"rec of {pid}",
                                                  "rationale": "r", "evidence": "e"})
    env.store.save_technique_note(pid, "n1", {"question": f"q of {pid}", "summary": "s", "techniques": []})
    return sid


def test_only_caregivers(env):
    seed(env, DAD)
    for path in ("/api/caregiver/accounts", f"/api/caregiver/{DAD}/overview", f"/api/caregiver/{DAD}/sessions",
                 f"/api/caregiver/{DAD}/memory/history"):
        assert get(env, path, token="tok-dad").status_code == 403
        assert env.client.get(path).status_code == 401


def test_unknown_accounts_are_404(env):
    assert get(env, "/api/caregiver/stranger@example.com/overview").status_code == 404
    assert get(env, "/api/caregiver/stranger@example.com/sessions").status_code == 404


def test_accounts_include_the_caregivers_own_account(env):
    seed(env, TOMER)
    body = get(env, "/api/caregiver/accounts").json()
    assert body["me"] == TOMER
    assert {a["email"] for a in body["accounts"]} == {DAD, TOMER}


def test_overview_shows_only_that_accounts_data(env):
    seed(env, DAD)
    seed(env, TOMER, words=("חיפה", "עכו"))
    for pid, other in ((DAD, TOMER), (TOMER, DAD)):
        ov = get(env, f"/api/caregiver/{pid.upper()}/overview").json()  # case-insensitive
        text = str(ov)
        assert ov["email"] == pid and f"memory of {pid}" in text and other not in text
        assert [f["evidence"] for f in ov["flags"]] == [f"flag of {pid}"]
        assert [r["title"] for r in ov["recommendations"]] == [f"rec of {pid}"]
        assert [n["question"] for n in ov["research_notes"]] == [f"q of {pid}"]
    tomer = get(env, f"/api/caregiver/{TOMER}/overview").json()
    assert [w["word"] for w in tomer["word_bank"]] == ["חיפה", "עכו"]
    assert tomer["memory"]["sections"]["interests"] == [f"interest of {TOMER}"]
    plan = tomer["next_plan"]
    assert "Main goal (name_retrieval)" in plan["rendered"] and plan["research"]["reason"] == "covered"


def test_sessions_and_transcript(env):
    sid = seed(env, DAD)
    seed(env, TOMER)
    sessions = get(env, f"/api/caregiver/{DAD}/sessions").json()["sessions"]
    assert len(sessions) == 1
    s = sessions[0]
    assert s["summary"] == f"summary of {DAD}" and s["mood"] == "good" and s["plan_goal"] == "name_retrieval"
    assert s["probe_results"][0]["result"] == "cued" and "class_plan" not in s
    detail = get(env, f"/api/caregiver/{DAD}/sessions/{sid}").json()
    assert [(t["speaker"], t["text"], t["live_text"]) for t in detail["turns"]] == [
        ("tutor", f"שלום {DAD}", ""), ("patient", "שלום", "שלום!")]
    # a session id from another account is not found under this one
    assert get(env, f"/api/caregiver/{TOMER}/sessions/{sid}").status_code == 404


def test_memory_history(env):
    seed(env, DAD)
    versions = get(env, f"/api/caregiver/{DAD}/memory/history").json()["versions"]
    assert [v["memory_prompt"] for v in versions] == [f"older memory of {DAD}"]


def test_caregiver_page_is_served_with_versioned_assets(env):
    html = env.client.get("/caregiver").text
    assert "caregiver.js?v=" in html and "__ASSET_VERSION__" not in html


def test_rebuild_the_next_plan_now(env):
    from fake_llm import FakeClient, text
    sid = seed(env, DAD)
    seed(env, TOMER)
    tomer_plan = env.store.get_next_plan(TOMER)
    new_plan = a_plan(primary_goal={"type": "discourse", "description": "Rebuilt: tell a story"})
    env.llm = FakeClient(text("{}", parsed=new_plan))
    r = env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-tomer"), json={})
    assert r.status_code == 200 and r.json() == {"plan_status": "done", "built_after_session": sid, "error": None}
    assert "Rebuilt: tell a story" in get(env, f"/api/caregiver/{DAD}/overview").json()["next_plan"]["rendered"]
    assert env.store.get_next_plan(TOMER) == tomer_plan  # other account untouched


def test_rebuild_failure_keeps_the_old_plan(env):
    from fake_llm import FakeClient, text
    seed(env, DAD)
    before = env.store.get_next_plan(DAD)
    env.llm = FakeClient(text("{}", parsed=a_plan(probe=[])))  # invalid: no check-in items
    body = env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-tomer"), json={}).json()
    assert body["plan_status"] == "failed" and "probe items" in body["error"]
    assert env.store.get_next_plan(DAD) == before


def test_rebuild_needs_a_memory_and_a_caregiver(env):
    assert env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-tomer"), json={}).status_code == 409
    assert env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-dad"), json={}).status_code == 403



# ---- step 2: actions -----------------------------------------------------------------------------

def post(env, path, body=None, token="tok-tomer"):
    return env.client.post(path, headers=auth(token), json=body or {})


def memory_with_facts(env, pid=DAD):
    env.store.save_memory(pid, "s1", {
        "memory_prompt": "He lives in Haifa with his wife Rina. He loves the Galilee and trips to Akko.",
        "sections": {"personal_facts": ["Lives in Haifa with his wife Rina", "Has a dog named Bobo"],
                     "interests": ["The Galilee"]},
        "sessions_processed": 3}, None)


def test_resolve_flag_only_in_its_own_account(env):
    seed(env, DAD)
    seed(env, TOMER)
    dad_flag = env.store.list_flags(DAD)[0]["id"]
    assert post(env, f"/api/caregiver/{TOMER}/flags/{dad_flag}/resolve").status_code == 404
    assert post(env, f"/api/caregiver/{DAD}/flags/{dad_flag}/resolve").status_code == 200
    flag = env.store.list_flags(DAD)[0]
    assert flag["status"] == "resolved" and flag["resolved_by"] == TOMER
    assert env.store.list_flags(TOMER)[0]["status"] == "open"
    assert post(env, f"/api/caregiver/{DAD}/flags/{dad_flag}/resolve", token="tok-dad").status_code == 403


def test_recommendation_status(env):
    seed(env, DAD)
    rec_id = env.store.list_recommendations(DAD)[0]["id"]
    assert post(env, f"/api/caregiver/{DAD}/recommendations/{rec_id}", {"status": "accepted"}).status_code == 200
    assert env.store.list_recommendations(DAD)[0]["status"] == "accepted"
    assert post(env, f"/api/caregiver/{DAD}/recommendations/{rec_id}", {"status": "deleted"}).status_code == 422
    assert post(env, f"/api/caregiver/{TOMER}/recommendations/{rec_id}", {"status": "done"}).status_code == 404


def test_github_link_is_prefilled_and_has_no_personal_data(env):
    from urllib.parse import parse_qs, urlsplit
    env.configure(simon_profiles=f"{DAD}=efraim")
    memory_with_facts(env)
    sid = env.store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    env.store.add_games_recommendation(DAD, sid, {
        "game_id": "scramble", "kind": "tune_difficulty", "title": "Harder places for Efraim",
        "rationale": "Rina says efraim solves every places round", "evidence": "0 hints in 5 sessions (dad@example.com)"})
    rec = get(env, f"/api/caregiver/{DAD}/overview").json()["recommendations"][0]
    url = urlsplit(rec["github_url"])
    assert (url.netloc, url.path) == ("github.com", "/TomerShimshi/simon/issues/new")
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    issue = q["title"] + q["body"]
    assert q["title"] == "[scramble] Harder places for [name]"
    assert "0 hints in 5 sessions" in issue and "Task for Claude Code" in issue
    for secret in ("Efraim", "efraim", "Rina", "dad@example.com", "Haifa"):
        assert secret not in issue


def test_notes_are_saved_per_account_and_reach_the_builder(env):
    from fake_llm import FakeClient, text
    seed(env, DAD)
    seed(env, TOMER)
    r = env.client.put(f"/api/caregiver/{DAD}/notes", headers=auth("tok-tomer"), json={"text": "  Focus on family names.  "})
    assert r.status_code == 200
    assert env.store.get_notes(DAD)["text"] == "Focus on family names." and env.store.get_notes(TOMER) is None
    assert get(env, f"/api/caregiver/{DAD}/overview").json()["notes"]["updated_by"] == TOMER
    too_long = env.client.put(f"/api/caregiver/{DAD}/notes", headers=auth("tok-tomer"), json={"text": "x" * 1501})
    assert too_long.status_code == 422
    env.llm = FakeClient(text("{}", parsed=a_plan()))
    post(env, f"/api/caregiver/{DAD}/plan/rebuild")
    context = env.llm.requests[0]["contents"]
    assert "# NOTES FROM THE FAMILY / THERAPIST" in context and "Focus on family names." in context


def test_remove_memory_item_rewrites_the_summary(env):
    from fake_llm import FakeClient, text
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    memory_with_facts(env)
    memory_with_facts(env, TOMER)
    env.llm = FakeClient(text("He lives in Haifa. He loves the Galilee and trips to Akko."))
    r = post(env, f"/api/caregiver/{DAD}/memory/remove-item",
             {"section": "personal_facts", "item": "Lives in Haifa with his wife Rina"})
    assert r.status_code == 200
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["personal_facts"] == ["Has a dog named Bobo"]
    assert memory["memory_prompt"] == "He lives in Haifa. He loves the Galilee and trips to Akko."
    assert "Lives in Haifa with his wife Rina" in env.llm.requests[0]["contents"]  # the model was told what to drop
    versions = env.store.list_memory_history(DAD)
    assert versions[0]["version"].startswith("edit-") and "wife Rina" in versions[0]["memory_prompt"]
    assert "wife Rina" in env.archived[r.json()["backup"]]  # bucket backup first
    assert "wife Rina" in env.store.get_memory(TOMER)["memory_prompt"]  # other account untouched


def test_remove_memory_item_failures_change_nothing(env):
    from fake_llm import FakeClient, server_error, text
    memory_with_facts(env)
    before = env.store.get_memory(DAD)
    path = f"/api/caregiver/{DAD}/memory/remove-item"
    assert post(env, path, {"section": "personal_facts", "item": "not there"}).status_code == 409
    assert post(env, path, {"section": "bogus", "item": "x"}).status_code == 409
    env.llm = FakeClient(text("He."))  # a broken (far too short) rewrite
    assert post(env, path, {"section": "personal_facts", "item": "Has a dog named Bobo"}).status_code == 409
    env.llm = FakeClient(*[server_error() for _ in range(6)])  # models busy
    assert post(env, path, {"section": "personal_facts", "item": "Has a dog named Bobo"}).status_code == 503
    assert env.store.get_memory(DAD) == before


def test_restore_a_version_and_undo_it(env):
    seed(env, DAD)  # current: "memory of DAD"; history: "older memory of DAD"
    old = env.store.list_memory_history(DAD)[0]["version"]
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": old}).status_code == 200
    assert env.store.get_memory(DAD)["memory_prompt"] == f"older memory of {DAD}"
    undo = next(v for v in env.store.list_memory_history(DAD) if v["version"].startswith("restore-"))
    assert undo["memory_prompt"] == f"memory of {DAD}"
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": undo["version"]}).status_code == 200
    assert env.store.get_memory(DAD)["memory_prompt"] == f"memory of {DAD}"
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": "nope"}).status_code == 404


def test_plan_records_which_notes_it_used(env):
    from fake_llm import FakeClient, text
    seed(env, DAD)
    env.client.put(f"/api/caregiver/{DAD}/notes", headers=auth("tok-tomer"), json={"text": "Family names only."})
    env.llm = FakeClient(text("{}", parsed=a_plan(notes_applied="Check-ins use family names, per the notes.")))
    post(env, f"/api/caregiver/{DAD}/plan/rebuild")
    ov = get(env, f"/api/caregiver/{DAD}/overview").json()
    assert ov["next_plan"]["notes_used_at"] == ov["notes"]["updated_at"]
    assert ov["next_plan"]["notes_applied"] == "Check-ins use family names, per the notes."
    assert "per the notes" not in ov["next_plan"]["rendered"]  # the tutor never sees it



# ---- 8.5: word bank cleanup -----------------------------------------------------------------------

def test_remove_a_word_from_the_word_bank(env):
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    seed(env, DAD, words=("טבריה", "רונית"))
    seed(env, TOMER, words=("רונית",))
    r = post(env, f"/api/caregiver/{DAD}/word-bank/remove", {"word": "רונית"})
    assert r.status_code == 200
    assert list(env.store.get_memory(DAD)["word_bank"]) == ["טבריה"]
    assert "רונית" in env.archived[r.json()["backup"]]  # backed up first
    edit = next(v for v in env.store.list_memory_history(DAD) if v["version"].startswith("edit-"))
    assert "רונית" in edit["word_bank"]  # undo via restore
    assert "רונית" in env.store.get_memory(TOMER)["word_bank"]  # other account untouched
    assert post(env, f"/api/caregiver/{DAD}/word-bank/remove", {"word": "רונית"}).status_code == 409
    assert post(env, f"/api/caregiver/{DAD}/word-bank/remove", {"word": "טבריה"}, token="tok-dad").status_code == 403



# ---- 8.5: prompt views ---------------------------------------------------------------------------

def test_each_session_stores_its_prompt_and_the_page_shows_it(env):
    from conftest import FakeAuthTokens
    sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
    given = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    body = get(env, f"/api/caregiver/{DAD}/sessions/{sid}/prompt").json()
    assert body["text"] == given and body["prompt_version"]
    assert get(env, f"/api/caregiver/{TOMER}/sessions/{sid}/prompt").status_code == 404  # not Tomer's session
    old = env.store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")  # from before 8.5
    assert get(env, f"/api/caregiver/{DAD}/sessions/{old}/prompt").json()["text"] is None


def test_next_prompt_is_exactly_what_the_session_start_uses(env):
    from conftest import FakeAuthTokens
    seed(env, DAD)
    shown = get(env, f"/api/caregiver/{DAD}/next-prompt").json()["text"]
    assert f"memory of {DAD}" in shown and "TODAY'S PLAN" in shown
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    given = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    assert shown == given
    assert get(env, f"/api/caregiver/{DAD}/next-prompt", token="tok-dad").status_code == 403



# ---- 09: model visibility -----------------------------------------------------------------------

def test_models_are_shown_per_session_and_for_the_next_plan(env):
    sid = seed(env, DAD)
    env.store.update_session(DAD, sid, {"memory_model": "gemini-3.8-flash", "plan_model": "gemini-3.5-flash-lite"})
    row = get(env, f"/api/caregiver/{DAD}/sessions").json()["sessions"][0]
    assert (row["memory_model"], row["plan_model"]) == ("gemini-3.8-flash", "gemini-3.5-flash-lite")
    assert get(env, f"/api/caregiver/{DAD}/overview").json()["next_plan"]["model"] == "gemini-3.5-flash-lite"



# ---- 09 (4.5): translating the therapist export -----------------------------------------------------

def test_export_translation(env):
    from fake_llm import FakeClient, text
    from app.caregiver_api import Translations
    seed(env, DAD)
    he = Translations(translations=["הוא דיבר על הכנרת.", "שלף את טבריה לבד"])
    env.llm = FakeClient(text(he.model_dump_json(), parsed=he))
    body = post(env, f"/api/caregiver/{DAD}/export/translate",
                {"texts": ["He talked about the Galilee.", "Retrieved טבריה on his own"]}).json()
    assert body["translations"] == he.translations
    sent = env.llm.requests[0]
    assert "Retrieved טבריה on his own" in sent["contents"]  # Hebrew words go through untouched
    assert "Keep every Hebrew word" in sent["config"].system_instruction


def test_export_translation_failures(env):
    from fake_llm import FakeClient, client_error, text
    from app.caregiver_api import Translations
    seed(env, DAD)
    path = f"/api/caregiver/{DAD}/export/translate"
    short = Translations(translations=["רק אחד"])
    env.llm = FakeClient(text(short.model_dump_json(), parsed=short))
    assert post(env, path, {"texts": ["one", "two"]}).status_code == 502  # incomplete -> page prints English
    env.llm = FakeClient(client_error(400))
    assert post(env, path, {"texts": ["one"]}).status_code == 503
    assert post(env, path, {"texts": ["x"] * 401}).status_code == 413
    assert post(env, path, {"texts": ["one"]}, token="tok-dad").status_code == 403



# ---- 09: progress graphs (the numbers; drawing is the browser's job) ------------------------------

def test_progress_numbers():
    import datetime as dt
    from app.caregiver_api import progress_series

    def session(day, results, mood="ok"):
        return {"started_at": dt.datetime(2026, 10, day), "mood": mood,
                "probe_results": [{"word": w, "kind": k, "result": r} for w, k, r in results]}

    sessions = [  # newest first, as stored
        session(12, [("a", "treated", "uncued"), ("b", "treated", "uncued"), ("c", "untreated", "failed")], "good"),
        session(11, [("a", "treated", "cued"), ("b", "treated", "uncued"), ("c", "untreated", "uncued")]),
        session(10, [], "low"),  # no check-ins, but a mood
        {"started_at": dt.datetime(2026, 10, 9)},  # nothing to show: skipped
    ] + [session(d, [("x", "treated", "failed"), ("y", "untreated", "failed")]) for d in (8, 7, 6, 5, 4)]
    data = progress_series(sessions, {"a": {"last_result": "uncued"}, "b": {"last_result": "cued"},
                                      "c": {"last_result": "failed"}, "d": {"last_result": "uncued"}})
    pts = data["points"]
    assert [pt["date"].day for pt in pts] == [4, 5, 6, 7, 8, 10, 11, 12]  # oldest first, empty one skipped
    assert (pts[-1]["treated"], pts[-1]["untreated"], pts[-1]["mood"]) == (100, 0, 3)
    assert (pts[-2]["treated"], pts[-2]["untreated"]) == (50, 100)
    assert pts[-3] == {"date": dt.datetime(2026, 10, 10), "treated": None, "untreated": None, "items": 0, "mood": 1}
    # last 5 sessions with check-ins (12, 11, 8, 7, 6) vs the ones before (5, 4)
    assert data["compare"]["recent"] == {"treated": 30, "untreated": 20, "sessions": 5}
    assert data["compare"]["before"] == {"treated": 0, "untreated": 0, "sessions": 2}
    assert data["words"] == {"total": 4, "own": 2, "hint": 1, "not_yet": 1}


def test_progress_route_is_per_account_and_caregiver_only(env):
    seed(env, DAD)
    data = get(env, f"/api/caregiver/{DAD}/progress").json()
    assert data["points"][0]["untreated"] == 0 and data["words"]["total"] == 1
    assert get(env, f"/api/caregiver/{TOMER}/progress").json()["points"] == []
    assert get(env, f"/api/caregiver/{DAD}/progress", token="tok-dad").status_code == 403



# ---- 09: per-account voice settings -------------------------------------------------------------------

def _vad():
    from conftest import FakeAuthTokens
    return FakeAuthTokens.last_config.live_connect_constraints.config.realtime_input_config.automatic_activity_detection


def test_voice_settings_reach_the_session_token(env):
    put = lambda body, token="tok-tomer": env.client.put(f"/api/caregiver/{DAD}/settings", headers=auth(token), json=body)  # noqa: E731
    # defaults
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).json()["voice"] == {"tap_to_talk": False, "noise_level": 0}
    assert _vad().silence_duration_ms == 3000 and not _vad().disabled
    # a longer silence for Dad
    assert put({"voice": {"silence_ms": 5500, "tap_to_talk": False}}).status_code == 200
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert _vad().silence_duration_ms == 5500
    assert get(env, f"/api/caregiver/{DAD}/overview").json()["settings"]["silence_ms"] == 5500
    # tap-to-talk: automatic detection off, and the page is told to show the button
    put({"voice": {"silence_ms": 5500, "tap_to_talk": True}})
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).json()["voice"] == {"tap_to_talk": True, "noise_level": 0}
    assert _vad().disabled is True
    # per account: Tomer's sessions keep the defaults
    env.client.post("/api/session/start", headers=auth("tok-tomer"))
    assert _vad().silence_duration_ms == 3000 and not _vad().disabled
    # validated, and caregivers only
    assert put({"voice": {"silence_ms": 500, "tap_to_talk": False}}).status_code == 422
    assert put({"voice": {"silence_ms": 9000, "tap_to_talk": False}}).status_code == 422
    assert put({"voice": {"silence_ms": 4000, "tap_to_talk": False}}, token="tok-dad").status_code == 403



# ---- process a session now (instead of waiting for the hourly sweep) ------------------------------

def test_process_an_unprocessed_session_now(env):
    from fake_llm import FakeClient, server_error, text
    from test_memory_wiring import consolidated, plan_reply, talk
    sid = talk(env)
    env.llm = FakeClient(*[server_error() for _ in range(12)])  # models down at the end of the session
    env.client.post(f"/api/session/{sid}/end", headers=auth("tok-dad"), json={"reason": "end_button"})
    assert env.store.get_session(DAD, sid)["memory_status"] == "failed"
    env.llm = FakeClient(text("done"), consolidated("He talked about his grandchildren."), plan_reply())
    body = post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()
    assert (body["memory_status"], body["plan_status"]) == ("done", "done")
    assert env.store.get_memory(DAD)["memory_prompt"] == "He talked about his grandchildren."
    assert env.store.get_session(DAD, sid)["voice_decision"] is not None
    # done now: pressing it again changes nothing and calls no model
    env.llm = FakeClient()
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()["memory_status"] == "done"


def test_process_refuses_a_session_that_may_still_be_running_but_ends_a_stuck_one(env):
    import datetime as dt
    from fake_llm import FakeClient, text
    from test_memory_wiring import consolidated, plan_reply, talk
    sid = talk(env)
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").status_code == 409  # started just now
    env.store.update_session(DAD, sid, {"started_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=45)})
    env.llm = FakeClient(text("done"), consolidated("m"), plan_reply())
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()["memory_status"] == "done"
    assert env.store.get_session(DAD, sid)["end_reason"] == "abandoned"
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process", token="tok-dad").status_code == 403
    assert post(env, f"/api/caregiver/{TOMER}/sessions/{sid}/process").status_code == 404



def test_process_picks_up_where_it_stopped_memory_done_plan_failed(env):
    from fake_llm import FakeClient, text
    from test_memory_wiring import consolidated, plan_reply, talk
    sid = talk(env)
    env.llm = FakeClient(text("done"), consolidated("Memory from the session."), text("{}"))  # plan reply invalid
    env.client.post(f"/api/session/{sid}/end", headers=auth("tok-dad"), json={"reason": "end_button"})
    session = env.store.get_session(DAD, sid)
    assert (session["memory_status"], session["plan_status"]) == ("done", "failed")
    memory_before = env.store.get_memory(DAD)
    env.llm = FakeClient(plan_reply())  # ONE reply: a memory-update call would run out of script
    body = post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()
    assert (body["memory_status"], body["plan_status"]) == ("done", "done")
    assert len(env.llm.requests) == 1  # only the plan builder ran
    assert env.store.get_memory(DAD) == memory_before  # the memory wasn't updated twice
