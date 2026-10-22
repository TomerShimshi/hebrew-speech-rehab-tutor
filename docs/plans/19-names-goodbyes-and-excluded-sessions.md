# Sub-plan 19: Hearing the names right, a clean goodbye, and leaving a conversation out

Part of the [master design](00-master-design.md). After [18](18-one-question-greeting.md). (Was 13.5, then 14, then 15, then 16, then 17, then 18, until 2026-10-22.) Requested by Tomer (2026-10-11).

> **Revisit after 13, 13.5 and 14 are done.** 13 changes how a session runs (steps, a record of what was done, and maybe an optional gate on `end_session`). Parts of this plan depend on it: the noise filter off during the names game needs 13's "current step"; the goodbye rules must fit 13's `end_session` (gated or not). Re-read and adjust this plan before building it.

## Why
- **A names-game answer misheard live (a patient session, 11.10).** He said a name correctly. Gemini, listening to the session's recording afterwards, heard it clearly (95%+ sure). But the live model answered as if he hadn't found it, and the live transcript wrote something else. So the game recorded "failed" for a name he found.
  - A possible contributor (**not proven**, to test): the noise filter holds back his audio while she is still speaking, so a quick answer right at the end of her question may lose its start.
- **A goodbye loop (Tomer's test session, 11.10).**
  - At 6.6 minutes he said "להתראות". Gemini's transcript wrote **"מה הליטרות?"**; the browser caption had it right.
  - The page decides whether he said goodbye from **Gemini's transcript only** (`s.lastUserText = u.gem` in `static/app.js`), so it refused her `end_session` ("he has not said goodbye yet").
  - She said goodbye again, he said goodbye again, and so on, until he pressed the end button.
- **No way to leave one conversation out.** A test session on the patient's account, a session that went wrong (noise, a misunderstanding, a technical problem), or someone else speaking can teach the memory wrong facts. Today the only tools are removing memory items one by one, restoring the whole memory to an earlier version, or a full reset. Tomer wants a button on the session itself.

## Goal
1. **The names game is scored right**, even when the live model mishears him.
2. **No goodbye loops.** When he says goodbye, she hangs up after her own goodbye, even if one transcript mishears him.
3. **"Leave this conversation out"** (not a delete): a button next to each conversation on the caregiver page. The conversation stays visible, marked, and can be put back, but nothing learns from it any more.

## Design

### 0. Steps mode by default: moved to [13.5](13.5-tool-based-planner.md) (2026-10-12)

### A. Hearing the names game right
- **Live (prompt):** in the names game, if his answer is unclear, or sounds only similar to the name, she asks once ("סליחה, לא שמעתי טוב, תגיד שוב?") before saying the name. A misheard right answer then gets a second chance, and the second try still counts as "on his own".
- **Live (code):** while the names game step is active (13's current step), the noise filter is off, so a quick answer isn't cut. This also tests the filter suspicion.
- **After the session (code, the main fix):** the names game's answers are re-checked from the recording. The memory update sends the recording to Gemini with that session's game questions and names, asking what he said for each. Listening afterwards is clearly better than live (it heard the misheard name correctly).
  - Where the recording disagrees with the live result, the recording wins, and the result is marked `rechecked`.
  - A live mishearing is reported as a tutor issue (`misheard`), so the family sees it.
  - Without a recording (recording off), the live result stays, as today.

### B. The goodbye (page code)
- **Both transcripts count.** "Did he say goodbye?" checks Gemini's transcript **and** the browser caption of his last line, and also the line before it (a goodbye split across two lines).
- **One refusal at most.** If she calls `end_session` and it's refused for a missing goodbye, the next call is accepted once he has said anything at all after her goodbye. Two people don't say goodbye three times. The silence nudge after her goodbye still ends it, as today.
- **Logged:** each refusal and its reason go into the page log (already there), and the session records `goodbye_refusals` so loops show up on the caregiver page.
- **Wider goodbye words:** "ביי", "יאללה ביי", "תודה רבה, להתראות", "נדבר", "נתראה", "שיהיה לך…" (a wish at the end, if it follows her goodbye).
- **Fits 13:** if 13 adds its optional gate ("not before the wrap-up note"), the gate comes first; this rule only decides whether he said goodbye.

### B2. Transcription markers (added 2026-10-15)
- **Seen in a test session (15.10):** Gemini's transcription of her voice twice wrote `<no speech detected>` at the end of her line (a pause or breath with no speech). The page adds whatever text arrives, so it showed in the captions, the saved transcript and the caregiver page, and the memory agent reads it too. He never heard it.
- **Fix (page code):** drop any text in angle brackets (`<...>`) from both transcripts (hers and his) before it is shown or saved. Real Hebrew speech never comes in that form.
- **The memory agent's transcript** (`format_transcript`) drops them too, for sessions saved before the fix.

### C. Leaving a conversation out (caregiver page + code)
- **The button:** on each conversation on the caregiver page, "🚫 לא לכלול בזיכרון ובתכנון", with an inline confirm. When a conversation is left out, it shows a "לא נכלל" chip, and the button becomes "↩ להחזיר".
- **Stored:** `excluded: true`, `excluded_by`, `excluded_at` on the session. Nothing is deleted: the transcript, recording and prompt stay.
- **What a left-out conversation no longer feeds:**

  | Where | Today | When left out |
  |---|---|---|
  | Memory update (incl. the hourly sweep) | runs after each session | **skipped** (`memory_status: excluded`) |
  | His words as "his data" (the grounding guard, 8.5) | last 3 transcripts | not counted |
  | The memory's recent summaries | last 5 | its summary removed |
  | The names game's results (12) | in the set | its results removed from the set |
  | His pace (12b) | last 5 sessions | not counted |
  | "When you last spoke" | last real session | not counted |
  | Progress graphs and the therapist export | all sessions | not shown (a "show left-out" toggle on the page) |
  | Voice tuning (09) | after each session | not counted |
  | Daily reminder "already practised today" (11) | any session that day | still counts: he did talk |
- **If it was already processed,** its effect on the memory has to be undone. The memory before it is saved (`memory_history/{sid}`), so:
  - **It's the latest processed conversation:** the page offers "also restore the memory to before this conversation" (the existing restore, with a backup). This is exact.
  - **Later conversations were processed after it:** restoring would also throw away what they taught. The page says so and offers only the cleanup that can be done exactly: its names-game results and its summary. Its memory items can be removed one by one with the existing ✕.
- **Then the next lesson is rebuilt** without it (the existing rebuild), if it was the session the current plan was built after.
- **Putting it back** clears the flag. If it was never processed, it's processed then (as "process now" does today). If its memory was restored away, it is processed again.

## Files
| File | Purpose |
|---|---|
| `prompts/tutor.yaml` | Ask once more on an unclear names-game answer. |
| `static/app.js` | The noise filter off during the names game step; goodbye: both transcripts, the last two lines, one refusal at most, wider words. |
| `app/agent/memory_update.py`, `app/audio_store.py` | Re-check the names game from the recording; the `misheard` tutor issue. |
| `app/transcripts.py`, `app/main.py` | `goodbye_refusals` on the session (from the page's `/end`). |
| `static/app.js`, `app/agent/memory_update.py` | Drop `<...>` transcription markers (B2). |
| `app/store.py` | `excluded` on sessions; the sweep and pending queries skip them. |
| `app/agent/memory_update.py`, `app/agent/next_class.py`, `app/session_prompt.py`, `app/voice_tuning.py`, `app/caregiver_api.py` | Skip left-out sessions (the table above). |
| `app/check_in_set.py`, `app/agent/memory_edit.py` | Remove a session's names-game results and summary; restore before it. |
| `app/caregiver_api.py`, `static/caregiver.*` | Exclude / put back, the chip, the restore offer, the "show left-out" toggle. |
| `tests/` | The recheck (agree / disagree / no recording); the goodbye rules (a misheard goodbye, one refusal, two lines); every place in the table; restore when latest vs not; putting back. |

## Done when
- [ ] A names-game answer the live model misheard is corrected from the recording, and shown as a tutor issue.
- [ ] A goodbye misheard by one transcript still ends the session after her goodbye; never more than one refusal.
- [ ] No `<...>` transcription markers in the captions, the saved transcript or the memory agent's input.
- [ ] A conversation left out is visible and marked, but changes nothing in the memory, plan, names game, pace, timing or graphs; putting it back works.
- [ ] `pytest` passes.

## Commit
`Sub-plan 19: hearing the names right, a clean goodbye, and leaving a conversation out`
