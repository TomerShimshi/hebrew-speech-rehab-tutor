# Sub-plan 05: Next-class builder (SUMMARY_MODEL call #3) + ClassPlan

Part of the [master design](00-master-design.md). Depends on [04](04-memory-update.md) (memory per account) and [4.5](04.5-memory-reset.md) (reset).

## Goal
After the memory update, a second agent call writes a **concrete lesson plan for the next session**. The tutor then follows that plan instead of improvising:
- one main goal, rotated across days
- a few **uncued test items** to measure progress
- practice items with ready hints
- a short activity and conversation topics
- homework
- an easy fallback for when he's tired

It's built around **his** actual difficulty (from the assessment) and **his** life (from the memory).

## Out of scope
- games data in the plan and homework (06)
- web search for new techniques (07)
- viewing or editing plans and therapist goals in a UI (08); for now the therapist's goals come from the profile in the bucket
- pointed Hebrew (niqqud) target words on screen (09)

## Design decisions (2026-10-02, after 04/4.5)
- **Built for Dad's real profile.** His assessment shows mild, high-level difficulty: retrieving **proper names** (people, places), organizing longer speech, and higher-level language. His therapist recommends exactly those three areas. So the plan's main goal **rotates across days** between:
  1. `name_retrieval`: names of people and places from **his life** (taken from memory: family, towns, trips), plus well-known Israeli places and public figures
  2. `discourse`: telling a story in order, explaining how to do something step by step, summarizing something he watched or read
  3. `high_level_language`: naming as many items in a category as he can ("cities in the Galilee"), synonyms, precise word choice, idioms and sayings
  4. `conversation`: an easier "free" day after a hard one, or when his mood was low

  The builder sees the last 5 plans' goals, so it can rotate and avoid repeating itself.
- **Session 1 is an intro session**, built from a fixed template (`prompts/intro_plan.yaml`) with no LLM call. The first time an account has no memory, or right after "forget memory", the session is "getting to know you": the people in his life, places he loves, his work, his hobbies. This **seeds the memory with his personal names and places**, which later name-retrieval sessions practice. A light, informal check of naming is included, with nothing that feels like a test.
- **Progress measurement:** each regular plan has a small **probe**: 3–5 items asked **without hints first**.
  - **Treated** items are words due in the word bank, already practiced.
  - **Untreated** controls are new items of the same kind, never practiced.
  - The memory update (04) gets **the plan the session used** and records each probe result with `probe: true` (`uncued` / `cued` / `failed`). The session doc gets `probe_results`.
  - Over the weeks, this shows whether *practiced* names improve faster than unpracticed ones. That's the "real progress" view the caregiver page (08) will graph.
- **One structured-output call, no tool loop.** The builder's only "write" is a single plan. Its inputs (the profile, memory, word bank due list, recent plans and summaries, and the curated techniques) are small, so they all go **in the context**. Same principle as 04: reads in the context, writes through validated output. This is one call through the same retry/fallback chain. A tool loop arrives in 07, when web search becomes a tool.
- **Validated schema, `ClassPlan`** (Pydantic, used as `response_schema`):
  - `plan_type`: `intro` | `regular`
  - `primary_goal`: `{type, description}`
  - `recall_from_last_time`: one sentence to use in the greeting
  - `warmup`: one easy opener at his level
  - `probe[]` (≤ 5): `{target, kind: treated|untreated, elicit}`. `elicit` is how the tutor asks it without hints, e.g. a description.
  - `practice[]` (≤ 8): `{target, elicit, hint_meaning, hint_first_syllable, sentence_completion}`
  - `activity`: for discourse or high-level days, e.g. "explain step by step how you make shakshuka"
  - `conversation_topics[]` (≤ 3), from his interests
  - `homework`: one small task
  - `fatigue_fallback`: an easy, sure-success activity
  - `avoid[]`: from the memory's `what_to_avoid` and the therapist's notes
- **Where plans live:** `patients/{email}/plans/next` holds the plan for the coming session. When a session starts, the plan it uses is **copied into the session doc** (`class_plan`), so the memory update and later analysis know exactly what was planned. "Forget memory" (4.5) also deletes `plans/next`, so the next session is an intro again.
- **When it runs:**
  - **In `/end`**, right after a successful memory update, inside the same request (the browser doesn't wait). The shared time budget grows from 240 s to 300 s; Cloud Run's timeout is 600 s.
  - Session doc fields: `plan_status: pending → done | failed`, `plan_model`.
  - **The hourly sweep** also builds plans that failed, or whose session's memory finished without one.
  - **If there's no plan at `/start`**, the session never blocks:
    - no memory → the intro template
    - otherwise → **no plan section**; the tutor follows the generic structure from 02, exactly as today
- **The tutor follows the plan** (`prompts/tutor.yaml` v1.0, rendered into the existing `{class_plan}` placeholder as "TODAY'S PLAN"):
  - **The plan guides; his chosen topic still leads.** She weaves the practice into what he wants to talk about.
  - **Probe items come first in the focused part, uncued.** Hints are allowed only after a real attempt, and then the hint ladder applies.
  - **Never read the plan aloud**, never say "test", and never mention that she has a plan.
  - Give the homework at the end.
  - Use the fatigue fallback if he struggles.
- **Prompts in English, content in Hebrew:**
  - `prompts/next_class.yaml`: the builder instructions, including rotation rules, his level, using his own names, a cap on hard items, and Hebrew correctness of the hints (the first syllable as spoken, "טְבֶ…", never the letter's name)
  - `prompts/therapy_techniques.yaml`: a short curated set of techniques per goal type, given to the builder as context
- **Privacy:** like 04, the plan is built from the memory and profile; nothing personal goes into the repo.

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `ClassPlan` and its item models; `WordResult` usage gains `probe`. |
| `app/agent/next_class.py` | `build_next_plan(store, client, settings, pid, sid)`: context → one structured call → validate → save `plans/next` and the session's `plan_status`. Never raises. |
| `app/class_plan.py` | `render_class_plan(plan) -> str` for the tutor prompt; `intro_plan()` from the template; `plan_for_session(store, pid)` (the next plan, the intro, or none). |
| `prompts/next_class.yaml`, `prompts/intro_plan.yaml`, `prompts/therapy_techniques.yaml` | Builder instructions, the fixed intro plan, and the curated techniques. |
| `prompts/tutor.yaml` | v1.0: how to follow TODAY'S PLAN. |
| `prompts/memory_update.yaml` + `app/agent/memory_tools.py` + `app/agent/memory_update.py` | The memory update receives the session's `class_plan`; `record_word_result` gains `probe: bool`; `probe_results` are saved on the session. |
| `app/store.py` | `get_next_plan`, `save_next_plan`, `recent_plans(pid, n)`; `forget_memory` also clears `plans/next`; the sweep finds sessions whose `plan_status` is pending or failed. |
| `app/main.py` | `/start` renders the plan and copies it into the session; `/end` runs memory → plan; the sweep builds missing plans. |
| `tests/` | Schema validation; the intro on a fresh or reset account; rendering; rotation input (recent goals in context); the plan saved and copied into the session; the plan never blocks `/start`; probe results recorded; failure → `failed` → sweep retry. |

## Tasks
1. [x] Schemas, `class_plan.py` (render + intro template), store methods, with tests.
2. [x] `next_class.yaml` + `therapy_techniques.yaml` + `build_next_plan`. **Dry run** on Tomer's real memory and show the generated plan for review.
3. [x] Probe recording in the memory update (plan in context, `probe` flag, `probe_results`).
4. [x] Wire `/end` → memory → plan, the sweep, and `/start` (render + copy); tutor prompt v1.0; reset clears the plan.
5. [x] Local / remote end-to-end: reset → intro session → plan built → next session follows it (asks the probe items uncued, then practices, gives homework).
6. [x] Commit and push.

## Manual steps for Tomer
- Review the first generated plan (task 2): is it at the right level for Dad, and are the hints correct Hebrew?
- Optional: add a line with the therapist's current goals to the profile file and re-run `setup_gcp.sh` to upload it.

## Done when
- [x] `pytest` passes (103 tests).
- [x] A fresh or reset account gets the **intro** session, and afterwards the memory holds his people and places.
- [x] After a session, `plans/next` holds a valid plan whose main goal differs from the last 1–2 days unless there's a reason.
- [x] The next session visibly follows it: probe items asked without hints first, practice with the planned hints, homework at the end, and the plan never read aloud.
- [x] The probe results appear on the session doc and in the word bank.
- [x] A model outage never blocks a session (no plan → generic structure) and is retried by the sweep.

## Commit
`Sub-plan 05: next-class planner agent and ClassPlan-driven sessions`

## Notes from building it (2026-10-02)
- **The first dry run** (on Tomer's real memory) produced a plan with **0 probe items**. The small fallback model (`3.5-flash-lite`) ignored the instruction. Fixes: the schema sent to Gemini carries `minItems: 3, maxItems: 5` for `probe`, the prompt marks the probe as REQUIRED every session, and a plan with fewer than 3 probe items is rejected (`plan_status: failed`, retried by the sweep). The second dry run produced 3 probe items, correct first-syllable hints ("עֶזְ..." for עזרה מקצועית), and a natural Hebrew recall line.
- **The free-tier quota (`429 RESOURCE_EXHAUSTED`)** showed up during development for 3.8-flash, 3.7-flash and flash-latest. Unlike a 503 spike, a quota doesn't recover in seconds, so **429 now skips straight to the next model** (like 404). Dad's daily use (about 3–4 text calls) is far below the limits; development runs are what exhaust them.
- **Open question for Tomer:** famous-city probes (Tel Aviv, Jerusalem, Haifa) are probably too easy for Dad, so he'd hit the ceiling. Once his intro session seeds personal names and places, the builder uses those. A rule to prefer less-famous places could be added.
- **Prompt rendering:** a section whose placeholders are all empty is now dropped **entirely**, including any fixed guidance text. So without a plan, the tutor doesn't see the "how to use today's plan" rules either.
- **Verified on real Firestore** (throwaway account, deleted): next plan save/read, recent plans, pending plans, forget-memory clears the plan, delete-account.
- **Unnatural topic shifts (Tomer's session JJzPpZ9s, 2:45 long).** Mid-story, the tutor jumped to a check-in item (whose answer, "Tel Aviv", he had *just said himself*). The story's ending, summary and opinion never came. She started the closing at about 2 minutes, two of three check-in items were never asked, and her closing ("say the city again") confused him. Root cause: the prompt read as a **checklist of stages** and the plan as a **list of items**. **Tutor prompt v1.1** restructures the session around conversation flow:
  - **one thread at a time** (help him finish a story: next, ending, summary or opinion)
  - **bridge every topic change** with a linking or gentle explicit sentence
  - the plan is a **menu, not a script**; check-in items come at natural moments, never mid-story, and **don't count if he already said the answer**; it's fine not to reach every item
  - **she never starts closing on her own**: the browser sends the wrap-up note at **about 9 minutes, at a quiet moment** (not while either side is talking); she closes early only if he asks or is tired
  - a natural closing: summary + specific praise + homework + goodbye, with no "say it again"

  **Replayed live** with the same plan and story: at the exact point of the old jump, she now stays with the story ("ואיך היא מסתגלת לחיים החדשים…?", "And how does she adapt to the new life…?").
- **Readable prompt archive names:** `<Israel date_time>_<plan type-goal>_<sid8>.md`, e.g. `2026-10-03_16-47_regular-discourse_PLYI39zF.md`. `tzdata` was added, since the slim image has no time-zone database. The full session ID is in the file header.
- **Builder prompt v0.2:** lines in the tutor's voice use the feminine for herself and the masculine for him; untreated check-in items must match the treated items' difficulty (no Jerusalem / Tel Aviv / Haifa / Eilat-level answers).
- **Still a quiz feel (session aXp8RV0J, prompt v1.1).** The Caesarea thread was natural. Then, right after an emotional moment ("the wind, the sun, the waves"), she asked two back-to-back trivia questions about unrelated cities. She also said "נכון מאוד! עכו" ("Exactly right! Akko") to an answer he never gave ("הכל?"), and promised to remind him tomorrow, which she can't do. Fixes:
  - **Builder v0.3:** check-in items must be **connected** to his life or the session's topics (e.g. near places he loves), each with a Hebrew **`bridge`** lead-in, and no stand-alone quiz questions.
  - **Tutor v1.2:** at most one name question per topic, never two in a row; turn each one back into conversation ("היית שם פעם?", "Have you been there?"); say "נכון" (correct) only if he actually said the name; never promise anything outside the session ("אשאל אותך על זה בפעם הבאה", "I'll ask you next time").
  - **treated/untreated is decided by code** (in the word bank → treated), never by the model. The dry run had labelled all four items "treated", including Haifa, which was never practiced.

  Replayed live: the promise, the false "correct" and the follow-up are all fixed, and the transition is now topic-linked.
- **Status at commit (2026-10-03):** verified on the remote with Tomer's account:
  - reset → intro (Caesarea, anime and other personal facts seeded into memory)
  - regular plans built automatically (discourse, then name_retrieval)
  - sessions followed them, and `probe_results` were recorded (Caesarea uncued/treated; Akko cued with low confidence; Zichron uncued)

  The conversation naturalness was improved twice (v1.1 flow, v1.2 names-in-conversation). Tomer will keep tuning it in later rounds. The "outage never blocks" item is covered by tests and seen live (fallback to `3.5-flash-lite` under quota).
