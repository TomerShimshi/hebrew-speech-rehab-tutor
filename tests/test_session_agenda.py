"""13: the session as steps from TODAY'S PLAN, handed out by the page after each next_step call."""

from app.agenda import after_last, build_agenda, overview
from conftest import DAD, FakeAuthTokens, auth
from test_class_plan import a_plan


def practice_item(target):
    return {"target": target, "elicit": f"איפה {target}?", "hint_meaning": "m", "hint_first_syllable": "s",
            "sentence_completion": "c"}


PLAN = a_plan(probe=[{"target": "עכו", "kind": "untreated", "elicit": "העיר עם החומות?"},
                     {"target": "מצדה", "kind": "treated", "elicit": "המבצר ליד ים המלח?"}],
              practice=[practice_item("טבריה"), practice_item("צפת")],
              activity="Ask him to explain, step by step, how he plans a day trip.",
              reserve_practice=[practice_item("נהריה")],
              reserve_topics=["Ask what he cooks on Fridays."], conversation_topics=["his garden"])


def test_the_agenda_follows_the_plan_in_order():
    steps = build_agenda(PLAN)
    assert [(s["kind"], s["label"]) for s in steps] == [
        ("opening", ""), ("names_game", ""), ("practice", "טבריה"), ("practice", "צפת"),
        ("activity", ""), ("reserve", "נהריה"), ("thread", ""), ("thread", "")]
    game = steps[1]["text"]
    assert '1) "העיר עם החומות?" (answer: עכו) 2) "המבצר ליד ים המלח?" (answer: מצדה)' in game
    assert "NO hints" in game and "after his answer to the LAST question" in game
    assert 'ask "איפה טבריה?" (answer: טבריה)' in steps[2]["text"] and "Practice item 1 of 2" in steps[2]["text"]
    assert overview(steps) == ("Today's steps, in order: 1. opening, 2. names game, 3. practice (טבריה), "
                               "4. practice (צפת), 5. activity, 6. extra practice (נהריה), "
                               "7. conversation thread, 8. conversation thread.")
    assert steps[6]["text"].startswith("Conversation thread: Ask what he cooks on Fridays.")
    # after the planned steps: a follow-up step, again and again -- never "the steps are done"
    assert after_last(PLAN).startswith("Follow-up:") and "done" not in after_last(PLAN)


def test_without_a_plan_the_agenda_is_opening_and_his_topic():
    assert [s["kind"] for s in build_agenda(None)] == ["opening", "conversation"]


def test_todays_game_names_are_not_practiced_again_in_the_same_session():
    from app.class_plan import with_names_game
    from test_names_game import a_set
    plan = with_names_game(PLAN, a_set(("נהריה", "treated"), ("טבריה", "treated")))
    assert {p.target for p in plan.probe} == {"נהריה", "טבריה"}
    assert [p.target for p in plan.practice] == ["צפת"] and plan.reserve_practice == []


def set_steps_mode(env, on):
    assert env.client.put(f"/api/caregiver/{DAD}/settings", headers=auth("tok-tomer"),
                          json={"voice": {"steps_mode": on}}).status_code == 200


def tool_names():
    tools = FakeAuthTokens.last_config.live_connect_constraints.config.tools[0].function_declarations
    return [t.name for t in tools]


def instruction():
    return FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text


def test_steps_mode_is_off_by_default_and_changes_nothing(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["agenda"] is None and "CURRENT STEP" not in body["start_note"]
    assert tool_names() == ["end_session"] and "## WORKING STEP BY STEP" not in instruction()
    assert "agenda" not in env.store.get_session(DAD, body["session_id"])


def test_steps_mode_hands_the_page_the_agenda_and_her_the_first_step(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    set_steps_mode(env, True)
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert len(body["agenda"]["steps"]) == 7  # no names-game set: opening, 2 practice, activity, reserve, 2 threads
    assert body["agenda"]["steps"][0].startswith("Opening:") and body["agenda"]["after"].startswith("Follow-up:")
    assert body["start_note"].endswith(f"CURRENT STEP: {body['agenda']['steps'][0]}]")
    assert tool_names() == ["end_session", "next_step"]
    assert "## WORKING STEP BY STEP" in instruction() and "Today's steps, in order: 1. opening" in instruction()
    sid = body["session_id"]
    assert [a["kind"] for a in env.store.get_session(DAD, sid)["agenda"]] == [
        "opening", "practice", "practice", "activity", "reserve", "thread", "thread"]
    # the exact texts she got are saved with the session (13), for the caregiver page
    saved = env.store.get_session(DAD, sid)
    assert [a["text"] for a in saved["agenda"]] == body["agenda"]["steps"]
    assert saved["agenda_after"] == body["agenda"]["after"]
    # ...and the next session's steps are on the page before it happens
    nxt_plan = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["next_plan"]
    assert nxt_plan["steps_mode"] is True and nxt_plan["steps"][0]["text"].startswith("Opening:")
    assert nxt_plan["steps_after"].startswith("Follow-up:")
    # the steps she reported are saved with the session at the end
    env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye", "steps_done": [
        {"done": "Opening", "how_it_went": "He feels fine.", "at_s": 40.5}]})
    assert env.store.get_session(DAD, sid)["steps_done"] == [{"done": "Opening", "how_it_went": "He feels fine.", "at_s": 40.5}]
    # the caregiver page's "prompt for the next session" uses the same mode
    nxt = env.client.get(f"/api/caregiver/{DAD}/next-prompt", headers=auth("tok-tomer")).json()["text"]
    assert "## WORKING STEP BY STEP" in nxt


def test_in_steps_mode_her_prompt_has_no_questions_to_jump_ahead_to(env):
    """12.10: with the whole plan in her prompt she asked the next question on her own, then again
    from the step reply. In steps mode the questions come only from the page."""
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    env.client.post("/api/session/start", headers=auth())
    assert 'איפה טבריה?' in instruction()  # steps mode off: the full plan, as before
    set_steps_mode(env, True)
    body = env.client.post("/api/session/start", headers=auth()).json()
    text = instruction()
    assert "Main goal (name_retrieval)" in text and "Avoid: politics" in text  # the general parts stay
    for gone in ("איפה טבריה?", "Practice items", "RESERVE -- use ONLY", "Ask him to explain, step by step", "Conversation topics"):
        assert gone not in text, gone
    assert any("איפה טבריה?" in step for step in body["agenda"]["steps"])  # ...they come from the page


def test_steps_are_small_conversations_and_practice_comes_inside_a_topic():
    item = dict(practice_item("קוואלקום"), topic="his years at work")
    steps = build_agenda(a_plan(practice=[item], reserve_topics=["His ping-pong plans."]))
    practice = next(s["text"] for s in steps if s["kind"] == "practice")
    assert practice.startswith("Practice item 1 of 1, inside a short conversation: talk with him about his years at work")
    assert "After the name, one follow-up about it." in practice
    thread = next(s["text"] for s in steps if s["kind"] == "thread")
    assert "at least one follow-up on his own words" in thread


def test_the_page_gets_each_steps_kind_and_her_rules_say_call_first(env):
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", PLAN.model_dump(mode="json"))
    set_steps_mode(env, True)
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["agenda"]["kinds"] == ["opening", "practice", "practice", "activity", "reserve", "thread", "thread"]
    assert "FIRST call next_step" in " ".join(instruction().split())
    tool = next(t for t in FakeAuthTokens.last_config.live_connect_constraints.config.tools[0].function_declarations
                if t.name == "next_step")
    assert tool.behavior is None and "FIRST, before you say anything" in tool.description  # blocking, called first
