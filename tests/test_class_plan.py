"""Lesson plans (05, 13.5): the intro, rendering, the tool-based builder, probes, and wiring."""

import datetime as dt
import re

from app import llm
from app.agent.memory_update import run_memory_update
from app.agent.next_class import build_next_plan
from app.class_plan import intro_plan, plan_for_session, render_class_plan, render_plan_full
from app.config import Settings
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from conftest import DAD, FakeAuthTokens, auth
from fake_llm import FakeClient, text, tool_calls
from plan_helpers import a_plan, builder_rounds, plan_context

TODAY = dt.date(2026, 10, 2)
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
GAME = {"kind": "names_game", "items": [{"target": "טבריה", "kind": "treated", "elicit": "העיר על הכנרת"},
                                        {"target": "צפת", "kind": "untreated", "elicit": "עיר המקובלים"}]}


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


def system_instruction():
    return FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text


# ---- choosing and rendering -------------------------------------------------------------------

def test_intro_plan_for_a_new_account_and_none_once_there_is_memory_but_no_plan():
    store = InMemorySessionStore()
    assert plan_for_session(store, DAD).plan_type == "intro"
    store.save_memory(DAD, "s", {"memory_prompt": "He loves the Galilee."}, None)
    assert plan_for_session(store, DAD) is None  # a free conversation, never blocks
    store.save_next_plan(DAD, "s", a_plan().model_dump(mode="json"))
    assert plan_for_session(store, DAD).primary_goal.type.value == "name_retrieval"
    # a plan saved before 13.5 (no steps) counts as no plan: it's rebuilt
    store.save_next_plan(DAD, "s", {"plan_type": "regular", "primary_goal": {"type": "discourse", "description": "x"},
                                    "practice": [{"target": "כנרת"}]})
    assert plan_for_session(store, DAD) is None


def test_tutor_gets_only_the_session_level_parts_the_family_gets_everything():
    plan = a_plan()
    out = render_class_plan(plan)
    assert "Main goal (name_retrieval)" in out and "Homework (say it ONLY in the closing" in out
    assert "Avoid: politics" in out and "כנרת" not in out  # the steps come from the page, one at a time
    full = render_plan_full(plan)
    assert "Steps:" in full and 'Ask: "איך נקרא כנרת?" (answer: כנרת)' in full
    assert render_class_plan(None) == "" == render_plan_full(None)


def test_intro_plan_is_steps():
    plan = intro_plan()
    assert plan.plan_type == "intro" and plan.probe == [] and "names" in plan.primary_goal.description
    assert [s.kind for s in plan.steps] == ["opening", "activity", "thread", "thread"]
    assert "\n" not in plan.steps[1].instructions  # folded YAML is normalized


# ---- the builder ------------------------------------------------------------------------------

def test_builder_saves_a_plan_of_steps_with_recent_goals_in_context():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee.", "word_bank": {
        "טבריה": {"attempts": 1, "failed": 1, "last_result": "failed", "next_due": "2026-10-01"}}}, None)
    old = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, old, {"class_plan": a_plan(goal="discourse").model_dump(mode="json")})
    client = FakeClient(*builder_rounds())
    assert build_next_plan(store, client, SETTINGS, DAD, old, today=TODAY, generate_fn=gen) == "done"
    saved = store.get_next_plan(DAD)
    assert saved["plan_type"] == "regular" and saved["built_after_session"] == old
    assert [s["kind"] for s in saved["steps"]] == ["opening", "practice", "practice", "activity", "thread",
                                                     "thread", "thread", "thread", "thread", "sequencing"]
    assert saved["estimated_minutes"] == 12.1 and saved["homework"] == "Think of a place."
    assert saved["steps"][-1]["told_order"] not in ([1, 2, 3, 4], [4, 3, 2, 1])  # scrambled by code
    context = plan_context(client)
    assert "- discourse: Names of places he loves." in context  # recent goals, for rotation
    assert "first): טבריה" in context  # the word bank's due words
    session = store.get_session(DAD, old)
    assert (session["plan_status"], session["plan_tool_calls"], session["plan_tool_errors"]) == ("done", 13, 0)


def test_builder_without_memory_leaves_the_intro_for_next_time():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    assert build_next_plan(store, FakeClient(), SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    assert store.get_next_plan(DAD) is None


# ---- probes recorded by the memory update -------------------------------------------------------

def test_memory_update_scores_the_sessions_names_game():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    plan = a_plan(steps=[{"kind": "opening"}, GAME])
    store.update_session(DAD, sid, {"class_plan": plan.model_dump(mode="json")})
    store.upsert_turns(DAD, sid, [TurnIn(seq=i, speaker=sp, text=tx, t_start_s=i)
                                  for i, (sp, tx) in enumerate([("tutor", "העיר על הכנרת?"), ("patient", "טבריה"),
                                                                ("tutor", "עיר המקובלים?"), ("patient", "צפת")])])
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    client = FakeClient(
        tool_calls(("record_word_result", {"word": "טבריה", "result": "uncued", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "צפת", "result": "cued", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "כנרת", "result": "cued", "asr_confidence": "high"})),
        text("done"),
    )
    assert run_memory_update(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    session = store.get_session(DAD, sid)
    assert session["probe_results"] == [
        {"word": "טבריה", "result": "uncued", "kind": "treated", "low_confidence": False},
        {"word": "צפת", "result": "cued", "kind": "untreated", "low_confidence": False},
    ]  # כנרת was practice, not the names game
    assert session["plan_status"] == "pending"  # next: build the next plan
    context = client.requests[0]["contents"][0].parts[0].text
    assert "TODAY'S PLAN" in context and 'Names game, 2 questions' in context


# ---- wiring through the API --------------------------------------------------------------------------

def test_first_session_gets_the_intro_and_the_session_keeps_its_plan(env):
    env.store.save_profile(DAD, "Man, 70.", "uploaded", "tomer@example.com")  # uploaded: no needs check (15.5)
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert "## TODAY'S PLAN" in system_instruction() and "Plan type: intro" in system_instruction()
    assert env.store.get_session(DAD, body["session_id"])["class_plan"]["plan_type"] == "intro"
    assert body["agenda"]["kinds"] == ["opening", "activity", "thread", "thread"]


def test_next_session_follows_the_built_plan_with_the_names_game_from_the_set(env):
    from app.check_in_set import new_set
    from app.schemas import CheckInItem
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan().model_dump(mode="json"))
    # without a set there is no names game today
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["names_game"] is False and "names_game" not in body["agenda"]["kinds"]
    env.store.save_check_in_set(DAD, new_set([CheckInItem(target="עכו", question="העיר העתיקה עם החומות?"),
                                              CheckInItem(target="טבריה", question="העיר על הכנרת?", kind="treated")],
                                             "s0", TODAY))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["names_game"] is True and body["agenda"]["kinds"][1] == "names_game"
    assert '"העיר על הכנרת?" (answer: טבריה)' in body["agenda"]["steps"][1]
    # today's game name טבריה is not practiced again in the same session
    assert not any("answer: טבריה)" in s and s.startswith("Practice") for s in body["agenda"]["steps"])
    instruction = system_instruction()
    assert "Main goal (name_retrieval)" in instruction and "Never read the plan aloud" in " ".join(instruction.split())
    probe = env.store.get_session(DAD, body["session_id"])["class_plan"]["steps"][1]["items"]
    assert {(p["target"], p["kind"]) for p in probe} == {("עכו", "untreated"), ("טבריה", "treated")}


def test_memory_but_no_plan_means_a_free_conversation(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert "## TODAY'S PLAN" not in system_instruction() and "Never read the plan" not in system_instruction()
    assert "class_plan" not in env.store.get_session(DAD, body["session_id"])
    assert body["agenda"]["kinds"] == ["opening", "conversation"]


def test_forget_memory_makes_the_next_session_an_intro_again(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan().model_dump(mode="json"))
    env.client.post(f"/api/caregiver/{DAD}/reset", headers=auth("tok-tomer"),
                    json={"scope": "memory", "confirm_email": DAD})
    env.client.post("/api/session/start", headers=auth())
    assert "Plan type: intro" in system_instruction()


def test_hebrew_sentences_never_share_a_line_with_english():
    from app.class_plan import HEBREW
    out = render_class_plan(a_plan(homework="אני רוצה שתחשוב על מקום שאתה אוהב לטייל בו.",
                                   fatigue_fallback='Talk about his garden, using the word "גינה".'))
    assert "Homework (say it ONLY in the closing, after the wrap-up note):\n      אני רוצה" in out
    assert 'If he is tired or frustrated: Talk about his garden, using the word "גינה".' in out
    for line in out.splitlines():
        hebrew_words = sum(1 for w in line.split() if HEBREW.search(w))
        english_words = sum(1 for w in line.split() if re.fullmatch(r"[A-Za-z]{3,}[:,.]?", w))
        assert not (hebrew_words > 2 and english_words > 2), line


def test_notes_applied_is_for_caregivers_only():
    assert "per the notes" not in render_class_plan(a_plan(notes_applied="Family names only, per the notes."))
