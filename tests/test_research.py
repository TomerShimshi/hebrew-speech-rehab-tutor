import datetime as dt

from app import llm
from app.agent.research import note_id, personal_terms, research_technique
from app.config import Settings
from app.research_sources import TavilyUnavailable
from app.schemas import Confidence, ResearchFindings, Technique
from app.store import InMemorySessionStore
from fake_llm import FakeClient, text, tool_calls

PID = "dad@example.com"
NOW = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.timezone.utc)
QUESTION = "mild anomia for proper names in a fluent speaker; retrieval practice at home"
SFA_URL = "https://www.asha.org/practice-portal/aphasia/"
BLOG_URL = "https://blog.example/aphasia-tips"


def settings(**overrides):
    fields = dict(summary_model="primary", summary_fallback_models="fallback", tavily_api_key="KEY",
                  research_daily_limit=3, research_monthly_limit=800, research_max_searches=3)
    return Settings(**{**fields, **overrides})


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


class FakeSearch:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, api_key, query, scope="trusted"):
        self.calls.append({"query": query, "scope": scope})
        if self.error:
            raise self.error
        if scope == "open":
            return [{"title": "Tips", "url": BLOG_URL, "content": "practice naming", "trusted": False}]
        return [{"title": "SFA", "url": SFA_URL, "content": "Semantic feature analysis...", "trusted": True}]


def technique(name="Semantic Feature Analysis", url=SFA_URL, how_to="Describe features of the item, then name it."):
    return Technique(name=name, how_to=how_to, hebrew_example="במה משתמשים בזה?", source_url=url)


def findings(*techniques, summary="SFA helps naming."):
    f = ResearchFindings(summary=summary, techniques=list(techniques), confidence=Confidence.medium)
    return text(f.model_dump_json(), parsed=f)


def run(client, store=None, search=None, question=QUESTION, personal=frozenset({"Rina"}), **settings_overrides):
    store = store or InMemorySessionStore()
    search = search or FakeSearch()
    out = research_technique(store, client, settings(**settings_overrides), PID, question,
                             personal=set(personal), now=NOW, generate_fn=gen, search_fn=search)
    return out, store, search


def test_finds_and_keeps_sourced_techniques():
    client = FakeClient(
        tool_calls(("web_search", {"query": "semantic feature analysis anomia"})),
        tool_calls(("web_search", {"query": "word finding home exercises", "scope": "open"})),
        text("done"),
        findings(technique(), technique("Naming practice", url=BLOG_URL + "/")),  # trailing / still matches
    )
    out, store, search = run(client)
    assert out["status"] == "ok"
    assert [(t["name"], t["source_trusted"]) for t in out["techniques"]] == [
        ("Semantic Feature Analysis", True), ("Naming practice", False)]
    assert out["techniques"][1]["source_url"] == BLOG_URL
    assert [c["scope"] for c in search.calls] == ["trusted", "open"]
    note = store.get_technique_note(PID, note_id(QUESTION))
    assert note["queries"][0] == {"query": "semantic feature analysis anomia", "scope": "trusted", "provider": "tavily"}
    assert store.searches_in_month("2026-10") == 2 and store.research_runs_on(PID, "2026-10-04") == 1
    # the findings call sees the search results, the question, and nothing else
    findings_input = client.requests[-1]["contents"]
    assert SFA_URL in findings_input and QUESTION in findings_input


def test_invented_sources_and_medical_techniques_are_dropped():
    client = FakeClient(
        tool_calls(("web_search", {"query": "anomia treatment"})),
        text("done"),
        findings(technique(),
                 technique("Made-up method", url="https://pubmed.ncbi.nlm.nih.gov/99999999/"),
                 technique("tDCS-assisted naming", how_to="Combine naming with brain stimulation."),
                 summary="SFA helps naming. tDCS may boost it."),
    )
    out, store, _ = run(client)
    assert [t["name"] for t in out["techniques"]] == ["Semantic Feature Analysis"]
    assert out["summary"] == "SFA helps naming."
    assert store.get_technique_note(PID, note_id(QUESTION))["dropped"] == {"unsourced": 1, "medical": 1, "over_limit": 0}


def test_nothing_sourced_means_no_findings_and_no_cache():
    client = FakeClient(tool_calls(("web_search", {"query": "anomia treatment"})), text("done"),
                        findings(technique(url="https://invented.example/")))
    out, store, _ = run(client)
    assert out["status"] == "no_findings" and out["techniques"] == []
    assert store.technique_notes == {}


def test_personal_question_is_rejected_before_any_call():
    client = FakeClient()
    out, store, search = run(client, question="how to help Rina's husband name places")
    assert out["status"] == "rejected" and search.calls == [] and client.requests == []
    out, _, _ = run(FakeClient(), question="anomia for names like חיפה")
    assert out["status"] == "rejected"
    assert store.research_runs_on(PID, "2026-10-04") == 0


def test_personal_or_hebrew_queries_never_reach_tavily():
    client = FakeClient(
        tool_calls(("web_search", {"query": "name practice for Rina"})),
        tool_calls(("web_search", {"query": "שיום שמות"})),
        tool_calls(("web_search", {"query": "proper name anomia"})),
        text("done"),
        findings(technique()),
    )
    out, _, search = run(client)
    assert [c["query"] for c in search.calls] == ["proper name anomia"]
    assert out["status"] == "ok"


def test_search_limits_per_run():
    client = FakeClient(
        tool_calls(("web_search", {"query": "a b c", "scope": "open"})),
        tool_calls(("web_search", {"query": "d e f", "scope": "open"})),  # 2nd open: refused
        tool_calls(("web_search", {"query": "g h i"}), ("web_search", {"query": "j k l"})),
        tool_calls(("web_search", {"query": "m n o"})),  # 4th search: refused
        text("done"),
        findings(technique()),
    )
    _, store, search = run(client)
    assert [c["query"] for c in search.calls] == ["a b c", "g h i", "j k l"]
    assert store.searches_in_month("2026-10") == 3


def test_cache_hit_skips_searching_and_expires_after_30_days():
    store = InMemorySessionStore()
    run(FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"), findings(technique())), store=store)
    out, _, search = run(FakeClient(), store=store, question="  Mild anomia for proper names in a fluent speaker; "
                                                                "retrieval practice at home ")
    assert out["status"] == "cached" and search.calls == []
    store.technique_notes[(PID, note_id(QUESTION))]["created_at"] = NOW - dt.timedelta(days=31)
    out, _, search = run(FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"),
                                    findings(technique())), store=store)
    assert out["status"] == "ok" and len(search.calls) == 1


def test_daily_and_monthly_limits_and_missing_key():
    store = InMemorySessionStore()
    for _ in range(3):
        store.add_research_run(PID, "2026-10-04")
    out, _, search = run(FakeClient(), store=store)
    assert out["status"] == "budget" and search.calls == []

    store = InMemorySessionStore()
    for _ in range(800):
        store.add_search("2026-10")
    assert run(FakeClient(), store=store)[0]["status"] == "unavailable"
    assert run(FakeClient(), tavily_api_key="")[0]["status"] == "unavailable"


def test_tavily_quota_error_stops_research():
    client = FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"))
    out, _, _ = run(client, search=FakeSearch(error=TavilyUnavailable("tavily HTTP 432")))
    assert out["status"] == "unavailable"


def test_never_raises():
    client = FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"), text("not json"))
    out, store, _ = run(client)
    assert out["status"] == "failed" and store.technique_notes == {}


def test_personal_terms_from_memory_and_profile():
    memory = {"memory_prompt": "He lives in Haifa with his wife Rina. Hebrew is his first language.",
              "sections": {"personal_facts": ["Grandson named Noam; trips to the Galilee"]},
              "focus_next_session": ["Practice names of places he visited, like Tiberias"]}
    terms = personal_terms(memory, "Name: efraim. Speaks Hebrew and Russian.", extra=("dad.cohen@example.com", "efraim"))
    assert {"Haifa", "Rina", "Noam", "Galilee", "Tiberias", "cohen", "efraim"} <= terms
    assert not {"Hebrew", "Russian", "He", "Grandson", "Practice", "Name"} & terms



# ---- 10: Gemini + Google Search when Tavily is unavailable ---------------------------------------

class FakeGeminiSearch:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, client, models, query, scope="trusted", *, generate_fn):
        from app.research_sources import SearchUnavailable
        self.calls.append({"query": query, "scope": scope})
        if self.error:
            raise SearchUnavailable(self.error)
        return [{"title": "asha.org", "url": SFA_URL, "content": "Semantic feature analysis...", "trusted": True}]


def run_with_fallback(client, store=None, search=None, gemini=None, **settings_overrides):
    store = store or InMemorySessionStore()
    search, gemini = search or FakeSearch(), gemini or FakeGeminiSearch()
    out = research_technique(store, client, settings(gemini_search_enabled=True, **settings_overrides), PID, QUESTION,
                             personal={"Rina"}, now=NOW, generate_fn=gen, search_fn=search, gemini_search_fn=gemini)
    return out, store, search, gemini


def test_tavily_quota_error_falls_back_to_gemini_search_for_the_same_query():
    client = FakeClient(tool_calls(("web_search", {"query": "semantic feature analysis"})), text("done"), findings(technique()))
    out, store, search, gemini = run_with_fallback(client, search=FakeSearch(error=TavilyUnavailable("tavily HTTP 432")))
    assert out["status"] == "ok" and [t["name"] for t in out["techniques"]] == ["Semantic Feature Analysis"]
    assert [c["query"] for c in gemini.calls] == ["semantic feature analysis"]  # the same query, not lost
    note = store.get_technique_note(PID, note_id(QUESTION))
    assert note["queries"][0]["provider"] == "gemini"
    assert (store.searches_in_month("2026-10", "tavily"), store.searches_in_month("2026-10", "gemini")) == (1, 1)


def test_no_tavily_key_goes_straight_to_gemini_search():
    client = FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"), findings(technique()))
    out, store, search, gemini = run_with_fallback(client, tavily_api_key="")
    assert out["status"] == "ok" and search.calls == [] and len(gemini.calls) == 1


def test_the_fallback_keeps_the_guardrails():
    client = FakeClient(tool_calls(("web_search", {"query": "names like Rina"})),
                        tool_calls(("web_search", {"query": "anomia"})), text("done"),
                        findings(technique(), technique("Invented", url="https://made-up.example/")))
    out, _, _, gemini = run_with_fallback(client, tavily_api_key="")
    assert [c["query"] for c in gemini.calls] == ["anomia"]  # personal query blocked before any search
    assert [t["name"] for t in out["techniques"]] == ["Semantic Feature Analysis"]  # unsourced one dropped


def test_both_providers_unavailable():
    client = FakeClient(tool_calls(("web_search", {"query": "anomia"})), text("done"))
    out, *_ = run_with_fallback(client, tavily_api_key="", gemini=FakeGeminiSearch(error="429 no grounding quota"))
    assert out["status"] == "unavailable"
    store = InMemorySessionStore()
    for _ in range(3):
        store.add_search("2026-10", "gemini")
    out, *_ = run_with_fallback(FakeClient(), store=store, tavily_api_key="", gemini_search_monthly_limit=3)
    assert out["status"] == "unavailable"  # the fallback's own monthly line
