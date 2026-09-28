# Sub-plan 04: Memory update (SUMMARY_MODEL call #2)

Part of the [master design](00-master-design.md). Depends on [03](03-auth-db-transcripts.md).

## Goal
After every session, an agent call (`SUMMARY_MODEL`, e.g. `gemini-3.8-flash`) reads the saved transcript and updates the memory using tools, then rewrites a compact `memory_prompt`. The next session's tutor prompt includes that memory, so the tutor remembers what they talked about and what he needs to work on.

## Out of scope
The per-session ClassPlan (05), games (06), web search (07).

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `MemoryEdit{section, op: add\|replace\|remove, content}`, `WordResult`, `SessionMetrics` (mood if known, independent vs. assisted turns, fatigue markers, `review_with_audio[]`, `asr_confidence` notes), `Flag`, `ConsolidatedMemory{memory_prompt, focus_next_session[]}`. |
| `app/agent/runner.py` | Generic function-calling loop over `google-genai`: tool registry, at most 8 rounds, a timeout, logging of every tool call, and a final structured output validated against a Pydantic `response_schema`. |
| `app/agent/tools.py` | Memory tools: `read_memory(section)`, `read_session_transcript(id)`, `list_sessions(n)`, `update_memory(...)`, `record_word_result(word, result, cue_level, asr_confidence)`, `save_session_metrics(...)`, `raise_flag(kind, severity, evidence)`. |
| `app/word_bank.py` | A deterministic spaced-retrieval merge (next due date grows with each uncued success and resets on a failure). Unit-tested, no LLM. |
| `app/agent/memory_update.py` | Orchestrates call #2 and saves the old `memory_prompt` to `memory/history/{session_id}` before writing the new one (≤ ~800 words). Status moves `ended → memory_updated`. |
| `prompts/memory_update.yaml` | Instructions: treat the transcript as **uncertain** (speech recognition on impaired speech), keep durable facts (people, interests, what works or frustrates him), compare against recent sessions for a **sudden decline** (raise a high-severity flag), and stay within the size budget. |
| `prompts/tutor.yaml` | Renders `{memory_prompt}` and a "recall from last time" line. |
| `app/main.py` | `/end` runs call #2 synchronously (the browser shows "כל הכבוד! נתראה מחר", "Well done! See you tomorrow"). A new `POST /api/session/prepare` detects sessions stuck at `ended` and finishes them. |
| `tests/` | Fake LLM that emits scripted tool calls; runner round limit; `update_memory` validation; word-bank spacing; history kept; resuming after a failure. |

## Done when
- [ ] `pytest` passes.
- [ ] After session 1, `memory/current.memory_prompt` makes sense, and `memory/history/` contains the previous version.
- [ ] Session 2 opens by naturally recalling something from session 1.
- [ ] If the tab is killed during `/end`, the next app open finishes the memory update.

## Commit
`Sub-plan 04: post-session memory update agent with tool calling and history`
