"""Lesson plans (sub-plan 05): intro, rendering, the builder, probes, and wiring."""

import datetime as dt

from app import llm
from app.agent.memory_update import run_memory_update
from app.agent.next_class import build_next_plan
from app.class_plan import intro_plan, plan_for_session, render_class_plan
from app.config import Settings
from app.schemas import ClassPlan, ConsolidatedMemory
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from conftest import DAD, FakeAuthTokens, auth
from fake_llm import FakeClient, text, tool_calls

TODAY = dt.date(2026, 10, 2)
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
PROBES = [{"target": "טבריה", "kind": "treated", "elicit": "העיר על הכנרת"},
          {"target": "עכו", "kind": "untreated", "elicit": "העיר העתיקה עם החומות"},
          {"target": "צפת", "kind": "untreated", "elicit": "עיר המקובלים"}]


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


def a_plan(**over) -> ClassPlan:
    fields = dict(plan_type="regular",
                  primary_goal={"type": "name_retrieval", "description": "Names of places he loves."},
                  recall_from_last_time="Last time he told you about his trip to the Galilee.",
                  probe=PROBES,
                  practice=[{"target": "כנרת", "elicit": "האגם בצפון", "hint_meaning": "מקור מים",
                             "hint_first_syllable": "כִּנֶּ...", "sentence_completion": "בקיץ שוחים ב..."}],
                  homework="Think of a place to tell me about.", fatigue_fallback="Talk about his garden.",
                  avoid=["politics"])
    fields.update(over)
    return ClassPlan(**fields)


def system_instruction():
    return FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text


# ---- choosing and rendering -------------------------------------------------------------------

def test_intro_plan_for_a_new_account_and_none_once_there_is_memory_but_no_plan():
    store = InMemorySessionStore()
    assert plan_for_session(store, DAD).plan_type == "intro"
    store.save_memory(DAD, "s", {"memory_prompt": "He loves the Galilee."}, None)
    assert plan_for_session(store, DAD) is None  # generic structure, never blocks
    store.save_next_plan(DAD, "s", a_plan().model_dump(mode="json"))
    assert plan_for_session(store, DAD).primary_goal.type.value == "name_retrieval"


def test_render_lists_the_checkins_without_hints_and_the_practice_hints():
    out = render_class_plan(a_plan())
    assert "WITHOUT any hint first" in out
    assert "(treated) ask: העיר על הכנרת -> answer: טבריה" in out
    assert "first syllable: כִּנֶּ..." in out
    assert "Homework to give at the end" in out and "Avoid: politics" in out
    assert render_class_plan(None) == ""


def test_intro_plan_template_is_clean():
    plan = intro_plan()
    assert plan.plan_type == "intro" and plan.probe == [] and "names" in plan.primary_goal.description
    assert "\n" not in plan.activity  # folded YAML is normalized


def test_tidy_trims_oversized_plans():
    plan = a_plan(probe=PROBES * 3, conversation_topics=["a", "b", "c", "d"], plan_type="weird").tidy()
    assert len(plan.probe) == 5 and len(plan.conversation_topics) == 3 and plan.plan_type == "regular"


# ---- the builder ------------------------------------------------------------------------------

def test_builder_saves_a_valid_plan_with_recent_goals_in_context():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee.", "word_bank": {
        "טבריה": {"attempts": 1, "failed": 1, "last_result": "failed", "next_due": "2026-10-01"}}}, None)
    old = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, old, {"class_plan": a_plan(primary_goal={"type": "discourse", "description": "Tell a story"}).model_dump(mode="json")})
    client = FakeClient(text("{}", parsed=a_plan()))
    assert build_next_plan(store, client, SETTINGS, DAD, old, today=TODAY, generate_fn=gen) == "done"
    saved = store.get_next_plan(DAD)
    assert saved["plan_type"] == "regular" and saved["built_after_session"] == old
    context = client.requests[0]["contents"]
    assert "- discourse: Tell a story" in context  # recent goals, for rotation
    assert "due for practice today: טבריה" in context  # the word bank's due words
    assert store.get_session(DAD, old)["plan_status"] == "done"


def test_builder_rejects_a_plan_without_checkin_items():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "x"}, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    client = FakeClient(text("{}", parsed=a_plan(probe=[])))
    assert build_next_plan(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "failed"
    assert store.get_next_plan(DAD) is None
    assert "probe items" in store.get_session(DAD, sid)["plan_error"]


def test_builder_without_memory_leaves_the_intro_for_next_time():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    assert build_next_plan(store, FakeClient(), SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    assert store.get_next_plan(DAD) is None


# ---- probes recorded by the memory update -------------------------------------------------------

def test_memory_update_scores_the_sessions_checkin_items():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"class_plan": a_plan().model_dump(mode="json")})
    store.upsert_turns(DAD, sid, [TurnIn(seq=i, speaker=sp, text=tx, t_start_s=i)
                                  for i, (sp, tx) in enumerate([("tutor", "העיר על הכנרת?"), ("patient", "טבריה"),
                                                                ("tutor", "עיר המקובלים?"), ("patient", "צפת")])])
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    client = FakeClient(
        tool_calls(("record_word_result", {"word": "טבריה", "result": "uncued", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "צפת", "result": "cued", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "כנרת", "result": "cued", "asr_confidence": "high"})),
        text("done"),
        text("{}", parsed=ConsolidatedMemory(memory_prompt="m", focus_next_session=[])),
    )
    assert run_memory_update(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    session = store.get_session(DAD, sid)
    assert session["probe_results"] == [
        {"word": "טבריה", "result": "uncued", "kind": "treated", "low_confidence": False},
        {"word": "צפת", "result": "cued", "kind": "untreated", "low_confidence": False},
    ]  # כנרת was practice, not a check-in
    assert session["plan_status"] == "pending"  # next: build the next plan
    assert "TODAY'S PLAN" in client.requests[0]["contents"][0].parts[0].text


# ---- wiring through the API --------------------------------------------------------------------------

def test_first_session_gets_the_intro_and_the_session_keeps_its_plan(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    assert "## TODAY'S PLAN" in system_instruction() and "Plan type: intro" in system_instruction()
    assert env.store.get_session(DAD, sid)["class_plan"]["plan_type"] == "intro"


def test_next_session_follows_the_built_plan(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan().model_dump(mode="json"))
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    instruction = system_instruction()
    assert "Main goal (name_retrieval)" in instruction and "-> answer: טבריה" in instruction
    assert "Never read the plan aloud" in " ".join(instruction.split())
    assert env.store.get_session(DAD, sid)["class_plan"]["probe"][0]["target"] == "טבריה"


def test_memory_but_no_plan_means_no_plan_section_at_all(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]
    assert "## TODAY'S PLAN" not in system_instruction() and "Never read the plan" not in system_instruction()
    assert "class_plan" not in env.store.get_session(DAD, sid)


def test_forget_memory_makes_the_next_session_an_intro_again(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan().model_dump(mode="json"))
    env.client.post("/api/admin/reset", headers=auth("tok-tomer"),
                    json={"email": DAD, "scope": "memory", "confirm_email": DAD})
    env.client.post("/api/session/start", headers=auth())
    assert "Plan type: intro" in system_instruction()


def test_treated_or_untreated_is_decided_by_the_word_bank_not_the_model():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "x", "word_bank": {"טבריה": {"attempts": 1}}}, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    claimed = [dict(p, kind="treated") for p in PROBES]  # the model says everything was practiced
    client = FakeClient(text("{}", parsed=a_plan(probe=claimed)))
    build_next_plan(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen)
    kinds = {p["target"]: p["kind"] for p in store.get_next_plan(DAD)["probe"]}
    assert kinds == {"טבריה": "treated", "עכו": "untreated", "צפת": "untreated"}


def test_checkin_lead_ins_are_rendered():
    plan = a_plan(probe=[dict(PROBES[0], bridge="מדברים על הכנרת...")] + PROBES[1:])
    assert "lead-in: מדברים על הכנרת... | ask: העיר על הכנרת" in render_class_plan(plan)
