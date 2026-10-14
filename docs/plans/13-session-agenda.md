# Sub-plan 13: A session that follows its agenda

Part of the [master design](00-master-design.md). After [12](12-own-names-and-check-ins.md). Requested by Tomer (2026-10-11). Followed by [13.5](13.5-tool-based-planner.md), [14](14-sequencing-stories.md) and [16](16-names-goodbyes-and-excluded-sessions.md).

## Why
Sessions keep ending well before the ~9-minute wrap-up note, because the tutor starts the closing on her own:
- **Tomer's test session (11.10, prompt 1.10):** she closed at 6.2 minutes ("נהניתי לשמוע…") without being asked. 12b (no wrap-up questions, a reserve, a plan sized to his pace) helped the flow, but didn't stop it.
- **A patient session (11.10, prompt 1.10, a plan built before 12b with no practice items and no reserve):** she closed at 3.5 minutes. The names game took ~1 minute, the main activity ~1.5, and then the plan "felt" done. The memory agent flagged it as `early_goodbye`.
- **Earlier sessions:** 7 of 8 closed on her own between 2.9 and 6.2 minutes (see 12).

## Goal
The session lasts until its agenda is done or about 9 minutes have passed, not until it "feels" done. She never starts the closing before the wrap-up note unless he asks to stop or is tired.

## Why not only the prompt
Prompt 1.5 → 1.10 tightened the "don't close early" rules five times (time notes, no wrap-up questions, "no" ends a topic, not the session), and she still closed at 3.5–6.5 minutes. In agent-led voice conversations, the common practice is to **drive the conversation as explicit steps from code** and **gate the end of the call in code**:
- Each step gets focused instructions, and code moves to the next step ([Pipecat Flows](https://docs.pipecat.ai/pipecat-flows/introduction.md), [LiveKit Agents tasks](https://docs.livekit.io/agents/logic)).
- The end-call tool is accepted only when conditions hold (the agenda done, a minimum duration, a clear goodbye), and "no", "okay" or "thank you" are not treated as goodbyes ([Edesy](https://edesy.in/blog/why-ai-voice-agent-hangs-up-too-early-fix-2026), [Vapi](https://support.vapi.ai/t/33147177/having-issues-with-call-ending), [Smallest](https://docs.smallest.ai/voice-agents/platform/troubleshooting/common-issues/agent-issues)).

The prompt still matters (the role, the rules, the whole plan for context), but it no longer decides alone when the session is over.

## Design: an agenda in the page, a `next_step` tool for her
- **The agenda** is built in code from TODAY'S PLAN at session start (the page gets it from `/api/session/start`): opening → names game → each practice item → the activity → the reserve items → (wrap-up) closing. Each step has a short instruction ("Practice item 2: ask … answer …").
- **She sees only the current step as her task.** The system prompt keeps the role, the rules and the whole plan for context. The step itself comes from the page: the first step in the start note, the next one in the reply to her tool call.
- **`next_step(done: str, how_it_went: str)`:** a second live tool. She calls it when a step is finished (SILENT: no reply needed). The page answers with the next step's instruction and "N steps left; the session is NOT over".
  - This tells the page exactly what's done (the open question from 12b), with no guessing from her words.
  - It's also a running record of the session for the memory agent and the caregiver page (which steps were done, and how).
- **When the agenda runs out before ~9 minutes,** the page gives open threads: follow-ups on what he said, the reserve topics, his interests.
- **`end_session` stays as it is (no gate in this round; decided with Tomer, 2026-10-11).** First we test whether the steps alone keep her going. Her closing sentences come before the call anyway, so the steps are what has to work.
- **The wrap-up note at ~9 minutes stays** as the only way into the closing step.
- **The silent time notes (12)** stay as they are.
- **Rolled out on Tomer's account first** (a per-account setting), then the patient's.

## Verify before building (a short live test, as for the silent notes in 12)
- Gemini Live (3.8) calls a SILENT tool mid-conversation reliably, at the end of a step.
- After the tool reply, she keeps talking naturally (no pause, no repeat, no reading the instruction aloud).
- If tool calls turn out unreliable, the fallback is a **live guard**: the page catches a closing pattern in her words before ~8 minutes ("נהניתי לשמוע", "לקראת הפעם הבאה") and sends a note at once: continue with the current step.

### Live test results (2026-10-11, gemini-3.8-live, text standing in for his speech)
1. **The tool works and the conversation stays natural.** She called `next_step` at every step (5 of 5), never read an instruction aloud, and moved into each new step smoothly ("בדיוק, עכו! איך נקראת העיר על שפת הכנרת?"). But she called it **too early**: in the same turn as her question, before his answer.
2. **Fixed with the rule** "ONLY after he has answered the step's last question and you have reacted; never in the same turn as asking a question". A 3-question names game then ran exactly right: one at a time, no hints, the name said warmly on a miss. But the step reply was sent **SILENT**, so she ended her turn ("…עכשיו נסכם את המשחק הזה.") and waited for him: a silent gap.
3. **Fixed by sending the reply with `WHEN_IDLE`.** With nothing from him, she started the next step **by herself**, about 3–7 seconds later ("בוא נעשה משחק קצר של שמות…", then "איך נקראת העיר על שפת הכנרת?").

So: `next_step` is NON_BLOCKING, called after his answer and her reaction, and answered with `WHEN_IDLE`.

## Progress (2026-10-11)
- **Built:**
  - `app/agenda.py`: the steps from TODAY'S PLAN (opening → names game → each practice item → activity → game-linked activity → reserve items), the "after the last step" open threads (reserve topics, conversation topics), and the overview for the system prompt.
  - `VoiceSettings.steps_mode` (off by default), a checkbox on the caregiver page.
  - The `next_step` tool, declared only in steps mode.
  - Tutor prompt 1.12: a WORKING STEP BY STEP section, only in steps mode.
  - The first step in the start note. The page hands out each next step and records what she reports (`steps_done`, saved at `/end`).
  - The caregiver page: "שלבים: N מתוך M", with what she reported for each step.
  - The memory agent sees the steps she reported.
- **Not built (as decided):** the `end_session` gate (below).
- `pytest`: 264 passed.

## Tomer's test in steps mode (2026-10-12) and the fixes
6.3 minutes, all 9 steps reported. Three problems:
- **Two separate turns with a gap.** She reacted ("שיהיה המון בהצלחה."), ended her turn and called `next_step`, and the WHEN_IDLE reply made her start a new turn 5–7 seconds later. In the test script this looked like "she goes on by herself"; in a real conversation it sounds like two blobs.
  - **Fix:** `next_step` is now **BLOCKING**. She reacts in one sentence, calls it, gets the reply in ~0.6 s, and continues in the **same turn**. Live-tested: "זה מדויק לגמרי! ⟨tool⟩ איך נקראת העיר על שפת הכנרת?", with no second turn.
- **A name asked twice.** Two of today's names-game names were also in the plan's reserve. The plan is built before the session's game names are chosen (rotation, at session start).
  - **Fix:** at session start, today's game names are removed from practice and the reserve.
- **She closed right after the last step.** A fast talker got through all 9 steps in ~4 minutes. The reply "All the planned steps are done, but it is NOT time to close…" made her close at once.
  - **Fix:** the page never says the steps are done. The plan's open threads (reserve topics, conversation topics) are steps of their own, and after them the page keeps handing out a **follow-up step** ("ask one specific follow-up about something he told you today"). Only the wrap-up note leads to the closing.
- Tutor prompt 1.13. `pytest`: 265 passed.

## Tomer's 12.10 sessions: duplicates, a mechanical feel, a refused goodbye (fixes)
- **The same question twice** (09:56): with the whole plan in her prompt she jumped ahead to the next question, then got it again from the step reply.
  - **Fix:** in steps mode, TODAY'S PLAN in her prompt keeps only the general parts. The questions come only from the page.
- **Her own question, then the step's** (10:16): she reacted first and, by habit, ended on a question of her own; the step then added a second one. She also read a step reply's extra words aloud ("אין צורך במילים נוספות…").
  - **Fix:** she calls `next_step` **first**, before saying anything, then speaks **one** turn: her reaction and the next step. Live-tested: the turn starts ~0.7 s after the call, with no extra question. The step reply is now only the step itself.
- **Mechanical:** every step was a single question and answer, and she moved on even when he said something interesting.
  - **Fix:** a step is a small conversation, with at least one follow-up on his own words. Practice names come **inside a topic** (a new `topic` field on practice items, e.g. "his years at work"). The plan builder prefers fewer, richer items.
- **She agreed to finish, then refused:** the 7-minute time note ("not time to close yet") arrived during the closing he had asked for.
  - **Fix:** no time notes once a closing has started (he asked to stop or said goodbye, the wrap-up note, or the "you may close" reply). The notes also say "unless he asked to stop".
- **Misheard names:** the noise filter is off during the names game (by step in steps mode; for ~2.5 minutes from the game's cue otherwise).
  - Root cause found, **not fixed yet** (Tomer: first try the filter off during the game): when her audio ends while the filter is holding his first syllable, that held audio is never sent.
- Tutor prompt 1.16, plan builder 0.15. `pytest`: 268 passed.

## Optional, only if the steps don't keep the sessions going: gate `end_session` in code
Accepted only if (the wrap-up note was given, or he asked to stop, or he's tired: a `reason` argument) and he said goodbye. Otherwise: "Not ended: it's only N minutes, the session isn't over. Continue with: <the current step>."
- It stops a closing that started anyway from becoming a hang-up, but it can't stop the closing sentences themselves. So after a refused call, the conversation would go on after a goodbye, which is awkward.
- Decide after testing the steps on Tomer's account, from how the sessions end.

## Files
| File | Purpose |
|---|---|
| `app/session_prompt.py`, `app/class_plan.py` | The agenda built from TODAY'S PLAN (steps with short instructions). |
| `app/main.py` | The agenda in the session start response. |
| `app/live_token.py` | The `next_step` tool. (`end_session` with a `reason`: only with the optional gate.) |
| `static/app.js` | The current step, `next_step` handling (reply with the next step), open threads when the agenda runs out, the steps done saved with the session. (The gated `end_session`: only if the optional gate is built.) |
| `prompts/tutor.yaml` | Working step by step: call `next_step` when a step is finished; never close before the wrap-up note. |
| `app/caregiver_api.py`, `static/caregiver.*` | Which steps a session did (and how), on the session. |
| `app/schemas.py`, `app/caregiver_api.py` | The per-account setting (agenda mode on / off). |
| `tests/` | The agenda from a plan (with and without a names game, practice, reserve); the setting. |

## Done when
- [ ] A live test shows `next_step` works mid-conversation, and the conversation stays natural.
- [ ] On Tomer's account, then the patient's: sessions reach the wrap-up note (or finish the whole agenda) unless he asks to stop.
- [ ] The caregiver page shows which steps each session did.
- [ ] `pytest` passes.

## Commit
`Sub-plan 13: a session that follows its agenda`
