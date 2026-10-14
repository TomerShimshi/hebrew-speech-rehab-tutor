"""14: telling things in order -- scrambling, scoring and sizing in code; the step, the builder's
tool and its frequency rule; the memory agent's report; the caregiver page."""

import datetime as dt

import pytest

from app import llm, sequencing
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.memory_update import run_memory_update, sequencing_result
from app.agent.next_class import build_next_plan, sequencing_history
from app.agent.plan_tools import PlanDraft, build_plan_tools
from app.config import Settings
from app.schemas import ClassPlan, ConsolidatedMemory, MemorySections
from app.steps import SequencingStep
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from conftest import DAD
from fake_llm import FakeClient, text, tool_calls
from plan_helpers import SEQUENCE, a_plan, build_calls

SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


# ---- plain code: scrambling, scoring, sizing ------------------------------------------------------

@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_scrambling_is_never_the_original_the_reverse_or_close(n):
    for seed in ("a", "b", "gift", "doctor"):
        order = sequencing.scramble(n, seed)
        assert sorted(order) == list(range(1, n + 1))
        assert order not in (list(range(1, n + 1)), list(range(n, 0, -1)))
        assert sum(1 for a, b in zip(order, order[1:]) if b == a + 1) <= 1
    assert sequencing.scramble(5, "same story") == sequencing.scramble(5, "same story")  # stable for a plan


def test_score_counts_neighbouring_pairs_in_order_and_events_included():
    assert sequencing.score([1, 3, 2, 4, 5], 5) == {"order_pct": 75, "events_included": 5, "events": 5, "full": False}
    assert sequencing.score([1, 2, 3, 4], 4)["full"] is True
    assert sequencing.score([4, 3, 2, 1], 4)["order_pct"] == 0
    left_out = sequencing.score([1, 2, 4], 4)  # he skipped event 3: the order he told is still right
    assert (left_out["order_pct"], left_out["events_included"], left_out["full"]) == (100, 3, False)
    assert sequencing.score([1, 1, 9, 2], 4)["events_included"] == 2  # repeats and nonsense ignored


def test_the_task_grows_with_success_and_shrinks_when_hard():
    full = {"events": 4, "order_pct": 100, "full": True}
    assert sequencing.recommended_events([]) == 4
    assert sequencing.recommended_events([full, full]) == 5
    assert sequencing.recommended_events([{**full, "events": 6}, {**full, "events": 6}]) == 6  # the top
    assert sequencing.recommended_events([{"events": 4, "order_pct": 33, "full": False}]) == 3
    assert sequencing.recommended_events([{"events": 3, "order_pct": 0, "full": False}]) == 3  # the bottom
    assert sequencing.recommended_events([{"events": 5, "order_pct": 75, "full": False}, full]) == 5


# ---- the step and the builder's tool ----------------------------------------------------------

def test_her_step_has_both_orders_and_the_long_turn_rule():
    step = SequencingStep(**SEQUENCE, told_order=[3, 1, 4, 2])
    text_ = step.instruction()
    assert '1) "הוא יצא מהבית"' in text_ and "Say them to him in THIS scrambled order: 3, 1, 4, 2." in text_
    assert "the one long turn of the session" in text_ and "never the answer first" in text_
    retell = SequencingStep(task="retell", title="a bus ride", events=["א", "ב", "ג"])
    assert retell.instruction().startswith('Story retell (a bus ride): tell him this story, in this order: 1) "א"')


def test_the_scrambled_game_sends_cards_in_the_order_she_says_them_and_retell_none():
    from app.class_plan import session_steps
    plan = a_plan(steps=[{"kind": "opening"}, {"kind": "sequencing", **SEQUENCE, "told_order": [3, 1, 4, 2]}])
    steps = session_steps(plan)
    ev = SEQUENCE["events"]
    assert "cards" not in steps[0] and steps[1]["cards"] == [ev[2], ev[0], ev[3], ev[1]]
    assert "number them as you say them" in steps[1]["text"]
    retell = a_plan(steps=[{"kind": "sequencing", "task": "retell", "title": "t", "events": ["א", "ב", "ג"]}])
    assert all("cards" not in s for s in session_steps(retell))


def tools_for(draft, **kw):
    kw.setdefault("check_practice", lambda step: None)
    kw.setdefault("his_games", set())
    kw.setdefault("set_names", set())
    return {t.name: t.handler for t in build_plan_tools(draft, **kw)}


def test_the_tool_scrambles_checks_the_size_and_finish_requires_it_when_due():
    draft = PlanDraft()
    tools = tools_for(draft, seq_events=4, seq_task="scrambled")
    with pytest.raises(ValueError, match="recommends 4 events"):
        tools["add_sequencing"]({**SEQUENCE, "events": ["א", "ב", "ג", "ד", "ה", "ו"]})
    with pytest.raises(ValueError, match="this time the task is scrambled"):
        tools["add_sequencing"]({**SEQUENCE, "task": "retell"})
    tools["add_sequencing"](SEQUENCE)
    step = draft.steps[-1]
    assert step.told_order not in ([1, 2, 3, 4], [4, 3, 2, 1]) and sorted(step.told_order) == [1, 2, 3, 4]
    with pytest.raises(ValueError, match="one sequencing task per session"):
        tools["add_sequencing"](SEQUENCE)
    # required and missing -> finish refuses
    other = PlanDraft()
    tools = tools_for(other, seq_task="retell")
    tools["set_goal"]({"type": "discourse", "description": "Stories."})
    for i in range(10):
        tools["add_thread"]({"topic": f"t{i}", "question": "?"})
    with pytest.raises(ValueError, match="every plan has a sequencing task"):
        tools["finish"]({})


def test_no_thread_about_the_homework_the_opening_already_asks_it():
    tools = tools_for(PlanDraft())
    for topic in ("reviewing homework: two scenic spots", "מה עשית עם שיעורי הבית"):
        with pytest.raises(ValueError, match="already asks about the homework"):
            tools["add_thread"]({"topic": topic, "question": "?"})
    tools["add_thread"]({"topic": "table tennis", "question": "?"})


def session_with(store, sequencing_result_, plan_type="regular", days_ago=1):
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="3.0")
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    store.update_session(DAD, sid, {"started_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago),
                                    "class_plan": {"plan_type": plan_type}, "sequencing": sequencing_result_})
    return sid


def test_every_session_has_one_and_the_two_kinds_take_turns():
    store = InMemorySessionStore()
    assert sequencing_history(store, DAD) == ([], "scrambled")  # the first one: scrambled
    done = {"status": "done", "task": "scrambled", "events": 4, "order_pct": 100, "full": True}
    session_with(store, done, days_ago=3)
    assert sequencing_history(store, DAD)[1] == "retell"
    session_with(store, None, days_ago=2)  # a session without one: still the retell's turn
    assert sequencing_history(store, DAD)[1] == "retell"
    session_with(store, {"status": "skipped", "task": "retell"}, days_ago=1)
    results, task = sequencing_history(store, DAD)
    assert task == "scrambled" and len(results) == 1  # skipped: no score, but the turn passed


@pytest.mark.names_game_set
def test_the_builder_sees_his_sequencing_and_saves_the_scrambled_task():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.save_check_in_set(DAD, {"id": "x", "created_on": dt.date.today().isoformat(), "items": [
        {"target": "עכו", "question": "q", "kind": "untreated"}]})
    client = FakeClient(tool_calls(*build_calls()), text("done"))
    assert build_next_plan(store, client, SETTINGS, DAD, sid, generate_fn=gen) == "done"
    context = client.requests[0]["contents"][0].parts[0].text
    assert "# HIS SEQUENCING" in context and "REQUIRED in every plan" in context and "task=scrambled" in context and "4 events" in context
    seq = [s for s in store.get_next_plan(DAD)["steps"] if s["kind"] == "sequencing"][0]
    assert seq["events"] == SEQUENCE["events"] and len(seq["told_order"]) == 4


# ---- the memory agent reports, code scores --------------------------------------------------------

def test_the_score_is_computed_by_code_from_the_order_he_told():
    plan = a_plan(steps=[{"kind": "opening"}, {"kind": "sequencing", **SEQUENCE, "told_order": [3, 1, 4, 2]}])
    draft = MemoryDraft(sections=MemorySections(), word_bank={}, today=dt.date(2026, 10, 13))
    tools = {t.name: t.handler for t in build_memory_tools(draft)}
    tools["record_sequencing"]({"told_order": [1, 2, 4, 3], "needed_help": True, "note": "Swapped the last two."})
    result = sequencing_result(plan, draft.sequencing)
    assert (result["status"], result["order_pct"], result["events_included"], result["needed_help"]) == (
        "done", 67, 4, True)
    assert sequencing_result(plan, {"skipped": True, "note": "tired"})["status"] == "skipped"
    assert sequencing_result(plan, None)["status"] == "not_reported"
    assert sequencing_result(a_plan(steps=[{"kind": "opening"}]), draft.sequencing) is None  # no task: nothing
    with pytest.raises(ValueError):
        tools["record_sequencing"]({"told_order": "1,2,3"})


def test_memory_update_saves_the_sessions_sequencing():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    plan = a_plan(steps=[{"kind": "opening"}, {"kind": "sequencing", **SEQUENCE, "told_order": [3, 1, 4, 2]}])
    store.update_session(DAD, sid, {"class_plan": plan.model_dump(mode="json")})
    store.upsert_turns(DAD, sid, [TurnIn(seq=i, speaker=sp, text=tx, t_start_s=i * 10) for i, (sp, tx) in enumerate([
        ("tutor", "אספר לך כמה דברים שקרו, אבל בבלגן..."),
        ("patient", "קודם הוא יצא מהבית, נכנס לחנות, בחר מתנה ושילם"),
        ("tutor", "קרה לך פעם משהו כזה?"), ("patient", "כן, קניתי מתנה לנכד")])])
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    client = FakeClient(tool_calls(("record_sequencing", {"told_order": [1, 2, 3, 4], "needed_help": False})),
                        text("done"), text("{}", parsed=ConsolidatedMemory(memory_prompt="m", focus_next_session=[])))
    assert run_memory_update(store, client, SETTINGS, DAD, sid, generate_fn=gen) == "done"
    seq = store.get_session(DAD, sid)["sequencing"]
    assert (seq["status"], seq["order_pct"], seq["full"], seq["title"]) == ("done", 100, True, "buying a gift")
    assert "Say them to him in THIS scrambled order: 3, 1, 4, 2." in client.requests[0]["contents"][0].parts[0].text


def test_a_missing_sequencing_report_gets_one_extra_round():
    store = InMemorySessionStore()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    plan = a_plan(steps=[{"kind": "opening"}, {"kind": "sequencing", **SEQUENCE, "told_order": [3, 1, 4, 2]}])
    store.update_session(DAD, sid, {"class_plan": plan.model_dump(mode="json")})
    store.upsert_turns(DAD, sid, [TurnIn(seq=i, speaker="patient", text=tx, t_start_s=i * 10) for i, tx in enumerate(
        ["קודם הוא יצא מהבית, נכנס לחנות, בחר מתנה ושילם", "כן, קניתי מתנה לנכד", "היה נחמד"])])
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    client = FakeClient(text("done"),  # the first loop forgets it
                        tool_calls(("record_sequencing", {"told_order": [1, 2, 3, 4]})), text("ok"),
                        text("{}", parsed=ConsolidatedMemory(memory_prompt="m", focus_next_session=[])))
    run_memory_update(store, client, SETTINGS, DAD, sid, generate_fn=gen)
    assert "YOU MISSED ONE" in str(client.requests[1]["config"])
    assert store.get_session(DAD, sid)["sequencing"]["status"] == "done"


def test_the_progress_page_has_a_sequencing_series():
    from app.caregiver_api import progress_series
    data = progress_series([{"started_at": dt.datetime(2026, 10, 13), "sequencing": {
        "status": "done", "task": "retell", "order_pct": 75, "events": 5}}], {})
    assert (data["points"][0]["sequencing"], data["points"][0]["sequencing_task"]) == (75, "retell")
