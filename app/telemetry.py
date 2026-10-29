"""Traces (sub-plan 19): every agent's work -- its model calls and tool calls, with latency, tokens,
cost and content -- for us, in the Google Cloud console, not the caregiver page.

- **A trace per agent** (Cloud Trace, OpenTelemetry spans sent to the Telemetry API), each its own
  waterfall, every span named after it:
  - `memory-agent` > `memory-agent: round N` > `memory-agent: generate_content` and
    `memory-agent: tool <name>`;
  - `plan-builder` > the same, with its research inside (`plan-builder: research round N` ...);
  - `tutor` (the live session) > `tutor: step N: <kind>` > `tutor: him` / `tutor: her` (each turn);
  - `translate` (the therapist export).
  Every span has `app.agent` (filter: `app.agent:memory-agent`) and `app.account` (the login email:
  one user's traces), and shows the TOTALS under it
  (`app.total.*`: cost, tokens, model calls). Attributes hold what fits (~60 KB a value).
- **Trace Explorer's Inputs/Outputs tab**: each model call (and the tutor's context, per step and turn)
  carries the OpenTelemetry GenAI event (`gen_ai.client.inference.operation.details`, conventions
  1.37): the system instructions, the input messages (with tool calls and results), the reply.
- **A log per agent** (Cloud Logging, through the Logging API): `memory-agent`, `plan-builder`,
  `tutor`, `translate` -- everything the agent did: its notes and tool calls (the lines it also
  prints), a short `llm_call` line per model call (the dashboard's metrics) and the full prompt
  (`llm_content`), each linked to its span and labelled `agent` and `account` (the login email). Buffered and written when the
  agent's job ends. Without the API (locally, tests): printed to stdout.

Off unless `telemetry_enabled` (on in Cloud Run, off locally and in tests): then the tracer is
OpenTelemetry's no-op and nothing is logged. Never in the way: a failing exporter is logged and
the job goes on. Spans and logs are flushed at the end of each request (main.py's middleware):
Cloud Run throttles the CPU once the response is sent, so a background export could stall.

A trial (19.E): the recording is OpenTelemetry, so another viewer (Langfuse, Phoenix) means
another exporter, not other code.
"""

import contextvars
import datetime as dt
import functools
import inspect
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link, Status, StatusCode

TRACER_NAME = "hebrew-tutor"
ENDPOINT = "https://telemetry.googleapis.com/v1/traces"
TRACE_ATTR_MAX_BYTES = 60_000  # a value over it is cut (the Telemetry API: 64 KiB a value)
LOG_MAX_BYTES = 240_000  # a Cloud Logging entry: 256 KB at most
LOG_API = "https://logging.googleapis.com/v2/entries:write"
SEMCONV = "https://opentelemetry.io/schemas/1.37.0"  # the GenAI conventions Trace Explorer reads
GENAI_EVENT = "gen_ai.client.inference.operation.details"

# Prices in USD (checked 2026-10-06, docs/plans/10-paid-gemini.md): per 1M tokens for text, per
# minute of audio for the live model (audio is 32 tokens a second). An ESTIMATE -- the bill is the
# truth. A model missing here is priced as "default" and marked so.
PRICES = {
    "gemini-3.8-flash": {"in": 0.75, "out": 3.75},
    "default": {"in": 0.75, "out": 3.75},
    "live": {"text_in": 0.75, "audio_in_per_min": 0.005, "audio_out_per_min": 0.018, "text_out": 3.75},
}
AUDIO_TOKENS_PER_MIN = 32 * 60

# The agents, by job: each is its own trace and its own log; research runs inside the plan builder.
AGENTS = {"memory_update": "memory-agent", "next_plan": "plan-builder", "research": "research",
          "translate_export": "translate", "live_session": "tutor"}

_job: contextvars.ContextVar[str] = contextvars.ContextVar("telemetry_job", default="")
_agent: contextvars.ContextVar[str] = contextvars.ContextVar("telemetry_agent", default="")  # the trace's agent
_account: contextvars.ContextVar[str] = contextvars.ContextVar("telemetry_account", default="")  # whose (the login email)
# the totals of the spans open right now, innermost last: a model call adds to each of them
_totals: contextvars.ContextVar[tuple] = contextvars.ContextVar("telemetry_totals", default=())
_state = {"enabled": False, "provider": None, "project": "", "thoughts": False, "log_session": None,
          "resource": None, "pending": []}


def _log(message: str) -> None:
    print(f"[telemetry] {message}", file=sys.stderr, flush=True)


def setup(settings) -> None:
    """Starts sending spans (once per process). Without `telemetry_enabled`: nothing."""
    if _state["provider"] is not None or not getattr(settings, "telemetry_enabled", False):
        return
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import SpanLimits, TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        project = settings.gcp_project_id
        provider = TracerProvider(
            resource=Resource.create({"gcp.project_id": project, "service.name": TRACER_NAME}),
            # our own cut (text()) keeps values under the API's limit; the SDK's default would drop
            # attributes over 128 per span
            span_limits=SpanLimits(max_span_attributes=512, max_span_attribute_length=None),
        )
        # small batches: each of her turns carries her whole context (each request stays small)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT,
                                                                        session=AuthorizedSession(creds)),
                                                       max_export_batch_size=8))
        use(provider, project, thoughts=bool(getattr(settings, "trace_thoughts", False)))
        _state.update(log_session=AuthorizedSession(creds), resource=_cloud_run_resource(project))
        _log(f"tracing to Cloud Trace (project {project})")
    except Exception as exc:  # noqa: BLE001 -- tracing must never stop the app
        _log(f"tracing off: {exc!r:.200}")


def _cloud_run_resource(project: str) -> dict:
    """The monitored resource the log entries belong to: this Cloud Run revision (the dashboard's
    metrics filter on it), or "global" outside Cloud Run."""
    service = os.environ.get("K_SERVICE")
    if not service:
        return {"type": "global", "labels": {"project_id": project}}
    region = "us-central1"
    try:
        import requests
        r = requests.get("http://metadata.google.internal/computeMetadata/v1/instance/region",
                         headers={"Metadata-Flavor": "Google"}, timeout=2)
        region = r.text.rsplit("/", 1)[-1] or region
    except Exception:  # noqa: BLE001
        pass
    return {"type": "cloud_run_revision", "labels": {
        "project_id": project, "service_name": service, "location": region,
        "revision_name": os.environ.get("K_REVISION", ""), "configuration_name": os.environ.get("K_CONFIGURATION", "")}}


def use(provider, project: str, *, thoughts: bool = False) -> None:
    """Records with this provider (setup(); tests pass one with an in-memory exporter)."""
    _state.update(enabled=provider is not None, provider=provider, project=project, thoughts=thoughts)


def enabled() -> bool:
    return _state["enabled"]


def thoughts_on() -> bool:
    """The agents ask for thought summaries (19.B, `trace_thoughts`)."""
    return _state["enabled"] and _state["thoughts"]


def flush() -> None:
    """Sends this request's spans and logs now (before Cloud Run throttles the CPU)."""
    flush_logs()
    provider = _state["provider"]
    if provider is not None:
        try:
            provider.force_flush(timeout_millis=5000)
        except Exception as exc:  # noqa: BLE001
            _log(f"flush failed: {exc!r:.200}")


def tracer():
    provider = _state["provider"]
    return (provider.get_tracer(TRACER_NAME, schema_url=SEMCONV) if provider is not None
            else trace.get_tracer(TRACER_NAME))


def text(value, limit: int = TRACE_ATTR_MAX_BYTES) -> str:
    """A string attribute, cut to fit (by bytes: Hebrew is 2 bytes a character)."""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    raw = s.encode("utf-8")
    if len(raw) <= limit:
        return s
    return raw[:limit - 40].decode("utf-8", "ignore") + f" ...[cut: {len(raw)} bytes]"


def _clean(attrs: dict) -> dict:
    out = {}
    for key, value in attrs.items():
        if value is None:
            continue
        out[key] = value if isinstance(value, (bool, int, float)) else text(value)
    return out


def name(what: str) -> str:
    """A span's name under the current agent: `plan-builder: round 2`, `plan-builder: research round 1`."""
    agent = _agent.get()
    if not agent:
        return what
    inner = AGENTS.get(_job.get(), _job.get())
    return f"{agent}: {inner + ' ' if inner and inner != agent else ''}{what}"


@contextmanager
def span(name: str, *, totals: bool = True, new_trace: bool = False, **attrs) -> Iterator:
    """A span (no-op when tracing is off); an exception marks it as an error and goes on up. With
    `totals`, it ends with the totals of the model calls made under it (`app.total.*`). With
    `new_trace`, it starts its own trace (an agent), linked to the span it was started from."""
    parent = trace.get_current_span().get_span_context()
    kwargs = {"context": Context(), "links": [Link(parent)] if parent.is_valid else None} if new_trace else {}
    with tracer().start_as_current_span(name, record_exception=False, set_status_on_exception=False, **kwargs) as s:
        if s.is_recording():
            s.set_attributes(_clean({"app.agent": _agent.get() or None, "app.account": _account.get() or None, **attrs}))
        acc = {"cost": 0.0, "input": 0, "output": 0, "thinking": 0, "calls": 0}
        token = _totals.set(_totals.get() + (acc,)) if totals else None
        try:
            yield s
        except Exception as exc:
            if s.is_recording():
                s.record_exception(exc)
                s.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            raise
        finally:
            if token is not None:
                _totals.reset(token)
                if acc["calls"] and s.is_recording():
                    s.set_attributes({"app.total.cost_usd": round(acc["cost"], 8),
                                      "app.total.input_tokens": acc["input"], "app.total.output_tokens": acc["output"],
                                      "app.total.thinking_tokens": acc["thinking"], "app.total.llm_calls": acc["calls"]})


def _add_totals(cost: float, tokens_in: int, tokens_out: int, tokens_thinking: int) -> None:
    for acc in _totals.get():
        acc["cost"] += cost
        acc["input"] += tokens_in
        acc["output"] += tokens_out
        acc["thinking"] += tokens_thinking
        acc["calls"] += 1


def llm_span(model: str):
    """A model call's span, named by its agent (`memory-agent: generate_content`); its own numbers
    are on it, so no totals."""
    return span(name("generate_content"), totals=False,
                **{"gen_ai.operation.name": "generate_content", "gen_ai.request.model": model,
                   "app.job": _job.get() or None})


def set_attrs(s, **attrs) -> None:
    if s is not None and s.is_recording():
        s.set_attributes(_clean(attrs))


def job(kind: str):
    """An agent's job (memory update, next plan, research, translation): its own trace when it is the
    first agent in this request (`memory-agent`), a span inside the running agent's trace when one
    agent calls another (research inside the plan builder). The account and session come from its
    arguments; its result (a status string) is recorded; its logs are written when it ends."""
    def wrap(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            bound = sig.bind_partial(*args, **kwargs).arguments
            label = AGENTS.get(kind, kind)
            top = not _agent.get()
            span_name = label if top else name(label)
            tokens = [(_job, _job.set(kind)), (_account, _account.set(bound.get("pid") or _account.get()))]
            tokens += [(_agent, _agent.set(label))] if top else []
            try:
                with span(span_name, new_trace=top, **{"app.job": kind, "app.session_id": bound.get("sid")}) as s:
                    result = fn(*args, **kwargs)
                    if isinstance(result, str):
                        set_attrs(s, **{"app.result": result})
                    return result
            finally:
                for var, token in reversed(tokens):
                    var.reset(token)
                if top:
                    flush_logs()
        return inner
    return wrap


def log_name() -> str:
    """The log of the running agent (`memory-agent`, `plan-builder`, ...)."""
    return _agent.get() or "app"


def _now() -> str:
    """Now, for a log entry (RFC 3339)."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log_line(event: str, payload: dict, span_=None, *, log: str | None = None) -> None:
    """A structured entry in the agent's log (or `log`), linked to the span, labelled with the agent.
    Buffered and written through the Logging API when the job ends (flush_logs); printed to stdout
    when the API isn't set up (locally, tests)."""
    if not _state["enabled"]:
        return
    s = span_ or trace.get_current_span()
    ctx = s.get_span_context()
    payload = {"message": payload.get("text") or f"[{event}]", "event": event, **payload}
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > LOG_MAX_BYTES:
        for key in ("contents", "system_instruction", "output"):
            if key in payload:
                payload[key] = text(payload[key], LOG_MAX_BYTES // 3)
    trace_name = f"projects/{_state['project']}/traces/{ctx.trace_id:032x}" if ctx.is_valid else None
    agent = log or log_name()
    if _state["log_session"] is not None:
        # its own time: written later (at the job's end), the entries keep their order and gaps
        entry = {"logName": f"projects/{_state['project']}/logs/{agent}", "resource": _state["resource"],
                 "timestamp": _now(), "severity": "INFO", "jsonPayload": payload,
                 "labels": {"agent": agent, "account": _account.get(), "job": _job.get() or "", "event": event}}
        if trace_name:
            entry.update(trace=trace_name, spanId=f"{ctx.span_id:016x}", traceSampled=True)
        _state["pending"].append(entry)
        return
    line = {"severity": "INFO", **payload}
    if trace_name:
        line.update({"logging.googleapis.com/trace": trace_name, "logging.googleapis.com/spanId": f"{ctx.span_id:016x}",
                     "logging.googleapis.com/trace_sampled": True})
    print(json.dumps(line, ensure_ascii=False, default=str), flush=True)


def flush_logs() -> None:
    """Writes the buffered log entries (a few requests of up to ~2 MB); on failure, prints them."""
    pending, _state["pending"] = _state["pending"], []
    session = _state["log_session"]
    batch, size = [], 0
    for entry in pending + [None]:
        n = len(json.dumps(entry, ensure_ascii=False, default=str).encode("utf-8")) if entry else 0
        if batch and (entry is None or size + n > 2_000_000):
            try:
                r = session.post(LOG_API, json={"entries": batch, "partialSuccess": True}, timeout=15)
                if r.status_code >= 300:
                    raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
            except Exception as exc:  # noqa: BLE001 -- falls back to stdout (Cloud Run's own log)
                _log(f"log write failed ({len(batch)} entries): {exc!s:.200}")
                for e in batch:
                    print(json.dumps({"severity": "INFO", **e["jsonPayload"]}, ensure_ascii=False, default=str),
                          flush=True)
            batch, size = [], 0
        if entry is not None:
            batch.append(entry)
            size += n


def note(message: str) -> None:
    """A line the agent prints (a tool call, a fallback, a decision), also in its log (19)."""
    if _state["enabled"] and _agent.get():
        log_line("note", {"text": message})


# --- model calls -------------------------------------------------------------------------------

def cost_usd(model: str, input_tokens: int, output_tokens: int) -> tuple[float, str]:
    """(estimated cost, which price was used). Thinking tokens are billed as output."""
    price = PRICES.get(model)
    source = model if price else "default"
    price = price or PRICES["default"]
    return round((input_tokens * price["in"] + output_tokens * price["out"]) / 1e6, 8), source


def live_cost_usd(usage: dict) -> float:
    """The live session's estimated cost, from its usage split by modality."""
    p = PRICES["live"]
    audio_in = usage.get("audio_in_tokens", 0)
    audio_out = usage.get("audio_out_tokens", 0)
    text_in = max(0, usage.get("prompt_tokens", 0) - audio_in)
    text_out = max(0, usage.get("response_tokens", 0) - audio_out)
    return round(audio_in / AUDIO_TOKENS_PER_MIN * p["audio_in_per_min"]
                 + audio_out / AUDIO_TOKENS_PER_MIN * p["audio_out_per_min"]
                 + text_in * p["text_in"] / 1e6 + text_out * p["text_out"] / 1e6, 8)


def _dump(value):
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _output(response) -> dict:
    """The reply: its text, its function calls and its thought summaries."""
    out = {"text": "", "function_calls": [], "thoughts": ""}
    try:
        for part in response.candidates[0].content.parts or []:
            if getattr(part, "thought", False) and part.text:
                out["thoughts"] += part.text
            elif part.text:
                out["text"] += part.text
            elif part.function_call:
                out["function_calls"].append({"name": part.function_call.name, "args": dict(part.function_call.args or {})})
    except (AttributeError, IndexError, TypeError):
        pass
    return out


def _parts(parts) -> list[dict]:
    """Gemini parts as GenAI semantic-convention parts (text, reasoning, tool_call, tool_call_response)."""
    out = []
    for p in parts or []:
        p = _dump(p) if not isinstance(p, dict) else p
        if p.get("thought") and p.get("text"):
            out.append({"type": "reasoning", "content": p["text"]})
        elif p.get("text") is not None:
            out.append({"type": "text", "content": p["text"]})
        elif p.get("function_call"):
            fc = p["function_call"]
            out.append({"type": "tool_call", "id": fc.get("id"), "name": fc.get("name"), "arguments": fc.get("args")})
        elif p.get("function_response"):
            fr = p["function_response"]
            out.append({"type": "tool_call_response", "id": fr.get("id"), "response": fr.get("response")})
    return out


def input_messages(contents) -> list[dict]:
    """The call's input as GenAI messages: user / assistant (her tool calls) / tool (their results)."""
    if isinstance(contents, str):
        return [{"role": "user", "parts": [{"type": "text", "content": contents}]}]
    out = []
    for c in contents if isinstance(contents, list) else [contents]:
        if isinstance(c, str):
            out.append({"role": "user", "parts": [{"type": "text", "content": c}]})
            continue
        d = _dump(c)
        parts = _parts(d.get("parts"))
        role = "assistant" if d.get("role") == "model" else d.get("role") or "user"
        if parts and all(p["type"] == "tool_call_response" for p in parts):
            role = "tool"
        out.append({"role": role, "parts": parts})
    return out


def output_messages(response) -> list[dict]:
    try:
        cand = response.candidates[0]
        reason = getattr(cand, "finish_reason", None)
        return [{"role": "assistant", "parts": _parts(cand.content.parts),
                 "finish_reason": (getattr(reason, "name", None) or str(reason or "stop")).lower()}]
    except (AttributeError, IndexError, TypeError):
        return []


def fit_json(value, limit: int = TRACE_ATTR_MAX_BYTES) -> str:
    """JSON under `limit` bytes that stays valid JSON: the longest texts are cut until it fits."""
    s = json.dumps(value, ensure_ascii=False, default=str)
    for _ in range(30):
        if len(s.encode("utf-8")) <= limit:
            return s
        texts = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if isinstance(v, str):
                        texts.append((len(v), node, k))
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(value)
        if not texts:
            break
        n, node, key = max(texts, key=lambda t: t[0])
        node[key] = node[key][: n // 2] + f" ...[cut: {n} characters]"
        s = json.dumps(value, ensure_ascii=False, default=str)
    return text(s, limit)


def record_generation(s, **kwargs) -> None:
    """The model call's numbers and content on its span; the full prompt and a metrics line to
    Cloud Logging. Never raises: a recording problem must not fail the call."""
    if not (_state["enabled"] and s is not None and s.is_recording()):
        return
    try:
        _record_generation(s, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _log(f"recording a model call failed: {exc!r:.200}")


def _record_generation(s, *, model: str, attempts: int, tried: list[str], started: float, response, contents,
                       config) -> None:
    latency_ms = round((time.monotonic() - started) * 1000)
    usage = getattr(response, "usage_metadata", None)
    tokens_in = getattr(usage, "prompt_token_count", 0) or 0
    tokens_out = getattr(usage, "candidates_token_count", 0) or 0
    tokens_thinking = getattr(usage, "thoughts_token_count", 0) or 0
    tokens_cached = getattr(usage, "cached_content_token_count", 0) or 0
    cost, price = cost_usd(model, tokens_in, tokens_out + tokens_thinking)
    out = _output(response)
    contents_d = _dump(contents)
    system = getattr(config, "system_instruction", None) if config is not None else None
    system = system if isinstance(system, str) or system is None else _dump(system)
    _add_totals(cost, tokens_in, tokens_out, tokens_thinking)
    set_attrs(s, **{
        "gen_ai.provider.name": "gcp.gemini",
        "gen_ai.response.model": model, "gen_ai.usage.input_tokens": tokens_in,
        "gen_ai.usage.output_tokens": tokens_out, "app.tokens.thinking": tokens_thinking,
        "app.tokens.cached": tokens_cached, "app.cost_usd": cost, "app.price": price,
        "app.latency_ms": latency_ms, "app.attempts": attempts, "app.models_tried": ",".join(tried),
        "app.output.text": out["text"] or None,
        "app.output.function_calls": out["function_calls"] or None, "app.output.thoughts": out["thoughts"] or None,
        "app.system_instruction.chars": len(system) if isinstance(system, str) else None,
    })
    # The Inputs/Outputs tab (GenAI conventions 1.37): the conversation, each part under ~60 KB.
    system_msgs = [{"type": "text", "content": system}] if isinstance(system, str) else _parts((system or {}).get("parts"))
    s.add_event(GENAI_EVENT, {
        "gen_ai.operation.name": "generate_content", "gen_ai.request.model": model, "gen_ai.response.model": model,
        "gen_ai.system_instructions": fit_json(system_msgs),
        "gen_ai.input.messages": fit_json(input_messages(contents)),
        "gen_ai.output.messages": fit_json(output_messages(response)),
    })
    log_line("llm_call", {"model": model, "latency_ms": latency_ms, "input_tokens": tokens_in,
                          "output_tokens": tokens_out, "thinking_tokens": tokens_thinking, "cost_usd": cost,
                          "attempts": attempts, "job": _current_job()}, s)
    log_line("llm_content", {"model": model, "system_instruction": system, "contents": contents_d,
                             "output": out}, s)


def _current_job() -> str:
    return _job.get()


# --- the live session (the page's summary, sent with /end) -------------------------------------

def _ns(t) -> int:
    return int(t.timestamp() * 1e9)


def _reply(text_: str, calls: list[dict] = ()) -> dict:
    """One of her lines as a model reply (an output message), with the tool calls she made in it."""
    return {"role": "assistant", "parts": [{"type": "text", "content": text_}, *calls], "finish_reason": "stop"}


def _step_given(k: int, step_text: str | None, steps_done) -> list[dict]:
    """How she got step k (without the page's context log): step 1 in the start note, the others as
    her next_step call and the page's reply -- a call and its reply, as Trace Explorer expects."""
    if not step_text:
        return []
    if k == 0:
        return [{"role": "user", "parts": [{"type": "text", "content": f"CURRENT STEP: {step_text}"}]}]
    call_id = f"next_step-{k}"
    done = steps_done[k - 1].done if k - 1 < len(steps_done) else ""
    return [{"role": "assistant", "parts": [{"type": "tool_call", "id": call_id, "name": "next_step",
                                             "arguments": {"done": done}}]},
            {"role": "tool", "parts": [{"type": "tool_call_response", "id": call_id,
                                        "response": {"result": f"CURRENT STEP: {step_text}"}}]}]


_ORDER = {"note": 0, "silent_note": 0, "turn": 1, "call": 2, "reply": 3}  # at the same moment


def context_timeline(turns: list[dict], events: list[dict]) -> list[tuple[float, dict, str]]:
    """Her context window in order, as GenAI messages: the voices (the saved turns: him `user`, her
    `assistant`) and what the page put in besides them (`events`: its notes as `user`, her tool calls,
    its replies as `tool`). Each with its time (seconds from the start) and kind. Her line is placed
    where it started, so a tool call she made in the middle of a line comes after the whole line."""
    items = []
    for n, t in enumerate(turns):
        items.append((t.get("t_start_s", 0), _ORDER["turn"], n, "turn",
                      {"role": "assistant" if t["speaker"] == "tutor" else "user",
                       "parts": [{"type": "text", "content": t["text"]}]}))
    for n, e in enumerate(events):
        kind = e.get("kind")
        if kind in ("note", "silent_note"):
            msg = {"role": "user", "parts": [{"type": "text", "content": e.get("text", "")}]}
        elif kind == "call":
            msg = {"role": "assistant", "parts": [{"type": "tool_call", "id": e.get("id"), "name": e.get("name"),
                                                   "arguments": e.get("args") or {}}]}
        elif kind == "reply":
            msg = {"role": "tool", "parts": [{"type": "tool_call_response", "id": e.get("id"),
                                              "response": e.get("response") or {}}]}
        else:
            continue
        items.append((e.get("at_s", 0), _ORDER[kind], len(turns) + n, kind, msg))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    return [(ts, msg, kind) for ts, _, _, kind, msg in items]


def record_live_session(store, pid: str, sid: str, session: dict, body) -> None:
    """The tutor's trace (the live session), from the page's summary at /end, the saved turns and
    the page's context log: `tutor` > `tutor: step N: <kind>` (from the page's steps_done) >
    `tutor: him` / `tutor: her` (each turn, its text and timing). Her context window is rebuilt in
    order (context_timeline): each of her turns is a model call -- her prompt and her whole context
    before it in, her line and her tool calls out -- and each step shows what she had when it began
    and what she said in it, with its cost. The usage, cost and her response times are on the root;
    the held next_step calls are events. Lines in the `tutor` log. Never raises."""
    if not _state["enabled"]:
        return
    tokens = [(_agent, _agent.set("tutor")), (_job, _job.set("live_session")), (_account, _account.set(pid))]
    try:
        import datetime as dt

        live = body.live
        now = dt.datetime.now(dt.timezone.utc)
        started = session.get("started_at") or now
        ended = session.get("ended_at") or now
        t0 = _ns(started)
        length_s = max(0.0, (ended - started).total_seconds())
        cost = live_cost_usd(live.model_dump())
        times = sorted(live.response_ms)

        def pct(p):
            return times[min(len(times) - 1, int(p * len(times)))] if times else None

        def at(seconds: float) -> int:
            return t0 + int(max(0.0, seconds) * 1e9)

        turns = [t for t in store.list_turns(pid, sid) if t.get("text")]
        prompt = (store.get_session_prompt(pid, sid) or {}).get("text", "")
        agenda = session.get("agenda") or []
        # Trace Explorer shows the Inputs/Outputs tab only for a span shaped like a model call: these on
        # the span, `generate_content` (not `chat`), and her replies with a finish_reason (tested 28.10)
        genai = {"gen_ai.operation.name": "generate_content", "gen_ai.request.model": session.get("model"),
                 "gen_ai.provider.name": "gcp.gemini"}
        root = tracer().start_span("tutor", context=Context(), start_time=t0, attributes=_clean({
            **genai, "app.agent": "tutor", "app.job": "live_session", "app.account": pid, "app.session_id": sid,
            "app.prompt_version": session.get("prompt_version"),
            "app.end_reason": getattr(body.reason, "value", str(body.reason)),
            "gen_ai.usage.input_tokens": live.prompt_tokens, "gen_ai.usage.output_tokens": live.response_tokens,
            "app.tokens.audio_in": live.audio_in_tokens, "app.tokens.audio_out": live.audio_out_tokens,
            "app.usage_reports": live.usage_reports, "app.usage.max_report_total": live.max_report_total,
            "app.cost_usd": cost, "app.total.cost_usd": cost, "app.response_ms.p50": pct(0.5),
            "app.response_ms.p90": pct(0.9), "app.response_ms.max": times[-1] if times else None,
            "app.response_ms.all": live.response_ms or None, "app.reconnects": live.reconnects,
            "app.go_aways": live.go_aways, "app.turns": len(turns),
            "app.steps_done": len(body.steps_done), "app.steps_held": len(body.steps_held),
        }))
        root_ctx = trace.set_span_in_context(root)
        # the steps: each one from the previous step change to its own (the last one to the end)
        bounds, prev = [], 0.0
        for i, d in enumerate(body.steps_done):
            kind = agenda[i]["kind"] if i < len(agenda) else ""
            bounds.append((f"step {i + 1}: {kind or d.done}", prev, d.at_s,
                           {"app.step.kind": kind, "app.step.done": d.done, "app.step.how_it_went": d.how_it_went,
                            "app.step.text": agenda[i]["text"] if i < len(agenda) else None}))
            prev = d.at_s
        n = len(body.steps_done)
        kind = agenda[n]["kind"] if n < len(agenda) else "after the plan"
        bounds.append((f"step {n + 1}: {kind}", prev, max(prev, length_s),
                       {"app.step.kind": kind, "app.step.text": agenda[n]["text"] if n < len(agenda) else None}))
        turns = turns[:400]
        where = [next((k for k, (_, a, b, _) in enumerate(bounds) if a <= t.get("t_start_s", 0) < b), len(bounds) - 1)
                 for t in turns]  # each turn's step
        # Her context window, rebuilt in order: the voices and everything the page put in besides them
        # (its notes, her tool calls, its replies: `live_context`, sent by the page before /end)
        events = session.get("live_context") or []
        timeline = context_timeline(turns, events)
        system = fit_json([{"type": "text", "content": prompt}])
        model = session.get("model") or ""

        def context(until: float, *, inclusive: bool = False) -> list[dict]:
            return [m for ts, m, _ in timeline if (ts <= until if inclusive else ts < until)]

        def calls_in(a: float, b: float) -> list[dict]:
            return [m["parts"][0] for ts, m, kind in timeline if kind == "call" and a <= ts < b]

        # Inputs/Outputs on the root: her prompt and the whole context window
        last = [t for t in turns if t["speaker"] == "tutor"][-1:]
        root.add_event(GENAI_EVENT, {
            "gen_ai.operation.name": "generate_content", "gen_ai.request.model": model,
            "gen_ai.system_instructions": system,
            "gen_ai.input.messages": fit_json([m for _, m, _ in timeline]),
            "gen_ai.output.messages": fit_json([_reply(t["text"]) for t in last]),
        }, timestamp=t0)
        first_note = next((ts for ts, _, kind in timeline if kind in ("note", "silent_note")), 0.0)
        steps = []
        for k, (label, a, b, attrs) in enumerate(bounds):
            # the step's spending: the usage the page counted while she was in it
            usage = live.by_step[k] if k < len(live.by_step) else None
            step_cost = live_cost_usd(usage.model_dump()) if usage else None
            sp = tracer().start_span(f"tutor: {label}", context=root_ctx, start_time=at(a), attributes=_clean({
                **genai, "app.agent": "tutor", "app.account": pid, **attrs,
                "gen_ai.usage.input_tokens": usage.prompt_tokens if usage else None,
                "gen_ai.usage.output_tokens": usage.response_tokens if usage else None,
                "app.tokens.audio_in": usage.audio_in_tokens if usage else None,
                "app.tokens.audio_out": usage.audio_out_tokens if usage else None,
                "app.usage_reports": usage.usage_reports if usage else None,
                "app.cost_usd": step_cost, "app.total.cost_usd": step_cost}))
            # Inputs: her context when the step began -- up to the start note (step 1) or the
            # next_step reply that handed it to her (they share its moment). Outputs: what she said in it.
            if events:
                given = context(first_note if k == 0 else a + 0.05, inclusive=True)
            else:  # a page from before the context log: the step as she got it, rebuilt from the plan
                given = context(a) + _step_given(k, attrs.get("app.step.text"), body.steps_done)
            sp.add_event(GENAI_EVENT, {
                "gen_ai.operation.name": "generate_content", "gen_ai.request.model": model,
                "gen_ai.system_instructions": system,
                "gen_ai.input.messages": fit_json(given),
                "gen_ai.output.messages": fit_json([_reply(t["text"]) for t, w in zip(turns, where)
                                                    if w == k and t["speaker"] == "tutor"]),
            }, timestamp=at(a))
            steps.append((sp, a, b))
        # the turns, each under the step it happened in; each of hers as a model call: her prompt and
        # her whole context window before it in, her line and the tool calls she made in it out
        for i, t in enumerate(turns):
            start = t.get("t_start_s", 0)
            end = turns[i + 1].get("t_start_s", start) if i + 1 < len(turns) else max(start, length_s)
            her = t["speaker"] == "tutor"
            sp = tracer().start_span("tutor: her" if her else "tutor: him",
                                     context=trace.set_span_in_context(steps[where[i]][0]),
                                     start_time=at(start), attributes=_clean({
                                         **(genai if her else {}), "app.agent": "tutor", "app.account": pid,
                                         "app.turn.speaker": t["speaker"],
                                         "app.turn.text": t["text"],
                                         "app.turn.interrupted": bool(t.get("interrupted")) or None,
                                         "app.turn.not_played": bool(t.get("not_played")) or None}))
            if her:
                sp.add_event(GENAI_EVENT, {
                    "gen_ai.operation.name": "generate_content", "gen_ai.request.model": model,
                    "gen_ai.system_instructions": system,
                    "gen_ai.input.messages": fit_json(context(start)),
                    "gen_ai.output.messages": fit_json([_reply(t["text"], calls_in(start, max(start, end) + 0.05))]),
                }, timestamp=at(start))
            sp.end(end_time=at(max(start, end)))
        for h in body.steps_held:
            root.add_event(f"next_step held ({h.reason})", {"step": h.step + 1}, timestamp=at(h.at_s))
        for sp, a, b in steps:
            sp.end(end_time=at(b))
        root.end(end_time=max(_ns(ended), at(prev)))
        log_line("live_session", {"session_id": sid, "cost_usd": cost, "prompt_tokens": live.prompt_tokens,
                                  "response_tokens": live.response_tokens, "response_ms_p50": pct(0.5),
                                  "response_ms_p90": pct(0.9), "reconnects": live.reconnects, "job": "live_session",
                                  "usage_reports": live.usage_reports, "max_report_total": live.max_report_total,
                                  "steps_cost_usd": [live_cost_usd(u.model_dump()) if u else None
                                                     for u in live.by_step]},
                 root, log="tutor")
        # the full prompt and context window in the tutor's log (as the agents' llm_content)
        log_line("live_content", {"session_id": sid, "model": model, "system_instruction": prompt,
                                  "contents": [m for _, m, _ in timeline]}, root, log="tutor")
        for ms in live.response_ms:  # one line each: a distribution on the dashboard
            log_line("live_response", {"response_ms": ms, "session_id": sid}, root, log="tutor")
    except Exception as exc:  # noqa: BLE001
        _log(f"recording the live session failed: {exc!r:.200}")
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
        flush_logs()
