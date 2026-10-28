"""Traces (sub-plan 19): what the spans hold, the cost estimate, and that tracing never breaks a job."""

from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import llm, telemetry
from app.agent.runner import Tool, run_tool_loop
from conftest import DAD, auth
from fake_llm import FakeClient, text, tool_calls
from test_memory_wiring import consolidated, plan_reply, talk


@pytest.fixture
def spans(capsys):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.use(provider, "test-project")
    llm.reset_cooldowns()
    yield exporter
    telemetry.use(None, "")


def by_name(exporter, name):
    return [s for s in exporter.get_finished_spans() if s.name == name]


def with_usage(response, prompt=1000, out=200, thinking=50):
    response.usage_metadata = SimpleNamespace(prompt_token_count=prompt, candidates_token_count=out,
                                              thoughts_token_count=thinking, cached_content_token_count=0)
    return response


# ---- pieces ----------------------------------------------------------------------------------

def test_text_is_cut_by_bytes_hebrew_counts_twice():
    assert telemetry.text("שלום", limit=100) == "שלום"
    cut = telemetry.text("א" * 1000, limit=200)
    assert len(cut.encode("utf-8")) <= 200 and "[cut: 2000 bytes]" in cut


def test_cost_known_model_and_default():
    assert telemetry.cost_usd("gemini-3.8-flash", 1_000_000, 1_000_000) == (4.5, "gemini-3.8-flash")
    assert telemetry.cost_usd("some-new-model", 1_000_000, 0) == (0.75, "default")


def test_live_cost_prices_audio_by_the_minute():
    one_min = telemetry.AUDIO_TOKENS_PER_MIN
    usage = {"prompt_tokens": one_min, "response_tokens": one_min, "audio_in_tokens": one_min, "audio_out_tokens": one_min}
    assert telemetry.live_cost_usd(usage) == pytest.approx(0.005 + 0.018)


def test_off_by_default_nothing_recorded(capsys):
    assert not telemetry.enabled()
    llm.generate(FakeClient(text("hi")), ["m"], "x", sleep=lambda s: None)
    assert capsys.readouterr().out == ""  # no log lines either


# ---- model calls and tool loops ---------------------------------------------------------------

def test_a_model_call_span_has_model_tokens_cost_and_content(spans, capsys):
    llm.generate(FakeClient(with_usage(text("שלום לך"))), ["gemini-3.8-flash"], "הקלט", sleep=lambda s: None)
    (s,) = by_name(spans, "generate_content")
    a = s.attributes
    assert a["gen_ai.response.model"] == "gemini-3.8-flash"
    assert (a["gen_ai.usage.input_tokens"], a["gen_ai.usage.output_tokens"], a["app.tokens.thinking"]) == (1000, 200, 50)
    assert a["app.cost_usd"] == pytest.approx((1000 * 0.75 + 250 * 3.75) / 1e6)
    assert a["app.output.text"] == "שלום לך"
    (event,) = [e for e in s.events if e.name == telemetry.GENAI_EVENT]
    assert "הקלט" in event.attributes["gen_ai.input.messages"]
    out = capsys.readouterr().out
    assert '"event": "llm_call"' in out and '"event": "llm_content"' in out
    assert f"traces/{s.context.trace_id:032x}" in out  # linked to the span


def test_a_fallback_is_an_event_on_the_same_span(spans):
    from fake_llm import server_error
    llm.generate(FakeClient(server_error(503), with_usage(text("ok"))), ["primary", "fallback"], "x", sleep=lambda s: None)
    (s,) = by_name(spans, "generate_content")
    assert s.attributes["app.models_tried"] == "primary,fallback" and s.attributes["app.attempts"] == 2
    assert [e.name for e in s.events] == ["attempt failed", telemetry.GENAI_EVENT]


def test_the_tool_loop_has_a_span_per_round_and_per_tool(spans):
    tool = Tool("note", "", {"type": "object"}, lambda args: {"saved": args["x"]})
    run_tool_loop(FakeClient(with_usage(tool_calls(("note", {"x": "א"}))), with_usage(text("done"))),
                  ["m"], "system", "user", [tool])
    assert [s.name for s in spans.get_finished_spans()] == [
        "generate_content", "tool note", "round 1", "generate_content", "round 2"]
    (t,) = by_name(spans, "tool note")
    assert t.attributes["app.tool.ok"] is True and '"saved": "א"' in t.attributes["app.tool.result"]
    r1 = by_name(spans, "round 1")[0]
    assert t.parent.span_id == r1.context.span_id and r1.attributes["app.tools_called"] == "note"
    # each round shows what it cost (19: the totals on every span)
    assert r1.attributes["app.total.llm_calls"] == 1
    assert r1.attributes["app.total.cost_usd"] == pytest.approx((1000 * 0.75 + 250 * 3.75) / 1e6)


def test_the_input_outputs_event_holds_the_conversation(spans):
    import json
    tool = Tool("note", "", {"type": "object"}, lambda args: {"saved": args["x"]})
    run_tool_loop(FakeClient(with_usage(tool_calls(("note", {"x": "א"}))), with_usage(text("done"))),
                  ["m"], "the system prompt", "the user", [tool])
    second = by_name(spans, "generate_content")[1]
    (event,) = [e for e in second.events if e.name == telemetry.GENAI_EVENT]
    messages = json.loads(event.attributes["gen_ai.input.messages"])
    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    assert messages[1]["parts"][0] == {"type": "tool_call", "id": "c0", "name": "note", "arguments": {"x": "א"}}
    assert messages[2]["parts"][0]["type"] == "tool_call_response"
    assert json.loads(event.attributes["gen_ai.system_instructions"]) == [{"type": "text", "content": "the system prompt"}]
    assert json.loads(event.attributes["gen_ai.output.messages"])[0]["parts"] == [{"type": "text", "content": "done"}]


def test_fit_json_stays_valid_json_under_the_limit():
    import json
    big = [{"role": "user", "parts": [{"type": "text", "content": "א" * 50_000}, {"type": "text", "content": "short"}]}]
    out = telemetry.fit_json(big, limit=20_000)
    assert len(out.encode("utf-8")) <= 20_000
    parsed = json.loads(out)
    assert parsed[0]["parts"][1]["content"] == "short" and "[cut:" in parsed[0]["parts"][0]["content"]


def test_each_agent_is_its_own_trace_with_its_own_log(spans, monkeypatch):
    sent = []

    class FakeSession:
        def post(self, url, json, timeout):
            sent.extend(json["entries"])
            return SimpleNamespace(status_code=200, text="")

    monkeypatch.setitem(telemetry._state, "log_session", FakeSession())
    monkeypatch.setitem(telemetry._state, "resource", {"type": "global"})
    clock = iter(range(1000))
    monkeypatch.setattr(telemetry, "_now", lambda: f"t{next(clock):03d}")

    @telemetry.job("research")
    def research(pid, sid):
        llm.generate(FakeClient(with_usage(text("found"))), ["m"], "q", sleep=lambda s: None)

    @telemetry.job("next_plan")
    def build(pid, sid):
        telemetry.note("[next_class] building")
        research(pid, sid)
        return "done"

    @telemetry.job("memory_update")
    def update(pid, sid):
        llm.generate(FakeClient(with_usage(text("ok"))), ["m"], "x", sleep=lambda s: None)
        return "done"

    with telemetry.span("request session end"):  # one request runs both agents
        update("a@b.c", "s1")
        build("a@b.c", "s1")
    memory, plan = by_name(spans, "memory-agent")[0], by_name(spans, "plan-builder")[0]
    # each agent is a root of its own trace (linked to the request), not inside the other's
    assert memory.parent is None and plan.parent is None and memory.context.trace_id != plan.context.trace_id
    assert memory.links and memory.attributes["app.total.llm_calls"] == 1
    # everything under an agent is named after it; research is inside the plan builder
    (inner,) = by_name(spans, "plan-builder: research")
    assert inner.parent.span_id == plan.context.span_id
    assert by_name(spans, "memory-agent: generate_content") and by_name(spans, "plan-builder: research generate_content")
    assert plan.attributes["app.total.llm_calls"] == 1  # research's call counts for the plan builder
    # a log per agent, labelled, linked to the spans; the agent's own lines are in it
    logs = {e["logName"].rsplit("/", 1)[-1] for e in sent}
    assert logs == {"memory-agent", "plan-builder"}
    assert all(e["labels"]["agent"] in ("memory-agent", "plan-builder") and e["trace"] for e in sent)
    assert any(e["jsonPayload"]["event"] == "note" and "building" in e["jsonPayload"]["text"] for e in sent)
    # whose: every span and every log entry, so one user's traces and logs can be filtered
    assert all(s.attributes.get("app.account") == "a@b.c" for s in spans.get_finished_spans()
               if s.name != "request session end")
    assert {e["labels"]["account"] for e in sent} == {"a@b.c"}
    # each entry keeps the time it happened, not the time the buffer was written
    times = [e["timestamp"] for e in sent]
    assert all(times) and times == sorted(times) and len(set(times)) > 1


def test_end_traces_each_agent_and_the_tutor(env, spans):
    env.llm = FakeClient(consolidated("He talked."), text("nothing to add"), *plan_reply())
    env.configure()
    env.store.save_profile(DAD, "Man, 70.", "uploaded", "tomer@example.com")
    sid = talk(env)
    live = {"prompt_tokens": 5000, "response_tokens": 3000, "audio_in_tokens": 4000, "audio_out_tokens": 2500,
            "usage_reports": 12, "max_report_total": 900, "response_ms": [800, 1200, 2000], "reconnects": 1}
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={
        "reason": "tutor_goodbye", "live": live,
        "steps_done": [{"done": "opening", "how_it_went": "ok", "at_s": 6}],
        "steps_held": [{"step": 1, "reason": "question", "at_s": 10}]})
    assert r.json()["memory_status"] == "done"
    roots = {s.name for s in spans.get_finished_spans() if s.parent is None}
    assert roots == {"tutor", "memory-agent", "plan-builder"}
    tutor = by_name(spans, "tutor")[0]
    assert tutor.attributes["app.response_ms.p50"] == 1200 and tutor.attributes["app.total.cost_usd"] > 0
    assert [e.name for e in tutor.events] == [telemetry.GENAI_EVENT, "next_step held (question)"]
    step1, step2 = by_name(spans, "tutor: step 1: opening")[0], [s for s in spans.get_finished_spans()
                                                                 if s.name.startswith("tutor: step 2")][0]
    turns = [s for s in spans.get_finished_spans() if s.name in ("tutor: her", "tutor: him")]
    assert len(turns) == 4  # the conversation, each turn under its step
    assert [t.parent.span_id for t in turns] == [step1.context.span_id] * 2 + [step2.context.span_id] * 2
    assert turns[1].attributes["app.turn.text"] == "על הנכדים"
    assert {s.attributes.get("app.account") for s in [tutor, step1, step2, *turns]} == {DAD}


def test_end_without_live_stats_still_works(env, spans):
    env.llm = FakeClient(consolidated("He talked."), text("nothing to add"), *plan_reply())
    env.configure()
    sid = talk(env)
    assert env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "end_button"}).status_code == 200
    assert not by_name(spans, "live session")
