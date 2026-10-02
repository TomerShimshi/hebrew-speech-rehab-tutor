# Sub-plan 04: Memory update (SUMMARY_MODEL call #2)

Part of the [master design](00-master-design.md). Depends on [03](03-auth-db-transcripts.md) (done: sign-in, Firestore sessions and transcripts).

## Goal
After each session, an agent call reads the saved transcript and **updates the tutor's memory of Dad**: what they talked about, personal facts he shared, what helped and what frustrated him, how his word retrieval went, and what to focus on next time. The next session's tutor prompt includes that memory, so she **remembers him** and can say things like "last time you told me about the trip to the Galilee…".

## Out of scope
- the per-session lesson plan / ClassPlan (05)
- games data (06)
- web search (07)
- viewing or editing memory in a UI (08); for now, use the Firestore console

## Design decisions (2026-10-01, after 03 and a live check of the models)
- **Model:** `SUMMARY_MODEL=gemini-3.8-flash` (available on the key; function calling verified live: it correctly called `record_word_result("טבריה", "cued")`).
  - **Reliability is the main risk.** During planning, `gemini-3.8-flash` returned `503 high demand` repeatedly on the free tier, and once so did `gemini-3.5-flash`.
  - So every model call goes through `llm.generate()`: up to 3 attempts per model with backoff (2 s, 6 s), then the next model in `SUMMARY_FALLBACK_MODELS=gemini-3.5-flash,gemini-2.5-flash`. Only `503`/`429`/`500` and timeouts are retried; `4xx` errors are not.
  - If every model fails, the session is marked `memory_status: failed` and **retried later** (see triggers). The transcript is never lost, because it's already in Firestore.
- **Two phases** (we couldn't confirm that tools and a JSON schema work together in one call):
  1. **Tool phase (the agent loop).** Context: the patient profile, the **current memory**, and the **transcript**, with both versions of his lines (Gemini's `text` and the browser's `live_text`). The model calls **write tools** to record what it learned. At most 8 rounds.
     - **Reads go in the context, not through tools.** The memory and transcript are small, and every extra round trip is another chance of a 503. **Writes go through tools,** so each one is validated, logged and deterministic.
  2. **Consolidation phase.** A separate call with `response_schema` and no tools. Input: the **updated** memory sections and this session's summary. Output: a fresh `memory_prompt`, the compact text injected into the tutor prompt, plus `focus_next_session`.
- **Tools** (`app/agent/memory_tools.py`, validated with Pydantic, applied to an in-request memory draft that's saved once at the end):
  - `update_memory(section, op: add|replace|remove, item)`. Sections:
    - `personal_facts`: people, places and life events he shared
    - `interests`
    - `what_works`: hints and approaches that helped
    - `what_to_avoid`: frustrations, sensitive topics
    - `language_observations`: patterns, e.g. "struggles with names of places, retrieves with the first-syllable hint"
    - `homework_given`

    Each section is capped (e.g. 25 items × 200 chars). Exact duplicates are ignored.
  - `record_word_result(word, result: uncued|cued|failed, cue_level?, asr_confidence: high|low)`: the **word bank**. A deterministic Python merge (`app/word_bank.py`): counts per result, `last_result`, `last_seen`, and a spaced-retrieval `next_due` (it grows after uncued successes and resets after a failure). It's used for real from 05 on; here we start collecting.
  - `save_session_summary(summary, topics[], mood: good|ok|low|unknown, highlights[], difficulties[])`: written to the session doc.
  - `raise_flag(kind: sudden_decline|distress|safety|technical, severity: low|high, evidence)`: written to `patients/{pid}/flags/{id}`. The caregiver page (08) shows these; for now they're visible in the console and logs.
- **Prompt files** (`prompts/memory_update.yaml`), in English:
  - the role: a careful assistant to a speech-language pathologist
  - **treat transcripts as uncertain.** Both versions are given. 03 found a case where Gemini's caption flipped the meaning ("can't" vs "can"); when the versions conflict, note the uncertainty and don't record a "fact" from just one of them
  - record only what he actually said; no diagnosing, no medical claims
  - compare with the previous memory to spot a **sudden decline**, and raise a flag if so
  - keep `memory_prompt` ≤ ~500 words, written as instructions to the tutor ("He enjoys…", "Last session you…", "Next time, …")
- **Firestore:**
  - `patients/{pid}/memory/current`: `memory_prompt`, `sections{…}`, `word_bank{word: {...}}`, `focus_next_session[]`, `last_session_id`, `sessions_processed`, `updated_at`, `prompt_version`.
  - `patients/{pid}/memory_history/{sid}`: the **previous** `memory/current`, saved before overwriting, so a bad update can be rolled back (rollback UI in 08).
  - The session doc gains `summary`, `topics`, `mood`, `highlights`, `difficulties`, `memory_status` (`pending` / `processing` / `done` / `failed` / `skipped`), `memory_error`, `memory_model` (which model actually answered) and `memory_attempts`.
- **When it runs** (the browser never waits for it):
  - **`/end`:** after marking the session ended, the server runs the update **inside that request**. Cloud Run throttles CPU after the response is sent, so it can't run in the background afterwards. The browser already sent `/end` with `keepalive` and shows "כל הכבוד!" ("Well done!") right away.
  - **`/start` recovers missed sessions.** Abandoned sessions (tab closed) and `failed` ones are processed before the new session starts (at most 2, with a ~60 s budget). While that happens, Dad sees **"רגע, אני נזכרת בשיחה הקודמת שלנו…"** ("one moment, I'm remembering our last conversation…"). If it fails, the session starts anyway with the older memory.
  - Sessions with **fewer than 2 patient lines are `skipped`**, so they don't pollute the memory.
  - **No double processing:** a transaction moves `pending|failed → processing`. A `processing` state older than 10 minutes counts as failed.
- **The tutor uses the memory:** `/start` renders `memory_prompt` and `focus_next_session` into the tutor prompt's `{memory_prompt}` section. `tutor.yaml` (v0.9) adds to the opening: *"If you remember something from the last session, mention one thing naturally in your greeting."*
- **Privacy:** the transcripts go to Gemini (free tier for the POC, as decided). The memory lives only in Firestore. Nothing personal goes into the repo.

## Files
| File | Purpose |
|---|---|
| `app/llm.py` | `generate(models, contents, config)`: retry, backoff and fallback chain, with a timeout per attempt; returns `(response, model_used, attempts)`. The only place that calls Gemini for text. |
| `app/agent/runner.py` | A generic manual function-calling loop: tool registry, at most N rounds, logs every call; a failing tool returns an error message to the model instead of crashing. Reused by 05–07. |
| `app/agent/memory_tools.py` | The four tools, their declarations and Pydantic validation, applied to a `MemoryDraft`. |
| `app/agent/memory_update.py` | Orchestration: lock → build context → tool phase → consolidation phase → save history + memory + session fields → `done`/`failed`/`skipped`. |
| `app/word_bank.py` | The deterministic spaced-retrieval merge. |
| `app/memory_store.py` | Firestore and in-memory implementations: `get_memory`, `save_memory(with history)`, `claim_session_for_memory` (transactional), `pending_memory_sessions`, `add_flag`. |
| `app/schemas.py` | `MemorySections`, `MemoryDraft`, `ConsolidatedMemory`, the tool argument models. |
| `prompts/memory_update.yaml` | The tool-phase system instruction plus the consolidation instruction. |
| `prompts/tutor.yaml` | v0.9: use the memory in the greeting. |
| `app/main.py` | `/end` runs the update. `/start` recovers pending sessions and injects the memory. |
| `static/app.js` | The "נזכרת…" status while `/start` is recovering. |
| `app/config.py` | `SUMMARY_MODEL`, `SUMMARY_FALLBACK_MODELS`, `MEMORY_MAX_TOOL_ROUNDS`. |
| `tests/` | A **fake LLM** that returns scripted tool calls and JSON; retries/fallback on 503; the runner's round limit and tool-error handling; tool validation and section caps; word-bank spacing; history saved before overwrite; `skipped` for short sessions; transactional claim; `/start` recovery; memory rendered into the tutor prompt. |

## Tasks
1. [x] `llm.py` (retries/fallback) and `agent/runner.py`, with tests.
2. [x] Schemas, word bank, memory tools and the memory store, with tests.
3. [x] `prompts/memory_update.yaml`, plus a live run on the real transcript from 03 (`X8ziABxU`); review the resulting memory with Tomer.
4. [x] Wire `/end` and `/start` (recovery + injection); tutor prompt v0.9; the frontend "נזכרת…" status.
5. [x] Local end-to-end: session 1 → memory saved → session 2 greets with a recall.
6. [x] Deploy, test on the remote, then commit and push.

## Manual steps for Tomer
- Review the first generated memory (task 3) and say whether it captures the right things.
- Nothing to set up in GCP: the same key and Firestore are used.

## Done when
- [x] `pytest` passes (76 tests).
- [ ] After a session, `memory/current` has a sensible `memory_prompt` and sections, the session doc has `summary` and `memory_status: done`, and `memory_history/` holds the previous version.
- [ ] **Session 2 opens by naturally recalling something from session 1.**
- [x] With the model forced to fail (bad model name in config), the session is marked `failed`, and the next `/start` processes it successfully once the model is fixed.
- [x] A 1-line session is `skipped`.
- [ ] A conflict between the two transcript versions doesn't become a "fact" in memory.

## Commit
`Sub-plan 04: post-session memory update agent with tool calling and history`

## Changes while building (2026-10-01)
- **Separate record per account (Tomer's request).** Every Firestore record is keyed by the **login email**: `patients/{email}/sessions|memory|memory_history|flags`. Memories can never mix; Tomer's test sessions don't touch Dad's memory. Dad's *profile* (in the bucket) still applies to every account, so tests feel like his sessions. `PATIENT_ID` was removed. The old `patient-1` test data was moved into Tomer's record and marked `skipped`.
- **The hourly sweep replaces blocking recovery on `/start`.** A blocking recovery could take about 2 minutes on a bad day. Cloud Scheduler job `memory-sweep` (hourly, `Asia/Jerusalem`) calls `POST /internal/memory/sweep` with a Google-signed OIDC token for the `memory-sweeper` service account. The app verifies the signature, the audience (the service URL) and that exact email; anyone else gets 401/403. It processes up to 3 waiting sessions per run (abandoned, or `failed` because the models were overloaded). `/end` still processes its own session right away, with a 240 s budget. Cloud Run's timeout was raised to 600 s.
- **Model availability (seen live):** `gemini-3.8-flash` hit long 503 "high demand" spikes, and `gemini-2.5-flash` returns **404 "no longer available to new users"** even though it's listed. The fallback chain is now 3.8-flash → 3.7-flash → 3.6-flash → flash-latest → 3.5-flash-lite. A 404 skips straight to the next model, and a whole update shares one time budget. **This affects 07:** its plan relied on free Google Search grounding in 2.5-flash.
- **First real dry run** (Tomer's 27-line session): it took 128 s and 21 attempts and was answered by `3.5-flash-lite`. The output was accurate and lean (an interest, a personal fact, a correct summary including the early ending). It sided with the browser caption where Gemini's caption flipped the meaning.
- **The memory reaches the tutor:** `/start` renders `memory_prompt` plus "Focus for this session" into the tutor prompt. In v0.9, she recalls one thing in her greeting, asks about homework, and never recites the memory.
- **Debug archive of the exact tutor prompt (Tomer's request):** each new session saves the full system prompt to `gs://heb-practice-private/debug/prompts/<email>/<session id>.md`, and the session doc gets a `prompt_uri`. It's best-effort and never blocks a session. The runtime service account has `objectCreator` only (it can't overwrite or delete, e.g. the profile). A lifecycle rule deletes `debug/` after **30 days**: about 15 KB per file, far inside the 5 GB free tier, so no size guard is needed.
