"""13 / 13.5: the plan's steps -- each step type owns its rules; the page hands them out one at a
time after each next_step call; one mode only."""

import pytest

from app.agent.plan_tools import BUDGET_MINUTES, PlanDraft, build_plan_tools
from app.class_plan import prepare_for_session, session_steps
from app.steps import FOLLOW_UP, NamesGameStep, PracticeStep, ThreadStep, overview
from conftest import DAD, FakeAuthTokens, auth
from plan_helpers import a_plan, practice, thread
from test_names_game import a_set

PLAN = a_plan()


# ---- each step type: content (from the plan) + fixed rules (from the class) ----------------

def test_a_step_is_its_content_plus_its_fixed_rules():
    step = PracticeStep(**practice("טבריה", topic="the Sea of Galilee"))
    text = step.instruction()
    assert text.startswith("Practice, inside a conversation about the Sea of Galilee.")
    assert 'Ask: "איך נקרא טבריה?" (answer: טבריה)' in text
    assert "HOW: A real short conversation about the topic -- a few exchanges, not a quiz" in text
    assert "After the name, talk about it with him" in text
    assert "follow up at least twice on his OWN words" in ThreadStep(**thread()).instruction()
    game = NamesGameStep(items=[{"target": "עכו", "kind": "untreated", "elicit": "העיר עם החומות?"}])
    assert '1) "העיר עם החומות?" (answer: עכו)' in game.instruction() and "NO hints" in game.instruction()


def test_saved_plans_hold_only_the_content_the_rules_come_from_the_code():
    saved = PLAN.model_dump(mode="json")
    assert "HOW" not in str(saved) and "RULES" not in str(saved)
    assert saved["steps"][2] == {"kind": "practice", **practice("כנרת"), "bridge": ""}


# ---- session start: only what can't be known when the plan is built -------------------------

def test_session_start_fills_the_game_drops_its_names_from_practice_and_starts_with_the_opening():
    plan = prepare_for_session(PLAN, a_set(("טבריה", "treated"), ("עכו", "untreated")))
    assert [s.kind for s in plan.steps] == ["opening", "names_game", "practice", "activity", "thread"]
    assert {p.target for p in plan.probe} == {"טבריה", "עכו"}
    assert [s.name for s in plan.steps if s.kind == "practice"] == ["כנרת"]  # טבריה is in today's game
    # no set -> no game today; a plan without an opening gets one first
    plan = prepare_for_session(a_plan(steps=[{"kind": "names_game"}, {"kind": "thread", **thread()}]), None)
    assert [s.kind for s in plan.steps] == ["opening", "thread"]


def test_without_a_plan_the_steps_are_opening_and_his_topic():
    assert [s["kind"] for s in session_steps(None)] == ["opening", "conversation"]
    # no agenda at all: with a numbered list she saw where the plan ended and closed there (12.10)
    assert "always a next step" in overview(session_steps(PLAN)) and "1." not in overview(session_steps(PLAN))
    assert all(s["text"].endswith("never right after you asked something.") for s in session_steps(PLAN))


# ---- the plan builder's tools ----------------------------------------------------------------

def tools_for(draft, **kw):
    kw.setdefault("check_practice", lambda step: None)
    kw.setdefault("his_games", set())
    kw.setdefault("set_names", {"עכו"})
    return {t.name: t.handler for t in build_plan_tools(draft, **kw)}


def test_the_builder_cannot_finish_under_the_time_budget_measured_from_his_sessions():
    draft = PlanDraft(measured={"practice": 0.5})  # he gets through a practice step in half a minute
    tools = tools_for(draft)
    tools["set_goal"]({"type": "name_retrieval", "description": "Names."})
    tools["set_opening"]({"recall": "", "opener": "מה שלומך?"})
    tools["place_names_game"]({})
    reply = tools["add_practice"](practice("כנרת"))
    assert reply["plan_minutes"] == round(0.6 + 1.0 + 0.5, 1) and reply["budget_minutes"] == BUDGET_MINUTES
    with pytest.raises(ValueError, match="add more steps"):
        tools["finish"]({})
    for i in range(7):
        tools["add_thread"](thread(f"topic {i}", "שאלה?"))
    assert tools["finish"]({"notes_applied": ""})["done"] is True
    plan = draft.to_plan()
    assert plan.steps[0].kind == "opening" and plan.estimated_minutes >= BUDGET_MINUTES


def test_the_tools_check_each_step_when_it_is_added():
    draft = PlanDraft()
    tools = tools_for(draft, check_practice=lambda step: "rejected: not in his data" if step.name == "דני" else None,
                      set_names=set())
    with pytest.raises(ValueError, match="not in his data"):
        tools["add_practice"](practice("דני"))
    tools["add_practice"](practice("כנרת"))
    with pytest.raises(ValueError, match="already in the plan"):
        tools["add_practice"](practice("כנרת"))
    with pytest.raises(ValueError, match="no names-game set"):
        tools["place_names_game"]({})
    with pytest.raises(ValueError, match="type must be one of"):
        tools["set_goal"]({"type": "intro", "description": "x"})
    assert "add_game_homework" not in tools  # no games app: no games tools


# ---- one mode: the session always runs as steps ---------------------------------------------

def tool_names():
    tools = FakeAuthTokens.last_config.live_connect_constraints.config.tools[0].function_declarations
    return [t.name for t in tools]


def instruction():
    return FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text


def test_every_session_runs_as_steps(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["agenda"]["kinds"] == ["opening", "practice", "practice", "activity", "thread"]  # no set: no game
    assert body["agenda"]["after"] == FOLLOW_UP
    assert body["start_note"].endswith(f"CURRENT STEP: {body['agenda']['steps'][0]}]")
    assert tool_names() == ["end_session", "next_step"]
    text = instruction()
    assert "## HOW THE SESSION WORKS" in text and "always a next step" in text and "1. opening" not in text
    assert "FIRST call next_step" in " ".join(text.split())
    for gone in ("איך נקרא כנרת?", "Practice items", "RESERVE -- use ONLY"):  # the steps come from the page
        assert gone not in text, gone
    sid = body["session_id"]
    saved = env.store.get_session(DAD, sid)
    assert [a["text"] for a in saved["agenda"]] == body["agenda"]["steps"] and saved["agenda_after"] == FOLLOW_UP
    # the steps she reported are saved with the session at the end
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye", "steps_done": [
        {"done": "Opening", "how_it_went": "He feels fine.", "at_s": 40.5}]})
    assert env.store.get_session(DAD, sid)["steps_done"] == [
        {"done": "Opening", "how_it_went": "He feels fine.", "at_s": 40.5}]
    # the caregiver page shows the next session's steps (exact texts), and the same prompt
    nxt = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["next_plan"]
    assert nxt["steps"][0]["text"].startswith("Opening") and nxt["steps_after"] == FOLLOW_UP
    assert "Steps:" in nxt["rendered"]
    prompt = env.client.get(f"/api/caregiver/{DAD}/next-prompt", headers=auth("tok-tomer")).json()["text"]
    assert "## HOW THE SESSION WORKS" in prompt


def test_step_lengths_are_measured_from_his_own_sessions():
    """12.10: a guessed pace factor got it backwards -- his long answers finished each step sooner.
    The builder's time budget uses how long each step kind really takes him (her step reports)."""
    from app.agent.next_class import step_minutes
    from app.store import InMemorySessionStore
    store = InMemorySessionStore()
    agenda = [{"kind": "opening"}, {"kind": "names_game"}, {"kind": "activity"}, {"kind": "practice"},
              {"kind": "thread"}]
    for version, reports in (("3.0", [32, 88, 208, 266, 280]), ("3.0", [30, 95, 200, 250, 270]),
                             ("1.16", [5, 10, 15, 20, 25])):  # before 3.0 she rushed: ignored
        sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version=version)
        store.update_session(DAD, sid, {"agenda": agenda, "steps_done": [{"done": "x", "at_s": a} for a in reports]})
    # the thread took ~0.3 min: she rushed -- planned as a real conversation (its 1-minute floor)
    assert step_minutes(store, DAD) == {"opening": 0.53, "names_game": 1.08, "activity": 2.0, "practice": 0.97,
                                         "thread": 1.0}
    assert step_minutes(InMemorySessionStore(), DAD) == {}  # no data: the defaults apply


def test_the_page_gets_how_many_answers_each_step_needs(env):
    """A talking step is a real short conversation: the page holds next_step until he has answered
    enough times in it (names game: its own questions; practice 2; a conversation topic 3)."""
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["agenda"]["min_answers"] == [1, 2, 2, 2, 3]  # opening, practice, practice, activity, thread
