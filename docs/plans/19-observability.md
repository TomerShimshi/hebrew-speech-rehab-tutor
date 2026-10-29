# Sub-plan 19: Seeing inside every step -- traces, inputs and outputs, latency and cost in Google Cloud

Part of the [master design](00-master-design.md). After [18](18-one-question-greeting.md), before [20](20-names-goodbyes-and-excluded-sessions.md). Requested by Tomer (2026-10-24). **Built 25.10 -- a trial of Cloud Trace: after seeing its pages we keep it, or switch the viewer (see E).** Built as designed; the dashboard and its log-based metrics are created by `deploy/setup_monitoring.sh` (run by `setup_gcp.sh`), and thought summaries are off until `TRACE_THOUGHTS=true` in `.env` (after the dry run). The 64 KiB test (B) was accepted by the Telemetry API but can only be read in the console: the Cloud Trace API can't read spans sent through the Telemetry API (a known gap). **Fixed 28.10:** the per-agent log entries are buffered and written when the job ends, so they all carried the write time; each entry now has its own `timestamp`, so a job's log keeps its order and gaps. **Added 28.10:** the user (`app.account`, the login email) on every span and as a log label (`labels.account`), to filter one user's traces and logs. **Added 28.10 (after a tutor session):** each tutor step shows its cost (the page counts Gemini Live's usage per step) and its Inputs/Outputs (her prompt, the talk before it and the step's instructions; the step's talk), and each of her turns the lines before it; her response time is measured from the last sound of his voice, not his transcript (which came 1-7 ms before her reply). Trace Explorer shows the Inputs/Outputs tab only for spans shaped like a model call: `gen_ai.operation.name` = `generate_content` on the span (`chat` is ignored), the provider, and replies with a `finish_reason` (tested 28.10 with test spans); the tutor's spans now are. **Added 29.10 -- her whole context window:** the page logs everything it puts into her context besides the voices (its notes, her tool calls, its exact replies, timed like the turns) and sends it once before /end (`POST /api/session/{id}/context`, its own request: /end's keepalive body stays small; saved as the session's `live_context`). The trace rebuilds her context in order: each step's Inputs end with the start note or the next_step reply that handed it to her; each of her turns is a model call with her prompt and her whole context before it, and her line plus the tool calls she made in it as output; the full prompt and context also go to the `tutor` log (`live_content`). A tool reply must hold an object, not a string: Trace Explorer marks a string reply "missing or invalid properties" (tested 29.10), even though the GenAI schema allows it. A page open since before a deploy reloads itself (`/api/health` reports the front end's version), so a session never runs an old script.

## Why
- **Today we see what the agents did, not why or at what price.**
  - Each tool call is one line in the server log, with its arguments cut at 120 characters and no result (`[agent] record_needs({...}) -> ok`).
  - Each session keeps counts (`memory_tool_calls`, `plan_tool_calls`, the model, the attempts) and the final results.
- **Not recorded anywhere:**
  - the input an agent got and what it answered, round by round;
  - the plan builder's reasoning;
  - how long each call took;
  - the tokens and cost per call, per session, per job;
  - the live session's own usage and her response time.
- **What we only learn from the monthly budget alert:** cost, and only as a total. When credits ran out (twice), we couldn't say what had used them.
- **Questions this should answer:**
  - "Why did the builder put this step in the plan?"
  - "What did the memory agent read before `record_needs`?"
  - "Which job costs the most?"
  - "Was the freeze a slow model?"
  - "How long does he wait for her answer?"
- **Not on the caregiver page.** It is for the family and is dense enough. This is for us, in the Google Cloud console.

## Goal
1. **A trace per job**, in Cloud Trace: memory update, next-plan build, research, summary, and the live session. Each job is a waterfall of its model calls and tool calls, with latency, model, attempts, fallbacks, tokens and cost.
2. **The full inputs and outputs** of every model call and tool call, in Cloud Logging, linked to their trace. Includes the plan builder's thought summaries.
3. **The live session:** the usage Gemini reports, her response time per turn, the step changes and the held calls. Sent by the page at the end and written as a trace.
4. **A dashboard** in Cloud Monitoring: cost per day, job and model; latency; failures and fallbacks.
5. **Inside the project:** nothing leaves heb-practice. Free at our volume.

## Design

### A. Where things go (GCP)
| What | Where | Why |
|---|---|---|
| The tree: job → model calls → tool calls, with the numbers and names, **and the content that fits**: replies, tool arguments and results, thought summaries, the page's steps | **Cloud Trace**, through the **Telemetry API** (OTLP) | A waterfall per job, with the content in the span. The Telemetry API takes attribute values up to 64 KiB and 1024 attributes per span; the older Cloud Trace API (the usual exporter) cuts values at 256 bytes and keeps 32 attributes. |
| The full prompts (and anything over 64 KiB) | **Cloud Logging**: one structured entry per call, with the trace and span ids | A prompt is ~16-50k characters, ~32-100 KB in UTF-8 (Hebrew is 2 bytes a character), so the larger ones don't fit in a span. Up to 256 KB per entry; from a span you open its log, and from a log you jump to its trace. |
| Charts | **Cloud Monitoring**: log-based metrics plus a dashboard kept as a JSON file in `deploy/` | "The GCP dashboard"; created by the deploy script. |

- **Retention:** traces are kept 30 days (fixed); logs 30 days (the default bucket). Later, if the agent evals need older inputs: a log sink to the private bucket or BigQuery.
- **Privacy:** the prompts hold his transcripts and health details. They stay in the project, like Firestore and the bucket, and are visible only to accounts with access to the project. No third-party tracing service: we considered Langfuse, LangSmith, Phoenix and Helicone.

### B. Instrumenting (server)
- **First, a test (before anything else):** one span with a 60 KB attribute, sent through the Telemetry API, and checked in Trace Explorer. Google's pages disagree on whether the 64 KiB limit applies to traces (the Trace quotas page: yes; the general quotas page: the Trace limits apply too). If values are still cut at 256 bytes, the content goes to Cloud Logging only, as in the first version of this plan.
- **OpenTelemetry SDK** with the OTLP exporter to `telemetry.googleapis.com` (the service account's credentials). One tracer for the app.
- **Our own spans at the two choke points.** The ready-made google-genai instrumentation records calls but doesn't know our jobs, rounds or fallbacks.
  - **`generate()`** (`app/llm.py`): one span per call.
    - Attributes: model, attempts, the models tried, latency, and tokens (input, output, thinking, cached, from `usage_metadata`). Also the estimated cost and the status.
    - Attribute names follow the OpenTelemetry names for AI calls (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, ...), plus ours (`app.job`, `app.session_id`, `app.round`, `app.cost_usd`).
  - **`run_tool_loop()`** (`app/agent/runner.py`): a span per round, and a child span per tool call with its name, ok/error and latency.
  - **A job span** where each job starts: the memory update, the plan build, research, the summary, "process now", the sweep. It carries the account, the session id and the trigger (end, sweep, caregiver).
- **The content:** in the span when it fits (under ~60 KB): the reply, the function calls and their results, the thought summaries, the new part of the input (his session's turns, the last round's tool results). The full prompt goes to a structured JSON line on stdout: Cloud Run sends it to Cloud Logging, and its `logging.googleapis.com/trace` and `spanId` fields link it to the span. The fixed system instruction is logged once per version (by its hash), not on every call.
- **Thought summaries:** `include_thoughts` on for the plan builder (and maybe the memory agent), behind a setting. Checked first with a dry run: same results, and a cost that stays reasonable.
- **Cost:** tokens × a price table in the config (per model; input, output and audio separately). It is an estimate: the bill stays the truth and is compared monthly.
- **Cloud Run's CPU:** after a response is sent the CPU is throttled. So spans are flushed (`force_flush`) at the end of each job, before the response. The jobs already run inside the request, for the same reason.
- **Never in the way:** if the exporter fails, the error is logged and the job goes on.

### C. The live session (the page)
- The browser can't send traces itself (it would need credentials), so it collects and sends one summary at the end, with `/end`:
  - **usage:** Gemini Live's `usageMetadata` messages added up, with the text/audio split;
  - **her response time per turn:** from the end of his speech to her first audio;
  - **the step changes and the held calls**, with their times;
  - **reconnects and freezes:** the connection lost or resumed, a turn without audio.
- The server writes it as the session's trace: a span per step and one per held call, with the timings as events. Plus a log line with the totals. Her response times give the dashboard a "how long he waits" chart.

### D. The dashboard
- Log-based metrics:
  - cost (sum) per job and model;
  - latency (distribution) per job and model;
  - tokens per job;
  - fallbacks and failures (count);
  - her response time (distribution).
- One dashboard, `deploy/monitoring/dashboard.json`, created or updated by the deploy script.
- Later (not now): an alert when a day's cost goes over a limit, earlier than the budget alert.

### E. A trial: the viewer can change
- The recording is OpenTelemetry: spans with standard names. Moving to another viewer changes the exporter, not the code that records.
- **Considered (24.10), if Cloud Trace's pages aren't good enough:**
  - **Langfuse Cloud** (free plan): the full prompt inline, cost and evals built in -- but his transcripts and health details would be stored with a third party.
  - **Langfuse self-hosted** in the project: private, but Postgres, ClickHouse, Redis and storage running all the time cost money.
  - **Arize Phoenix on Tomer's computer:** the spans saved as files in the private bucket, loaded into a local Phoenix to look at -- free and private, but not live; Phoenix reads its own attribute names (OpenInference), so we would write those too.
- After seeing Cloud Trace with a few real sessions: keep it, or switch (and if needed, take the exporter part of this plan out).

### F. Checking it
- **Locally:** the spans and log lines printed to the console (a debug exporter); unit tests check the attributes and the cost calculation with a fake model.
- **After deploying:** one session on the test account. Then:
  - in Trace Explorer, the memory and plan traces show the rounds and tools;
  - the logs open the full prompt from a span;
  - the session's trace shows the usage and response times;
  - the dashboard shows the session.
- **Tie it out:** the summed cost for a day vs. the billing page.

## Files
| File | Purpose |
|---|---|
| `app/telemetry.py` | The tracer and exporter, the job span, the structured log line, the cost table. |
| `app/llm.py`, `app/agent/runner.py` | Spans and log lines per model call, round and tool call. |
| `app/main.py`, `app/caregiver_api.py`, the agents | The job span at each entry point; the live session's summary at `/end`. |
| `static/app.js` | Usage, response times and connection events collected and sent with `/end`. |
| `app/config.py` | Price table; telemetry on/off; thought summaries on/off. |
| `deploy/monitoring/dashboard.json`, `deploy/deploy.sh`, `deploy/setup_gcp.sh` | The dashboard and log-based metrics; the service account's Cloud Trace role. |
| `requirements.txt` | OpenTelemetry SDK and the OTLP exporter (with Google auth). |
| `docs/tools.md` (generator) | The "Logging" section: where to look now. |
| `tests/` | Attributes, cost, a failing exporter doesn't break a job, the live summary at `/end`. |

## Later
- **Agent evals from the traces:** replay the memory agent and the plan builder on logged inputs, like `evals/replay_turns.py` does for the tutor.
- **A daily cost alert.**
- **A log sink** to keep the inputs longer than 30 days, if needed.

## Done when
- [ ] Every memory update, plan build, research and summary has a trace with its rounds and tools, latency, tokens and cost.
- [ ] The 64 KiB test done: the content that fits is in the span; the full prompts open from the span in Cloud Logging.
- [ ] Every model call's input and output, and every tool call's arguments and result, can be read from the trace.
- [ ] The plan builder's thought summaries are in the logs (if the dry run keeps them on).
- [ ] Each live session has a trace with its usage, her response times and the step changes.
- [ ] The dashboard shows cost, latency and failures per job and model, and a day's cost is close to the bill.
- [ ] A telemetry failure never breaks a session or a job; `pytest` passes.

## Commit
`Sub-plan 19: seeing inside every step -- traces, inputs and outputs, latency and cost in Google Cloud`
