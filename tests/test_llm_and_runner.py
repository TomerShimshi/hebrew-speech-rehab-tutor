import pytest

from app import llm
from app.agent.runner import Tool, run_tool_loop
from fake_llm import FakeClient, client_error, server_error, text, tool_calls

MODELS = ["primary", "fallback"]
no_sleep = lambda s: None  # noqa: E731


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=no_sleep)


# ---- llm.generate: retries + fallback -------------------------------------------------

def test_first_try_success():
    client = FakeClient(text("hi"))
    result = gen(client, MODELS, "x")
    assert (result.model, result.attempts) == ("primary", 1)


def test_overloaded_503_or_504_goes_to_the_next_model_at_once():
    """7.10.26: an overloaded model retried 3x (each try hanging) ate the budget; flash-lite never ran."""
    for code in (503, 504):
        llm.reset_cooldowns()
        client = FakeClient(server_error(code), text("ok"))
        result = gen(client, MODELS, "x")
        assert (result.model, result.attempts) == ("fallback", 2)
        assert [r["model"] for r in client.requests] == ["primary", "fallback"]


def test_a_client_timeout_also_goes_to_the_next_model():
    client = FakeClient(TimeoutError("read timed out"), text("ok"))
    assert gen(client, MODELS, "x").model == "fallback"


def test_backoff_between_attempts_for_transient_500s():
    slept = []
    client = FakeClient(server_error(500), server_error(502), text("ok"))
    llm.generate(client, ["m"], "x", sleep=slept.append)
    assert slept == [2, 6]


def test_one_more_pass_over_the_chain_when_every_model_failed():
    slept = []
    client = FakeClient(server_error(503), server_error(503), text("ok"))
    result = llm.generate(client, MODELS, "x", sleep=slept.append)
    assert (result.model, result.attempts) == ("primary", 3) and slept == [llm.PASS_PAUSE_S]


def test_no_second_pass_without_time_left():
    import time
    client = FakeClient(server_error(503), server_error(503), text("never"))
    with pytest.raises(llm.LLMUnavailable):
        llm.generate(client, MODELS, "x", sleep=no_sleep, deadline=time.monotonic() + 1)
    assert len(client.requests) == 2


def test_quota_429_skips_straight_to_the_next_model():
    client = FakeClient(server_error(429), text("ok"))
    result = gen(client, MODELS, "x")
    assert (result.model, result.attempts) == ("fallback", 2)


def test_client_errors_are_not_retried():
    client = FakeClient(client_error(400), text("never"))
    with pytest.raises(Exception):
        gen(client, MODELS, "x")
    assert len(client.requests) == 1


def test_unavailable_model_404_skips_straight_to_the_next():
    client = FakeClient(client_error(404), text("ok"))
    result = gen(client, MODELS, "x")
    assert (result.model, result.attempts) == ("fallback", 2)


def test_all_models_failing_raises_unavailable():
    client = FakeClient(*[server_error() for _ in range(6)])
    with pytest.raises(llm.LLMUnavailable):
        gen(client, MODELS, "x")
    assert len(client.requests) == 4  # 2 models x 2 passes


# ---- runner: the tool loop ------------------------------------------------------------

def make_tools(log):
    def add(args):
        if "item" not in args:
            raise ValueError("item is required")
        log.append(args["item"])
        return {"ok": True}

    return [Tool("add_item", "Add an item.", {"type": "object", "properties": {"item": {"type": "string"}}}, add)]


def run(client, tools, **kw):
    return run_tool_loop(client, MODELS, "system", "user", tools, generate_fn=gen, **kw)


def test_loop_executes_tool_calls_until_text():
    log = []
    client = FakeClient(
        tool_calls(("add_item", {"item": "a"}), ("add_item", {"item": "b"})),
        tool_calls(("add_item", {"item": "c"})),
        text("done"),
    )
    result = run(client, make_tools(log))
    assert log == ["a", "b", "c"]
    assert result.final_text == "done"
    assert result.rounds == 3
    assert all(c.ok for c in result.calls)
    # the tool results are sent back to the model
    last_request = client.requests[-1]["contents"]
    assert last_request[-1].parts[0].function_response.response == {"ok": True}


def test_bad_tool_input_is_reported_to_the_model_not_raised():
    log = []
    client = FakeClient(tool_calls(("add_item", {}), ("nope", {"x": 1})), text("done"))
    result = run(client, make_tools(log))
    assert [c.ok for c in result.calls] == [False, False]
    assert "item is required" in result.calls[0].result["error"]
    assert "unknown tool" in result.calls[1].result["error"]
    assert result.final_text == "done"


def test_round_limit():
    log = []
    client = FakeClient(*[tool_calls(("add_item", {"item": str(i)})) for i in range(5)])
    result = run(client, make_tools(log), max_rounds=3)
    assert result.hit_round_limit
    assert log == ["0", "1", "2"]


def test_loop_survives_a_503_mid_run():
    log = []
    client = FakeClient(tool_calls(("add_item", {"item": "a"})), server_error(), text("done"))
    result = run(client, make_tools(log))
    assert result.final_text == "done"
    assert result.attempts == 3



def test_an_overloaded_model_is_skipped_for_a_while():
    """7.10.26: each tool round waited 45 s on the same hung model; now it's skipped."""
    client = FakeClient(server_error(504), text("one"), text("two"))
    assert gen(client, MODELS, "x").model == "fallback"
    assert gen(client, MODELS, "y").model == "fallback"  # primary is cooling down: not even tried
    assert [r["model"] for r in client.requests] == ["primary", "fallback", "fallback"]


def test_when_every_model_is_cooling_down_all_are_tried_anyway():
    client = FakeClient(server_error(503), server_error(503), server_error(503), server_error(503), text("ok"))
    with pytest.raises(llm.LLMUnavailable):
        gen(client, MODELS, "x")  # both now cooling down
    assert gen(client, MODELS, "y").model == "primary"  # last resort: tried anyway
