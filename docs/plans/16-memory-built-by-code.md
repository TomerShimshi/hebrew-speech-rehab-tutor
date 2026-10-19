# Sub-plan 16: The tutor's memory, built by code from the checked sections

Part of the [master design](00-master-design.md). After [15.5](15.5-first-sessions-needs-check.md), before [17](17-measuring-and-summarizing.md). Requested by Tomer (2026-10-19), after an audit of the patient's memory text. **Built 2026-10-19.**

## Why
- **Today the memory update has two parts** (04): a tool loop that edits the memory sections one checked item at a time (facts, interests, what works, what to avoid, homework, the word bank), and then one **structured-output call that rewrites from scratch** the text the tutor actually reads (`memory_prompt`, ~250 words) and 2-4 focus points -- from the sections, the session summaries and the previous text.
- **That rewrite is the least controlled step**, and its result is the only memory she gets. An audit of the patient's text (19.10: the current version and two older ones, each claim compared with the sections and the summaries, the doubtful ones traced to the transcripts):
  - **Faithful in what it says:** 9 of 12 claims in the current text come from the sections, 1 from a session summary (the "last time" recall). One claim flagged as unsupported turned out real (in a session and in the sections).
  - **It invents a little, and it sticks:** a tutoring instruction ("give him time to correct himself before you help") is in all three versions, from no source -- the "what works" and "what to avoid" sections are **empty**, so the rewrite fills the gap with its own advice, and each rewrite copies the last.
  - **It drops more:** 3-5 section items are missing in every version (holiday events, a trip, a change the family made to his games). They were recorded and checked, but never reach her -- and because each rewrite starts from the previous text, an omission becomes permanent.
- **It makes corrections harder:** removing a wrong fact on the caregiver page needs another model call to rewrite the text without it (with a check that the rewrite didn't break).
- And it costs one more model call per session.

## Goal
1. **Everything in the checked sections reaches her; nothing else does.** The text she reads is assembled by code.
2. **"What works" and "what to avoid" come from his sessions**, not from a model's general advice.
3. **A removed fact is gone at once**, without a model call.
4. **The patient's sessions keep what they have now** (the "last time" recall, the homework, the focus points) -- minus the unsourced advice, plus the dropped facts.

## Design

### A. The memory text, assembled by code
- `render_memory(memory)` builds the tutor's memory section from the sections, in a fixed order, as short labeled lists:
  - **Last time** (`date`): the latest session summary (already saved by `save_session_summary`) -- what she recalls ONE thing from.
  - **About him:** personal facts; **his interests**.
  - **What works / what to avoid** when he gets stuck.
  - **Language notes** (`language_observations`).
  - **Homework given last time.**
  - **Focus for this session** (B).
- **Order inside a section: newest first**, and a cap per section (the existing 25 items, ~200 characters each) so the prompt stays bounded; the text's length is logged per session.
- **`memory_prompt` stays the field name** (the tutor prompt, the plan builder, research and the caregiver page read it), now written by code after every update and after every caregiver edit.

### B. The focus points, by a tool
- `set_focus(points)` in the memory agent's tool loop: 2-4 short concrete points for the next session, in English, replacing the previous ones. Checked (count, length) like the other tools.
- The consolidation call (`ConsolidatedMemory`) and its prompt are removed.

### C. What works / what to avoid, from what was heard
- The memory agent's prompt: after each session, if something clearly helped him (a cue, a pace, a kind of question) or clearly didn't, `update_memory` it into `what_works` / `what_to_avoid`, with what happened in a few words ("a first-sound cue brought 'נהריה' at once"). Only from this session's transcript; never general advice.
- **Merging instead of piling up:** when a new item updates an old one, `replace` it (the tool already supports it); a section at its cap must replace or remove before adding.

### D. Caregiver edits
- **Removing an item** (`/memory/remove-item`) removes it from the section and re-renders the text by code: no model call, instant. The `remove_fact` prompt and the "rewritten summary looks broken" check are removed.
- The caregiver page shows the rendered text exactly as she gets it (as today), and the sections with their ✕.

### E. The move
- On deploy, a one-time script renders each account's text from its current sections, and saves it as a new memory version (the old text stays in the history, restorable).
- **Checked before switching the patient:** the old text vs the new one, side by side -- every claim of the old text that came from the sections is in the new one; what's only in the old text is listed for Tomer (expected: the unsourced advice).
- Restoring an old memory version (08) restores its sections; the text is re-rendered from them.

## Files
| File | Purpose |
|---|---|
| `app/agent/memory_update.py` | No consolidation call; the text rendered by code after the tool loop. |
| `app/memory_text.py` (new) | `render_memory`: the sections -> the tutor's memory section. |
| `app/agent/memory_tools.py`, `prompts/memory_update.yaml` | `set_focus`; what works / to avoid from the session; replace to merge. The consolidation and `remove_fact` prompts removed. |
| `app/agent/memory_edit.py`, `app/caregiver_api.py` | Remove an item and re-render, no model call; restore re-renders. |
| `app/schemas.py` | `ConsolidatedMemory` removed. |
| `tests/` | Every section item appears in the text; nothing else does; the order and caps; `set_focus`; removing re-renders without a model call; the memory update makes no consolidation call. |
| `docs/tools.md` | Regenerated (`set_focus`). |

## What was built (2026-10-19)
- `app/memory_text.py` `render_memory`: "you have talked N times", last time (the latest summary), then the sections in a fixed order, newest first, capped; empty sections left out.
- The memory update: no consolidation call (one model call fewer per session); `set_focus` (2-4 points; the old ones kept if not called); what works / to avoid only from this session, with what happened; "every item reaches the tutor word for word". Memory update prompt 0.12; `ConsolidatedMemory` and the `remove_fact` prompt removed.
- Caregiver edits: removing an item and restoring a version re-render the text by code -- no model call; the remove endpoint no longer needs the models (not paused-gated).
- `docs/tools.md` regenerated (`set_focus`; the overview).
- **The move:** each account's text rendered and saved as a new memory version (`migrate16-...`), the old text in the history. The patient's comparison (dry run first): only in the old text -- the unsourced "give him time to self-monitor" advice, a recall instruction, and three points from older session summaries (his age and stroke are in his profile anyway); only in the new text -- 19 checked items the old text had dropped. ~250 -> ~480 words.
- Tests: `test_memory_text.py` (3); the memory, wiring and caregiver tests updated (no consolidation reply). `pytest`: 296 passed.
- Note: a wrong item in the sections now reaches the tutor as written -- removing it on the caregiver page is instant.

## Done when
- [x] The tutor's memory text is assembled by code from the sections; no item is dropped and nothing is added.
- [x] Focus points come from `set_focus`; "what works" and "what to avoid" fill from his sessions.
- [x] Removing a fact on the caregiver page is instant and needs no model call.
- [x] The patient's old and new texts were compared before the switch.
- [x] `pytest` passes.

## Commit
`Sub-plan 16: the tutor's memory built by code from the checked sections`
