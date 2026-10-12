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
    assert "HOW: A short conversation about the topic" in text and "After the name, one follow-up" in text
    assert "follow-up on his own words" in ThreadStep(**thread()).instruction()
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
    # kinds only: with the names in it she guessed the next question and asked it early (12.10)
    assert overview(session_steps(PLAN)) == ("Today's steps, in order: 1. opening, 2. names game, 3. practice, "
                                             "4. practice, 5. activity, 6. conversation thread.")
    assert all(s["text"].endswith("never right after you asked something.") for s in session_steps(PLAN))


# ---- the plan builder's tools ----------------------------------------------------------------

def tools_for(draft, **kw):
    kw.setdefault("check_practice", lambda step: None)
    kw.setdefault("his_games", set())
    kw.setdefault("set_names", {"עכו"})
    return {t.name: t.handler for t in build_plan_tools(draft, **kw)}


def test_the_builder_cannot_finish_under_the_time_budget_and_a_fast_talker_needs_more():
    draft = PlanDraft(pace_factor=0.8)  # FAST
    tools = tools_for(draft)
    tools["set_goal"]({"type": "name_retrieval", "description": "Names."})
    tools["set_opening"]({"recall": "", "opener": "מה שלומך?"})
    tools["place_names_game"]({})
    reply = tools["add_practice"](practice("כנרת"))
    assert reply["plan_minutes"] == round((1 + 1.5 + 1.25) * 0.8, 1) and reply["budget_minutes"] == BUDGET_MINUTES
    with pytest.raises(ValueError, match="add more steps"):
        tools["finish"]({})
    for i in range(6):
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
    assert "## HOW THE SESSION WORKS" in text and "Today's steps, in order: 1. opening" in text
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
