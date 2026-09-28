# Sub-plan 05: Next-class builder (SUMMARY_MODEL call #3) + ClassPlan

Part of the [master design](00-master-design.md). Depends on [04](04-memory-update.md).

## Goal
Once memory has been updated, a second agent call builds the **next session's lesson plan** (`ClassPlan`) and the rendered Live prompt. Each session then follows real therapy structure: one primary goal, a short fixed word test to measure progress, a clear fallback for when he's tired, and homework. The exercises depend on his `speech_profile`.

## Out of scope
Games data (06), web search (07), editing through the UI (08). The profile is edited in the Firestore console for now.

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `ClassPlan`: `plan_type` (baseline/regular), `speech_profile`, `primary_goal`, `probe_set{treated[5], untreated[5]}`, `targets[{word, pointed_form, root, semantic_cue, syllable_cue, sentence_completion}]`, `script_lines[]`, `automatic_items[]`, `conversation_topics[]`, `fatigue_plan{easy_fallback}`, `avoid[]`, `homework{games[], family_practice_line}`, `recall_from_last_time`. |
| `prompts/next_class.yaml` | Planner instructions: one primary goal per session and rotate activities across days; pick **baseline** for the first 2 sessions; choose exercises by profile (unknown means low-risk activities only; aphasia uses the cueing hierarchy with root and CV-syllable cues plus SFA and scripts; apraxia uses "watch, listen, say it with me" and repetition; dysarthria uses breath, loudness and rate); respect `therapist_goals` and `avoid`; pick due words from the word bank. |
| `prompts/therapy_techniques.yaml` | A curated knowledge base (the techniques from the master design) with Hebrew example phrasings, automatic sequences (counting in the feminine form, days, months) and a song list to confirm with the family. |
| `app/agent/tools.py` | Adds `get_therapy_technique(situation)`, `read_therapist_goals()`, `read_baseline()`, `read_word_bank(filter)`. |
| `app/agent/next_class.py` | Runs call #3 after #2 and saves `memory/current.next_plan` = {ClassPlan, rendered prompt, `prompt_version`}. Status moves to `next_plan_ready`. |
| `prompts/tutor.yaml` | v0.2 renders the ClassPlan phases: check-in → warm-up → probe (uncued, same scoring) → main block → functional/script → end on a success with homework. |
| `app/main.py` | `/api/session/start` uses the stored `next_plan`. The first-ever session gets a default baseline plan. |
| `tests/` | ClassPlan schema validation, baseline chosen for sessions 1–2, and the rendered prompt contains the plan sections. |

## Manual steps for Tomer
In Firestore `patients/abba`, fill in `speech_profile`, `therapist_goals`, `avoid`, family names, interests and `language_history`. Ideally his speech therapist confirms these.

## Done when
- [ ] `pytest` passes.
- [ ] Sessions 1–2 run as baseline sessions, and later sessions follow their plan (probe words asked, one main goal, homework given).
- [ ] Changing `speech_profile` visibly changes the next plan's exercises.

## Commit
`Sub-plan 05: next-class planner agent and ClassPlan-driven sessions`
