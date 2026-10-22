"""15.5: a new account's first two sessions find out what he needs; the app infers his profile."""
import datetime as dt

import pytest

from app import llm
from app.agent.memory_tools import Inferring, MemoryDraft, build_memory_tools
from app.agent.memory_update import run_memory_update, save_inferred
from app.agent.next_class import build_context, build_next_plan
from app.class_plan import fixed_plan, session_steps
from app.config import Settings
from app.patient_profile import account_profile, extract_vocabulary, needs_lines
from app.schemas import MemorySections
from app.steps import CheckStep
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from conftest import DAD, TOMER, FakeAuthTokens, auth
from fake_llm import FakeClient, text, tool_calls

SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
NEW = "new@example.com"


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


# ---- the first two sessions ---------------------------------------------------------------------

def test_a_new_account_starts_with_the_needs_check_and_an_uploaded_one_without(env):
    body = env.client.post("/api/session/start", headers=auth()).json()  # no profile
    assert body["agenda"]["kinds"] == ["opening", "activity", "check", "thread", "check", "thread", "check"]
    assert body["agenda"]["min_answers"][2] == 3  # the naming riddles: three answers before it ends
    saved = env.store.get_session(DAD, body["session_id"])["class_plan"]
    assert (saved["plan_type"], saved["intro_part"]) == ("intro", 1)
    env.store.save_profile(TOMER, "Man, 70.", "uploaded", TOMER)
    body = env.client.post("/api/session/start", headers=auth("tok-tomer")).json()
    assert "check" not in body["agenda"]["kinds"]  # an uploaded profile: just getting to know him


def test_checks_are_spread_and_never_called_a_test():
    for name in ("intro_needs_1", "intro_needs_2"):
        kinds = [s.kind for s in fixed_plan(name).steps]
        assert kinds[0] == "opening" and kinds[1] != "check"  # never right after the greeting
        assert all(not (a == b == "check") for a, b in zip(kinds, kinds[1:]))  # never two in a row
    areas = {s.area for name in ("intro_needs_1", "intro_needs_2") for s in fixed_plan(name).steps
             if isinstance(s, CheckStep)}
    assert areas == {"naming", "goals", "repetition", "understanding", "connected_speech", "clarity"}
    step = CheckStep(area="repetition", items=["שולחן", "כוס קפה חם"])
    text_ = step.instruction()
    assert 'ITEMS: 1) "שולחן" 2) "כוס קפה חם"' in text_ and "never say test" in text_
    assert session_steps(fixed_plan("intro_needs_1"))[2]["min_answers"] == 3


def ended(store, pid, plan, days_ago=0):
    sid = store.create_session(pid, user_email=pid, model="m", prompt_version="v")
    store.update_session(pid, sid, {"class_plan": plan.model_dump(mode="json"),
                                    "started_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)})
    store.end_session(pid, sid, EndReason.tutor_goodbye)
    return sid


def test_after_the_first_the_second_is_fixed_no_model():
    store = InMemorySessionStore()
    store.save_memory(NEW, "s0", {"memory_prompt": "He is new."}, None)
    sid = ended(store, NEW, fixed_plan("intro_needs_1"))
    assert build_next_plan(store, FakeClient(), SETTINGS, NEW, sid, generate_fn=gen) == "done"  # no replies scripted
    nxt = store.get_next_plan(NEW)
    assert (nxt["plan_type"], nxt["intro_part"]) == ("intro", 2)
    assert store.get_session(NEW, sid)["plan_model"] == "fixed: intro_needs_2"


# ---- the memory agent records needs and the profile ----------------------------------------------

def inferring_draft(**areas):
    return MemoryDraft(sections=MemorySections(), word_bank={}, today=dt.date(2026, 10, 15),
                       inferring=Inferring(areas=dict(areas)))


def test_record_needs_no_quote_no_level_and_the_familys_word_wins():
    draft = inferring_draft(naming={"level": "some_difficulty", "set_by": "family", "note": "therapist"})
    tools = {t.name: t.handler for t in build_memory_tools(draft)}
    tools["record_needs"]({"area": "repetition", "level": "ok", "evidence": [], "note": "Said all three."})
    assert draft.inferring.areas["repetition"]["level"] == "unclear"  # no evidence: never a guess
    tools["record_needs"]({"area": "naming", "level": "ok", "evidence": ["מפתח", "בננה"], "note": "All four."})
    naming = draft.inferring.areas["naming"]
    assert (naming["level"], naming["set_by"], naming["app_note"]) == ("some_difficulty", "family", "All four.")
    with pytest.raises(ValueError, match="for goals"):
        tools["record_needs"]({"area": "goals", "note": ""})
    tools["record_needs"]({"area": "goals", "note": "Wants to tell stories to his grandchildren.", "evidence": []})
    assert draft.inferring.areas["goals"]["level"] == "noted"
    assert {t.name for t in build_memory_tools(MemoryDraft(sections=MemorySections(), word_bank={},
                                                           today=None))}.isdisjoint({"record_needs", "update_profile"})


def session_with_talk(store, pid):
    sid = store.create_session(pid, user_email=pid, model="m", prompt_version="v")
    store.update_session(pid, sid, {"class_plan": fixed_plan("intro_needs_1").model_dump(mode="json")})
    store.upsert_turns(pid, sid, [TurnIn(seq=i, speaker="patient", text=tx, t_start_s=i * 10) for i, tx in enumerate(
        ["אני מורה בפנסיה, גר בעכו", "מפתח... בננה... בית מרקחת", "אהה... נהריה! שם גדלתי"])])
    store.end_session(pid, sid, EndReason.tutor_goodbye)
    return sid


def test_a_new_accounts_first_session_infers_his_profile_and_needs():
    store = InMemorySessionStore()
    sid = session_with_talk(store, NEW)
    client = FakeClient(
        tool_calls(("record_needs", {"area": "naming", "level": "some_difficulty", "evidence": ["מפתח... בננה"],
                                     "note": "Found them after a pause."}),
                   ("update_profile", {"field": "about", "op": "add", "item": "Retired teacher; lives in Akko."}),
                   ("update_profile", {"field": "vocabulary", "op": "add", "item": "עכו"}),
                   ("record_word_result", {"word": "נהריה", "result": "self_found", "asr_confidence": "high"})),
        text("done"))
    assert run_memory_update(store, client, SETTINGS, NEW, sid, generate_fn=gen) == "done"
    assert "record_needs" in {d.name for d in client.requests[0]["config"].tools[0].function_declarations}
    assert "# HIS NEEDS SO FAR" in client.requests[0]["contents"][0].parts[0].text
    needs = store.get_needs(NEW)["areas"]
    assert (needs["naming"]["level"], needs["naming"]["session"]) == ("some_difficulty", sid)
    profile = account_profile(store, NEW)
    assert profile.source == "inferred" and "Retired teacher; lives in Akko." in profile.text
    assert "Naming: some difficulty -- Found them after a pause." in profile.text
    assert extract_vocabulary(profile.text) == ["נהריה", "עכו"]  # his own names first, by code


def test_an_uploaded_profile_is_never_touched():
    store = InMemorySessionStore()
    store.save_profile(DAD, "his assessment", "uploaded", TOMER)
    sid = session_with_talk(store, DAD)
    client = FakeClient(text("done"))
    run_memory_update(store, client, SETTINGS, DAD, sid, generate_fn=gen)
    offered = {d.name for d in client.requests[0]["config"].tools[0].function_declarations}
    assert "record_needs" in offered and "update_profile" not in offered  # his needs yes, his profile never
    assert store.get_profile(DAD)["text"] == "his assessment" and store.get_needs(DAD) is None
    # and if the family uploads one while the agent is working, the agent's result doesn't replace it
    store2 = InMemorySessionStore()
    draft = inferring_draft()
    draft.inferring.about = ["Something."]
    store2.save_profile(NEW, "uploaded meanwhile", "uploaded", TOMER)
    save_inferred(store2, NEW, "s1", draft, dt.date(2026, 10, 15))
    assert store2.get_profile(NEW)["text"] == "uploaded meanwhile"


# ---- the plan builder, the session, the caregiver page --------------------------------------------

def test_the_builder_sees_his_needs():
    needs = {"areas": {"naming": {"level": "clear_difficulty", "note": "Long pauses.", "set_by": "app"},
                       "clarity": {"level": "some_difficulty", "set_by": "family"}}}
    lines = needs_lines(needs)
    assert lines == ["Naming: clear difficulty -- Long pauses.",
                     "Speech clarity: some difficulty (set by the family) [not practiced in the app yet]"]
    context = build_context({"memory_prompt": "m"}, [], "", dt.date(2026, 10, 15), needs_text="\n".join(lines))
    assert "# HIS NEEDS" in context and "Naming: clear difficulty" in context


def test_the_session_gets_the_inferred_profile(env):
    env.store.save_profile(DAD, "Inferred...\n- Vocabulary: עכו, נהריה", "inferred", "app",
                           extra={"about": [], "vocabulary": ["עכו", "נהריה"]})
    env.client.post("/api/session/start", headers=auth())
    cfg = FakeAuthTokens.last_config.live_connect_constraints.config
    assert "Inferred..." in cfg.system_instruction.parts[0].text
    assert cfg.input_audio_transcription.custom_vocabulary == ["עכו", "נהריה"]


def test_the_family_sets_an_area_and_the_inferred_profile_follows(env):
    env.store.save_profile(DAD, "old", "inferred", "app", extra={"about": ["Retired teacher."], "vocabulary": ["עכו"]})
    r = env.client.put(f"/api/caregiver/{DAD}/needs/repetition", headers=auth("tok-tomer"),
                       json={"level": "clear_difficulty", "note": "His therapist works on it."})
    assert r.status_code == 200
    area = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["needs"]["areas"]["repetition"]
    assert (area["level"], area["set_by"], area["by"]) == ("clear_difficulty", "family", TOMER)
    profile = env.store.get_profile(DAD)
    assert profile["source"] == "inferred" and "Repetition: clear difficulty (set by the family)" in profile["text"]
    assert env.client.put(f"/api/caregiver/{DAD}/needs/naming", headers=auth("tok-tomer"),
                          json={"level": "terrible"}).status_code == 422
    assert env.client.put(f"/api/caregiver/{DAD}/needs/naming", headers=auth(), json={"level": "ok"}).status_code == 403


# ---- tracking his needs over time, for every account (15.5b) -------------------------------------

def test_his_needs_build_a_history_and_points_for_his_therapist_without_touching_his_profile():
    store = InMemorySessionStore()
    store.save_profile(DAD, "his assessment", "uploaded", TOMER)
    for level, point in (("clear_difficulty", None), ("some_difficulty", "כדאי לשאול אם לתרגל שמות של מקומות")):
        sid = session_with_talk(store, DAD)
        calls = [("record_needs", {"area": "naming", "level": level, "evidence": ["מפתח... בננה"], "note": "Pauses."})]
        if point:
            calls.append(("suggest_for_therapist", {"point": point, "why": "Place names hard in 2 sessions.",
                                                    "evidence": ["אהה... נהריה"]}))
        client = FakeClient(tool_calls(*calls), text("done"))
        run_memory_update(store, client, SETTINGS, DAD, sid, generate_fn=gen)
    needs = store.get_needs(DAD)
    assert [h["level"] for h in needs["areas"]["naming"]["history"]] == ["clear_difficulty", "some_difficulty"]
    assert "history: clear_difficulty" in client.requests[0]["contents"][0].parts[0].text  # the agent sees it
    assert [p["text"] for p in needs["therapist_points"]] == ["כדאי לשאול אם לתרגל שמות של מקומות"]
    assert store.get_profile(DAD)["text"] == "his assessment"  # never touched


def test_a_point_is_not_repeated_and_at_most_two_a_session():
    draft = inferring_draft()
    draft.inferring.points = [{"text": "כבר ברשימה"}]
    tools = {t.name: t.handler for t in build_memory_tools(draft)}
    with pytest.raises(ValueError, match="already on the list"):
        tools["suggest_for_therapist"]({"point": "כבר ברשימה", "why": "x"})
    tools["suggest_for_therapist"]({"point": "א", "why": "x"})
    tools["suggest_for_therapist"]({"point": "ב", "why": "x"})
    with pytest.raises(ValueError, match="at most two"):
        tools["suggest_for_therapist"]({"point": "ג", "why": "x"})


def test_with_an_uploaded_profile_his_needs_never_reach_the_plan(env):
    from conftest import DAD as pid
    store = InMemorySessionStore()
    store.save_memory(pid, "s0", {"memory_prompt": "m"}, None)
    store.save_needs(pid, {"areas": {"naming": {"level": "clear_difficulty", "set_by": "app"}}})
    store.save_profile(pid, "his assessment", "uploaded", TOMER)
    sid = ended(store, pid, fixed_plan("intro_plan"))
    from plan_helpers import builder_rounds
    client = FakeClient(*builder_rounds(names=("עכו", "נהריה")))
    build_next_plan(store, client, SETTINGS, pid, sid, generate_fn=gen)
    context = client.requests[0]["contents"][0].parts[0].text
    assert "(none recorded: plan from the profile)" in context and "Naming: clear difficulty" not in context


def test_the_family_marks_a_point_raised(env):
    env.store.save_needs(DAD, {"areas": {}, "therapist_points": [{"id": "s1-0", "text": "נקודה", "status": "new"}]})
    url = f"/api/caregiver/{DAD}/therapist-points/s1-0"
    assert env.client.put(url, headers=auth("tok-tomer"), json={"status": "raised"}).status_code == 200
    assert env.store.get_needs(DAD)["therapist_points"][0]["status"] == "raised"
    assert env.client.put(f"/api/caregiver/{DAD}/therapist-points/nope", headers=auth("tok-tomer"),
                          json={"status": "raised"}).status_code == 404


# ---- needs checks a session didn't reach carry over (17) ---------------------------------------------

def test_missed_checks_go_into_the_second_session_and_then_one_per_plan():
    from app.class_plan import add_one_check, missed_checks
    first = fixed_plan("intro_needs_1").model_dump(mode="json")
    session = {"class_plan": first, "steps_done": [{"done": "a"}, {"done": "b"}, {"done": "c"}]}  # 3 of 7
    assert [c["area"] for c in missed_checks(session)] == ["repetition", "goals"]  # naming was reached
    store = InMemorySessionStore()
    store.save_memory(NEW, "s0", {"memory_prompt": "He is new."}, None)
    sid = ended(store, NEW, fixed_plan("intro_needs_1"))
    store.update_session(NEW, sid, {"steps_done": session["steps_done"]})
    store.save_needs(NEW, {"areas": {"naming": {"level": "ok", "set_by": "app"}}})
    build_next_plan(store, FakeClient(), SETTINGS, NEW, sid, generate_fn=gen)
    kinds = [(s["kind"], s.get("area")) for s in store.get_next_plan(NEW)["steps"]]
    assert kinds[-4:] == [("thread", None), ("check", "repetition"), ("thread", None), ("check", "goals")]
    assert all(not (a[0] == b[0] == "check") for a, b in zip(kinds, kinds[1:]))  # never two in a row
    assert store.get_needs(NEW)["pending_checks"] == [] and "naming" in store.get_needs(NEW)["areas"]  # kept
    # inside a built plan: after a thread that isn't followed by a check
    steps = [{"kind": "opening"}, {"kind": "thread"}, {"kind": "check"}, {"kind": "thread"}, {"kind": "practice"}]
    out = add_one_check(steps, {"kind": "check", "area": "goals"})
    assert [s["kind"] for s in out] == ["opening", "thread", "check", "thread", "check", "practice"]
