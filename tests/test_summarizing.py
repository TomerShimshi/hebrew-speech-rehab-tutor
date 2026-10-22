"""17: summarizing a short text in his own words -- scored and sized by code; it takes turns with the
sequencing task; the memory agent reports which main ideas he conveyed."""
import datetime as dt

import pytest

from app import summarizing
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.memory_update import summarizing_result
from app.agent.next_class import discourse_turn
from app.agent.plan_tools import PlanDraft, build_plan_tools
from app.schemas import MemorySections
from app.steps import SummaryStep
from app.store import InMemorySessionStore
from app.transcripts import EndReason
from conftest import DAD
from plan_helpers import a_plan

SUMMARY = {"title": "a new train line", "paragraph": "נפתח קו רכבת חדש בצפון. הוא מחבר שתי ערים. הנסיעה קצרה יותר. "
           "הכרטיס זול.", "main_ideas": ["A new train line opened up north", "It links two towns",
                                          "The ride is shorter", "The ticket is cheap"]}


def test_score_and_size():
    assert summarizing.score([1, 2, 4], 4) == {"ideas_pct": 75, "ideas_conveyed": 3, "ideas": 4, "full": False}
    assert summarizing.score([1, 1, 9], 4)["ideas_conveyed"] == 1  # repeats and nonsense ignored
    full = {"ideas": 4, "ideas_pct": 100, "full": True}
    assert summarizing.recommended_ideas([]) == 4
    assert summarizing.recommended_ideas([full, full]) == 5
    assert summarizing.recommended_ideas([{"ideas": 4, "ideas_pct": 25, "full": False}]) == 3


def tools_for(draft, **kw):
    return {t.name: t.handler for t in build_plan_tools(draft, check_practice=lambda s: None, his_games=set(),
                                                        set_names=set(), **kw)}


def test_the_summary_tool_checks_size_and_turn():
    draft = PlanDraft()
    tools = tools_for(draft, summary_ideas=4, discourse="summary")
    with pytest.raises(ValueError, match="recommends 4 main ideas"):
        tools["add_summary"]({**SUMMARY, "main_ideas": SUMMARY["main_ideas"] + ["a", "b"]})
    with pytest.raises(ValueError, match="not a sequencing task"):
        tools["add_sequencing"]({"task": "scrambled", "title": "t", "events": ["א", "ב", "ג", "ד"]})
    tools["add_summary"](SUMMARY)
    assert isinstance(draft.steps[-1], SummaryStep) and "ITEMS" not in draft.steps[-1].instruction()
    assert 'read him this paragraph: "נפתח קו רכבת חדש' in draft.steps[-1].instruction()
    with pytest.raises(ValueError, match="one summary per session"):
        tools["add_summary"](SUMMARY)
    other = PlanDraft()
    seq_turn = tools_for(other, discourse="sequencing", seq_task="scrambled")
    with pytest.raises(ValueError, match="not a summary"):
        seq_turn["add_summary"](SUMMARY)


def test_finish_requires_the_summary_on_its_turn():
    draft = PlanDraft()
    tools = tools_for(draft, discourse="summary")
    tools["set_goal"]({"type": "discourse", "description": "Telling."})
    for i in range(10):
        tools["add_thread"]({"topic": f"t{i}", "question": "?"})
    with pytest.raises(ValueError, match="add_summary"):
        tools["finish"]({})


def ended(store, field, value, days_ago):
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"class_plan": {"plan_type": "regular"}, field: value,
                                    "started_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)})
    store.end_session(DAD, sid, EndReason.tutor_goodbye)


def test_the_two_take_turns():
    store = InMemorySessionStore()
    assert discourse_turn(store, DAD) == "sequencing"
    ended(store, "sequencing", {"status": "done", "task": "scrambled"}, 2)
    assert discourse_turn(store, DAD) == "summary"
    ended(store, "summarizing", {"status": "skipped"}, 1)
    assert discourse_turn(store, DAD) == "sequencing"


def test_the_memory_agent_reports_and_code_scores():
    plan = a_plan(steps=[{"kind": "opening"}, {"kind": "summary", **SUMMARY}])
    draft = MemoryDraft(sections=MemorySections(), word_bank={}, today=dt.date(2026, 10, 21))
    tools = {t.name: t.handler for t in build_memory_tools(draft)}
    tools["record_summary"]({"conveyed": [1, 3, 4], "needed_help": False, "note": "Left out the two towns."})
    result = summarizing_result(plan, draft.summarizing)
    assert (result["status"], result["ideas_pct"], result["ideas_conveyed"]) == ("done", 75, 3)
    assert summarizing_result(plan, None)["status"] == "not_reported"
    assert summarizing_result(a_plan(steps=[{"kind": "opening"}]), draft.summarizing) is None
