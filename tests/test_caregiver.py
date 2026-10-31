"""Caregiver page API (08): reading every allowlisted account and the caregiver actions."""

from app.memory_text import render_memory
from conftest import DAD, TOMER, auth
from plan_helpers import a_plan

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


def test_the_session_row_shows_goodbye_refusals(env):
    sid = seed(env, DAD)
    env.store.update_session(DAD, sid, {"goodbye_refusals": 1})
    row = get(env, f"/api/caregiver/{DAD}/sessions").json()["sessions"][0]
    assert row["goodbye_refusals"] == 1


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
    from plan_helpers import builder_rounds
    env.llm = FakeClient(*builder_rounds(goal="discourse"))
    r = env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-tomer"), json={})
    assert r.status_code == 200 and r.json() == {"plan_status": "done", "built_after_session": sid, "error": None}
    assert "Main goal (discourse)" in get(env, f"/api/caregiver/{DAD}/overview").json()["next_plan"]["rendered"]
    assert env.store.get_next_plan(TOMER) == tomer_plan  # other account untouched


def test_rebuild_failure_keeps_the_old_plan(env):
    from fake_llm import FakeClient, text
    seed(env, DAD)
    before = env.store.get_next_plan(DAD)
    # the builder never finishes a usable plan (e.g. the models give up)
    env.llm = FakeClient(text("I can't plan today."))
    body = env.client.post(f"/api/caregiver/{DAD}/plan/rebuild", headers=auth("tok-tomer"), json={}).json()
    assert body["plan_status"] == "failed" and "didn't finish a usable plan" in body["error"]
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
    from plan_helpers import builder_rounds, plan_context
    env.llm = FakeClient(*builder_rounds())
    post(env, f"/api/caregiver/{DAD}/plan/rebuild")
    context = plan_context(env.llm)
    assert "# NOTES FROM THE FAMILY / THERAPIST" in context and "Focus on family names." in context


def test_remove_memory_item_re_renders_the_text_without_a_model(env):
    from fake_llm import FakeClient
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    memory_with_facts(env)
    memory_with_facts(env, TOMER)
    env.llm = FakeClient()  # no model call (16)
    r = post(env, f"/api/caregiver/{DAD}/memory/remove-item",
             {"section": "personal_facts", "item": "Lives in Haifa with his wife Rina"})
    assert r.status_code == 200 and env.llm.requests == []
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["personal_facts"] == ["Has a dog named Bobo"]
    assert "wife Rina" not in memory["memory_prompt"] and "- Has a dog named Bobo" in memory["memory_prompt"]
    versions = env.store.list_memory_history(DAD)
    assert versions[0]["version"].startswith("edit-") and "wife Rina" in versions[0]["memory_prompt"]
    assert "wife Rina" in env.archived[r.json()["backup"]]  # bucket backup first
    assert "wife Rina" in env.store.get_memory(TOMER)["memory_prompt"]  # other account untouched


def test_remove_memory_item_failures_change_nothing(env):
    memory_with_facts(env)
    before = env.store.get_memory(DAD)
    path = f"/api/caregiver/{DAD}/memory/remove-item"
    assert post(env, path, {"section": "personal_facts", "item": "not there"}).status_code == 409
    assert post(env, path, {"section": "bogus", "item": "x"}).status_code == 409
    assert env.store.get_memory(DAD) == before


def test_restore_a_version_and_undo_it(env):
    seed(env, DAD)  # current: "memory of DAD"; history: "older memory of DAD"
    old = env.store.list_memory_history(DAD)[0]["version"]
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": old}).status_code == 200
    restored = env.store.get_memory(DAD)
    assert restored["memory_prompt"] == render_memory(restored)  # its text, rendered from its sections (16)
    undo = next(v for v in env.store.list_memory_history(DAD) if v["version"].startswith("restore-"))
    assert undo["memory_prompt"] == f"memory of {DAD}"
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": undo["version"]}).status_code == 200
    assert f"interest of {DAD}" in env.store.get_memory(DAD)["memory_prompt"]
    assert post(env, f"/api/caregiver/{DAD}/memory/restore", {"version": "nope"}).status_code == 404


def test_plan_records_which_notes_it_used(env):
    from fake_llm import FakeClient, text
    seed(env, DAD)
    env.client.put(f"/api/caregiver/{DAD}/notes", headers=auth("tok-tomer"), json={"text": "Family names only."})
    from plan_helpers import build_calls
    from fake_llm import tool_calls
    calls = build_calls(finish=False) + [("finish", {"notes_applied": "Check-ins use family names, per the notes."})]
    env.llm = FakeClient(tool_calls(*calls), text("done"))
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
    assert pts[-3] == {"date": dt.datetime(2026, 10, 10), "treated": None, "untreated": None, "items": 0, "mood": 1,
                       "self_found": 0, "not_found": 0, "sequencing": None, "sequencing_task": None, "summarizing": None, "story": None, "his_view": None, "avg_words": None,
                       "repetition": None, "understanding": None, "clarity": None}
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
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).json()["voice"] == {"tap_to_talk": False, "noise_level": 0, "record_audio": True}
    assert _vad().silence_duration_ms == 3000 and not _vad().disabled
    # a longer silence for Dad
    assert put({"voice": {"silence_ms": 5500, "tap_to_talk": False}}).status_code == 200
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert _vad().silence_duration_ms == 5500
    assert get(env, f"/api/caregiver/{DAD}/overview").json()["settings"]["silence_ms"] == 5500
    # tap-to-talk: automatic detection off, and the page is told to show the button
    put({"voice": {"silence_ms": 5500, "tap_to_talk": True}})
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).json()["voice"] == {"tap_to_talk": True, "noise_level": 0, "record_audio": True}
    assert _vad().disabled is True
    # per account: Tomer's sessions keep the defaults
    env.client.post("/api/session/start", headers=auth("tok-tomer"))
    assert _vad().silence_duration_ms == 3000 and not _vad().disabled
    # validated, and caregivers only
    # 0 = no silence length: Gemini decides when he's done
    assert put({"voice": {"silence_ms": 0, "silence_auto": False, "tap_to_talk": False}}).status_code == 200
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert _vad().silence_duration_ms is None and not _vad().disabled
    assert _vad().end_of_speech_sensitivity is not None
    assert put({"voice": {"silence_ms": -1, "tap_to_talk": False}}).status_code == 422
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
    env.llm = FakeClient(consolidated("He talked about his grandchildren."), text("done"), *plan_reply())
    body = post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()
    assert (body["memory_status"], body["plan_status"]) == ("done", "done")
    assert "He talked about his grandchildren." in env.store.get_memory(DAD)["memory_prompt"]
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
    env.llm = FakeClient(consolidated("m"), text("done"), *plan_reply())
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()["memory_status"] == "done"
    assert env.store.get_session(DAD, sid)["end_reason"] == "abandoned"
    assert post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process", token="tok-dad").status_code == 403
    assert post(env, f"/api/caregiver/{TOMER}/sessions/{sid}/process").status_code == 404



def test_process_picks_up_where_it_stopped_memory_done_plan_failed(env):
    from fake_llm import FakeClient, text
    from test_memory_wiring import consolidated, plan_reply, talk
    env.store.save_profile(DAD, "Man, 70.", "uploaded", TOMER)  # the classic intro, then a built plan
    sid = talk(env)
    env.llm = FakeClient(consolidated("Memory from the session."), text("done"), text("{}"))  # plan reply invalid
    env.client.post(f"/api/session/{sid}/end", headers=auth("tok-dad"), json={"reason": "end_button"})
    session = env.store.get_session(DAD, sid)
    assert (session["memory_status"], session["plan_status"]) == ("done", "failed")
    memory_before = env.store.get_memory(DAD)
    env.llm = FakeClient(*plan_reply())  # only the builder's replies: a memory-update call would run out of script
    body = post(env, f"/api/caregiver/{DAD}/sessions/{sid}/process").json()
    assert (body["memory_status"], body["plan_status"]) == ("done", "done")
    assert len(env.llm.requests) == 2  # only the plan builder ran (its two rounds)
    assert env.store.get_memory(DAD) == memory_before  # the memory wasn't updated twice


def test_names_found_on_his_own_are_their_own_progress_series():
    import datetime as dt
    from app.caregiver_api import progress_series
    data = progress_series([{"started_at": dt.datetime(2026, 10, 12), "own_names": [
        {"word": "עין גדי", "result": "self_found"}, {"word": "עין גב", "result": "not_found"},
        {"word": "בניאס", "result": "self_found"}]}], {"עין גדי": {"last_result": "self_found"}})
    assert (data["points"][0]["self_found"], data["points"][0]["not_found"], data["points"][0]["items"]) == (2, 1, 0)
    assert data["words"]["own"] == 1


def test_names_game_set_on_the_page_new_set_and_remove_a_name(env):
    from app.check_in_set import new_set
    from app.schemas import CheckInItem
    import datetime as dt
    env.store.save_check_in_set(DAD, new_set([CheckInItem(target="עכו", question="q"),
                                              CheckInItem(target="צפת", question="q")], "s0", dt.date(2026, 10, 10)))
    ov = get(env, f"/api/caregiver/{DAD}/overview").json()
    assert [i["target"] for i in ov["check_in_set"]["items"]] == ["עכו", "צפת"]
    post = lambda path, body=None, token="tok-tomer": env.client.post(  # noqa: E731
        f"/api/caregiver/{DAD}/{path}", headers=auth(token), json=body or {})
    assert post("check-in/remove-item", {"target": "עכו"}, token="tok-dad").status_code == 403
    assert post("check-in/remove-item", {"target": "עכו"}).json()["items"] == 1
    assert post("check-in/remove-item", {"target": "עכו"}).status_code == 404
    assert post("check-in/new").json()["retired"] is True
    ov = get(env, f"/api/caregiver/{DAD}/overview").json()
    assert ov["check_in_set"] is None and ov["check_in_history"][0]["items"][0]["target"] == "צפת"


# ---- editing the memory (21): edit / add items, edit / remove summaries ----------------------------

def with_summaries(env, pid=DAD):
    memory_with_facts(env, pid)
    m = env.store.get_memory(pid)
    m.pop("updated_at", None)
    m["recent_summaries"] = [{"date": "2026-10-01", "session_id": "a", "mood": "good", "summary": "Talked about trips."},
                             {"date": "2026-10-02", "session_id": "b", "mood": "ok", "summary": "Talked about tea."}]
    env.store.save_memory(pid, "s2", m, None)


def test_edit_item_replaces_in_place_and_rerenders(env):
    from fake_llm import FakeClient
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    memory_with_facts(env)
    env.llm = FakeClient()  # no model call
    r = post(env, f"/api/caregiver/{DAD}/memory/edit-item",
             {"section": "personal_facts", "old": "Has a dog named Bobo", "new": "  Has two dogs  "})
    assert r.status_code == 200 and env.llm.requests == []
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["personal_facts"] == ["Lives in Haifa with his wife Rina", "Has two dogs"]
    assert "Has two dogs" in memory["memory_prompt"] and "Bobo" not in memory["memory_prompt"]
    assert "Has a dog named Bobo" in env.store.list_memory_history(DAD)[0]["sections"]["personal_facts"]  # restorable
    assert r.json()["backup"] in env.archived  # bucket backup first


def test_edit_of_a_changed_item_is_refused_and_changes_nothing(env):  # Review Focus 1
    memory_with_facts(env)
    before = env.store.get_memory(DAD)
    path = f"/api/caregiver/{DAD}/memory/edit-item"
    assert post(env, path, {"section": "personal_facts", "old": "not there", "new": "x"}).status_code == 409
    assert post(env, path, {"section": "bogus", "old": "x", "new": "y"}).status_code == 409
    assert env.store.get_memory(DAD) == before


def test_empty_or_too_long_edits_are_refused(env):  # Review Focus 5
    memory_with_facts(env)
    before = env.store.get_memory(DAD)
    path = f"/api/caregiver/{DAD}/memory/edit-item"
    assert post(env, path, {"section": "personal_facts", "old": "Has a dog named Bobo", "new": "   "}).status_code == 422
    assert post(env, path, {"section": "personal_facts", "old": "Has a dog named Bobo", "new": "x" * 201}).status_code == 422
    assert post(env, f"/api/caregiver/{DAD}/memory/add-item", {"section": "interests", "text": " "}).status_code == 422
    assert env.store.get_memory(DAD) == before


def test_add_item_is_newest_and_a_full_section_is_refused(env):
    from app.schemas import MAX_ITEMS_PER_SECTION
    memory_with_facts(env)
    path = f"/api/caregiver/{DAD}/memory/add-item"
    assert post(env, path, {"section": "interests", "text": "Cooking on weekends"}).status_code == 200
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["interests"] == ["The Galilee", "Cooking on weekends"]
    assert memory["memory_prompt"].index("Cooking on weekends") < memory["memory_prompt"].index("The Galilee")
    for i in range(MAX_ITEMS_PER_SECTION - 2):
        post(env, path, {"section": "interests", "text": f"interest {i}"})
    assert post(env, path, {"section": "interests", "text": "one too many"}).status_code == 422
    assert post(env, path, {"section": "interests", "text": "Cooking on weekends"}).status_code in (409, 422)


def test_editing_the_newest_summary_changes_the_last_time_line(env):  # Review Focus 4
    with_summaries(env)
    r = post(env, f"/api/caregiver/{DAD}/memory/edit-summary",
             {"date": "2026-10-02", "old": "Talked about tea.", "new": "Talked about coffee."})
    assert r.status_code == 200
    memory = env.store.get_memory(DAD)
    assert memory["recent_summaries"][-1]["summary"] == "Talked about coffee."
    assert "Talked about coffee." in memory["memory_prompt"] and "tea" not in memory["memory_prompt"]


def test_remove_summary_and_its_failures(env):
    with_summaries(env)
    path = f"/api/caregiver/{DAD}/memory/remove-summary"
    assert post(env, path, {"date": "2026-10-02", "old": "not it"}).status_code == 409
    assert post(env, path, {"date": "2026-10-02", "old": "Talked about tea."}).status_code == 200
    memory = env.store.get_memory(DAD)
    assert [r["date"] for r in memory["recent_summaries"]] == ["2026-10-01"]
    assert "Talked about trips." in memory["memory_prompt"]
    assert post(env, f"/api/caregiver/{DAD}/memory/edit-summary",
                {"date": "2026-10-01", "old": "Talked about trips.", "new": ""}).status_code == 422


def rendered_memory(env, pid=DAD):
    """with_summaries, with her text rendered from the sections as the app renders it."""
    from app.memory_text import render_memory
    with_summaries(env, pid)
    m = env.store.get_memory(pid)
    m.pop("updated_at", None)
    m["memory_prompt"] = render_memory(m)
    env.store.save_memory(pid, "s3", m, None)


def test_editing_her_whole_text_updates_the_sections_and_the_last_summary(env):
    rendered_memory(env)
    text = env.store.get_memory(DAD)["memory_prompt"]
    edited = (text.replace("Has a dog named Bobo", "Has a cat named Mitzi").replace("Talked about tea.", "Talked about coffee.")
              .replace("His interests:\n- The Galilee", "His interests:\n- Football\n- The Galilee"))
    r = post(env, f"/api/caregiver/{DAD}/memory/edit-text", {"old": text, "text": edited})
    assert r.status_code == 200, r.text
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["personal_facts"] == ["Lives in Haifa with his wife Rina", "Has a cat named Mitzi"]
    assert memory["sections"]["interests"] == ["The Galilee", "Football"]  # the top line is the newest
    assert memory["recent_summaries"][-1]["summary"] == "Talked about coffee."
    assert memory["memory_prompt"] == edited.strip()  # it stays as written: the next render gives the same text
    assert env.store.list_memory_history(DAD)[0]["memory_prompt"] == text  # restorable


def test_her_text_without_a_heading_empties_that_section(env):
    rendered_memory(env)
    text = env.store.get_memory(DAD)["memory_prompt"]
    edited = text.replace("His interests:\n- The Galilee", "").replace("Last time (2026-10-02):\nTalked about tea.", "")
    assert post(env, f"/api/caregiver/{DAD}/memory/edit-text", {"old": text, "text": edited}).status_code == 200
    memory = env.store.get_memory(DAD)
    assert memory["sections"]["interests"] == []
    assert [r["date"] for r in memory["recent_summaries"]] == ["2026-10-01"]  # the last summary went with its block


def test_her_text_edit_refuses_stray_lines_and_a_changed_memory(env):
    rendered_memory(env)
    before = env.store.get_memory(DAD)
    text = before["memory_prompt"]
    path = f"/api/caregiver/{DAD}/memory/edit-text"
    r = post(env, path, {"old": text, "text": text + "\nA line with no heading"})
    assert r.status_code == 422 and "A line with no heading" in r.json()["detail"]
    assert post(env, path, {"old": text, "text": "Some heading:\n- x"}).status_code == 422
    assert post(env, path, {"old": "an older text", "text": text}).status_code == 409
    assert env.store.get_memory(DAD) == before


def test_focus_points_are_edited_one_per_line(env):
    rendered_memory(env)
    path = f"/api/caregiver/{DAD}/memory/edit-focus"
    r = post(env, path, {"items": ["  Ask about the trip  ", "", "Practice the names game"]})
    assert r.status_code == 200
    memory = env.store.get_memory(DAD)
    assert memory["focus_next_session"] == ["Ask about the trip", "Practice the names game"]
    assert post(env, path, {"items": ["a", "b", "c", "d", "e"]}).status_code == 422
    assert post(env, path, {"items": ["x" * 201]}).status_code == 422
    assert post(env, path, {"items": []}).status_code == 200 and env.store.get_memory(DAD)["focus_next_session"] == []


def test_memory_edits_are_for_caregivers_only(env):
    memory_with_facts(env)
    r = post(env, f"/api/caregiver/{DAD}/memory/add-item", {"section": "interests", "text": "x"}, token="tok-dad")
    assert r.status_code == 403


# ---- his names and places (the profile's vocabulary, 21) -----------------------------------------------

def inferred_profile(env, pid=DAD, vocabulary=("דליה", "חיפה"), blocked=()):
    from app.patient_profile import render_inferred
    env.store.save_profile(pid, render_inferred(["Retired."], list(vocabulary), None), "inferred", "app",
                           extra={"about": ["Retired."], "vocabulary": list(vocabulary),
                                  "vocabulary_blocked": list(blocked)})


def test_a_removed_word_leaves_the_vocabulary_and_the_text(env):
    from app.patient_profile import extract_vocabulary
    inferred_profile(env)
    r = post(env, f"/api/caregiver/{DAD}/vocabulary/remove", {"word": "דליה"})
    assert r.status_code == 200
    prof = env.store.get_profile(DAD)
    assert prof["vocabulary"] == ["חיפה"] and prof["vocabulary_blocked"] == ["דליה"]
    assert extract_vocabulary(prof["text"]) == ["חיפה"] and prof["about"] == ["Retired."]
    assert prof["source"] == "inferred"
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/remove", {"word": "דליה"}).status_code == 409


def test_adding_a_word_back_unblocks_it(env):
    inferred_profile(env, vocabulary=("חיפה",), blocked=("דליה",))
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/add", {"word": " דליה "}).status_code == 200
    prof = env.store.get_profile(DAD)
    assert prof["vocabulary"] == ["דליה", "חיפה"] and prof["vocabulary_blocked"] == []
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/add", {"word": "x" * 41}).status_code == 422
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/add", {"word": "  "}).status_code == 422


def test_an_uploaded_profile_is_not_edited_by_the_vocabulary_editor(env):  # Review Focus 3
    env.store.save_profile(DAD, "His assessment.\nVocabulary: דליה", "uploaded", TOMER)
    before = env.store.get_profile(DAD)
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/remove", {"word": "דליה"}).status_code == 409
    assert post(env, f"/api/caregiver/{DAD}/vocabulary/add", {"word": "חיפה"}).status_code == 409
    assert env.store.get_profile(DAD) == before


def test_setting_a_need_keeps_the_blocked_list(env):
    inferred_profile(env, blocked=("עכו",))
    assert env.client.put(f"/api/caregiver/{DAD}/needs/naming", headers=auth("tok-tomer"),
                          json={"level": "some_difficulty", "note": "x"}).status_code == 200
    assert env.store.get_profile(DAD)["vocabulary_blocked"] == ["עכו"]


def test_the_overview_has_the_vocabulary_and_the_summaries(env):
    inferred_profile(env, blocked=("עכו",))
    with_summaries(env)
    ov = get(env, f"/api/caregiver/{DAD}/overview").json()
    assert ov["profile"]["vocabulary"] == ["דליה", "חיפה"] and ov["profile"]["vocabulary_blocked"] == ["עכו"]
    assert ov["profile"]["source"] == "inferred"
    assert [r["date"] for r in ov["memory"]["recent_summaries"]] == ["2026-10-01", "2026-10-02"]
