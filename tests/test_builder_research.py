import datetime as dt

from app import llm
from app.agent.next_class import build_next_plan
from app.config import Settings
from app.store import InMemorySessionStore
from fake_llm import FakeClient, client_error, text, tool_calls
from test_class_plan import a_plan

DAD = "dad.cohen@example.com"
NOW = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.timezone.utc)
QUESTION = "mild anomia for proper names; retrieval practice at home"
FOUND = {"status": "ok", "summary": "Retrieval practice helps.", "confidence": "high",
         "techniques": [{"name": "Spaced Retrieval", "how_to": "Ask again after longer gaps.",
                         "hebrew_example": "אתה זוכר איך קוראים לעיר?", "source_url": "https://www.asha.org/x",
                         "source_trusted": True}]}


def settings(**overrides):
    return Settings(**{"summary_model": "primary", "summary_fallback_models": "fallback",
                       "tavily_api_key": "KEY", **overrides})


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


class FakeResearch:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, store, client, settings, pid, question, *, personal, now, generate_fn):
        self.calls.append({"question": question, "personal": personal})
        return self.results.pop(0)


def setup():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "He lives in Haifa with his wife Rina.",
                                  "sections": {"personal_facts": ["Grandson named Noam"]}}, None)
    return store, store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")


def build(store, sid, client, research, **settings_overrides):
    return build_next_plan(store, client, settings(**settings_overrides), DAD, sid, generate_fn=gen,
                           now=NOW, today=NOW.date(), research_fn=research)


def test_research_result_reaches_the_plan_builder():
    store, sid = setup()
    research = FakeResearch(FOUND)
    client = FakeClient(tool_calls(("research_technique", {"question": QUESTION})), text("researched"),
                        text("{}", parsed=a_plan()))
    assert build(store, sid, client, research) == "done"
    assert research.calls[0]["question"] == QUESTION
    assert {"Haifa", "Rina", "Noam", "cohen"} <= research.calls[0]["personal"]
    plan_context = client.requests[-1]["contents"]
    assert "# RESEARCH FOR THIS PLAN (you asked: " + QUESTION in plan_context
    assert "Spaced Retrieval: Ask again after longer gaps." in plan_context
    assert "asha.org" not in plan_context  # the builder (and so the tutor) never gets sources
    saved = store.get_next_plan(DAD)["research"]
    assert saved == {"question": QUESTION, "status": "ok", "reason": None, "techniques": ["Spaced Retrieval"]}


def test_builder_may_decide_not_to_research():
    store, sid = setup()
    research = FakeResearch()
    client = FakeClient(text("no research needed: the techniques cover it"), text("{}", parsed=a_plan()))
    assert build(store, sid, client, research) == "done"
    assert research.calls == []
    assert store.get_next_plan(DAD)["research"] == {
        "question": None, "status": "not_needed", "reason": "no research needed: the techniques cover it", "techniques": []}
    assert "RESEARCH FOR THIS PLAN" not in client.requests[-1]["contents"]


def test_no_key_or_no_budget_means_no_research_phase():
    store, sid = setup()
    client = FakeClient(text("{}", parsed=a_plan()))
    assert build(store, sid, client, FakeResearch(), tavily_api_key="") == "done"
    assert len(client.requests) == 1  # just the plan call

    store, sid = setup()
    for _ in range(3):
        store.add_research_run(DAD, "2026-10-04")
    client = FakeClient(text("{}", parsed=a_plan()))
    assert build(store, sid, client, FakeResearch()) == "done" and len(client.requests) == 1


def test_only_one_research_run_per_plan_but_a_rejected_question_may_be_rewritten():
    store, sid = setup()
    research = FakeResearch({"status": "rejected", "message": "rewrite"}, FOUND)
    client = FakeClient(
        tool_calls(("research_technique", {"question": "names like Rina"})),
        tool_calls(("research_technique", {"question": QUESTION})),
        tool_calls(("research_technique", {"question": "another question"})),  # refused, then round limit
        text("{}", parsed=a_plan()),
    )
    assert build(store, sid, client, research) == "done"
    assert [c["question"] for c in research.calls] == ["names like Rina", QUESTION]
    assert store.get_next_plan(DAD)["research"]["status"] == "ok"


def test_research_failures_never_stop_the_plan():
    store, sid = setup()
    client = FakeClient(tool_calls(("research_technique", {"question": QUESTION})), text("done"),
                        text("{}", parsed=a_plan()))
    assert build(store, sid, client, FakeResearch({"status": "failed", "message": "x"})) == "done"
    assert "RESEARCH FOR THIS PLAN" not in client.requests[-1]["contents"]

    store, sid = setup()
    client = FakeClient(client_error(400), text("{}", parsed=a_plan()))  # the research phase call itself fails
    assert build(store, sid, client, FakeResearch()) == "done"
    assert store.get_next_plan(DAD)["research"] is None


def test_recent_notes_are_in_context_even_without_research():
    store, sid = setup()
    store.save_technique_note(DAD, "n1", {"question": QUESTION, "summary": "Retrieval practice helps.",
                                          "techniques": FOUND["techniques"]})
    client = FakeClient(text("{}", parsed=a_plan()))
    assert build(store, sid, client, FakeResearch(), tavily_api_key="") == "done"
    context = client.requests[0]["contents"]
    assert "# RESEARCH NOTES" in context and "- Q: " + QUESTION in context and "Spaced Retrieval" in context
