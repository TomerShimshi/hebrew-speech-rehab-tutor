# Sub-plan 18: She listens and asks well -- a reaction to every answer, one question at a time, never a question he answered

Part of the [master design](00-master-design.md). After [17.5](17.5-practicing-the-missing-areas.md), before [19](19-observability.md). Requested by Tomer (2026-10-22); extended 2026-10-23 after the patient's session of 22.10. **Built 23.10 as prompts (tutor 3.6): B, C and a stronger reaction rule; A (the `reaction` parameter) tested and shelved -- see Results.**

## Why
- **She sometimes ignores his answer (22.10, the patient):** after the story step he said "או, כל הזמן... הרבה פעמים", and her next turn went straight to the next topic -- not a word about it. This is the step change fixed by wording in 21.10 (tutor prompt 3.5): better (1 miss in 6 step changes in that session, ~1 in 3 before) but not solved. The text-mode evals can't reproduce it (21.10): it shows with voice, when the next step arrives and pushes the reaction out. He must never feel ignored.
- **She asked a question he had answered (22.10):** "איזה מקום נוסף בחרת להמליץ עליו?" at 0:32 -- he answered with a story (a hard climb in the army) whose name got cut off ("...אז קוראים לו"); she stayed with the story, then at 2:04 asked the same question again, word for word, as if he hadn't answered.
- **Double questions, in the greeting most of all (found by the evals' judge, 22.10):** scoring by meaning showed double questions the old "?" count missed (0 by punctuation vs 3-8 by meaning, per variant); most are the greeting: "איך עברו עליך היומיים האחרונים? הצלחת קצת לנוח ולהתרענן?" -- in almost every run. The likely cause: the opening gives her a recall line and an opener, and she makes both questions. "X, או אולי Y?" also still appears.
- One question at a time, and being heard, are clinical points for him (one thing to hold in mind; motivation), not only style.

## Goal
1. **A reaction to his answer at every step change**, enforced, not only asked for.
2. **Never a question he has answered** -- an answer cut short is helped, not re-asked.
3. **The greeting asks one question**; no glued "X, או אולי Y?".
4. **Measured:** the evals for what text mode can show, the audit of his real sessions for the rest.

## Design

### A. The reaction is part of next_step (code) -- tested, shelved (23.10)
- `next_step` gets a **required** parameter `reaction`: the one sentence (Hebrew) she says to what he just said. She writes it before she sees the next step -- the point: today the next step arrives and pushes the reaction out; here it's composed first.
- **The page's reply puts it first:** her own sentence, then the step ("first say your reaction ... then CURRENT STEP: ..."), worded so nothing meant for her is read aloud (checked in the evals: `reads_instructions`).
- **Checked by the page:** an empty or token reaction (one word, a generic "בוא נמשיך") is held -- "react to what he said, then call again".
- **Logged:** the reaction is saved with the step's report (`steps_done`), so the audit can check she actually said it (her first words after the step change vs the reaction she wrote).
- **Not** "react first, then call": tested 21.10, it brought back double questions.

### B. Never a question he answered (prompt)
- In "HOW YOU TALK": if he answered with a story or an example but the name or the point didn't come, that IS his answer -- help him find it ("איך קראו למקום שעליתם אליו?"), or go on; never repeat the original question as if he hadn't answered. Also when she comes back to a topic after following him elsewhere.

### C. One question in the greeting (prompt + the opening step)
- `OpeningStep`: hello, the recall as a STATEMENT ("בפעם הקודמת סיפרת לי על..."), then ONE question. The builder's `recall` is written as a statement, its `opener` as the one question.
- The start note (`app/session_prompt.py`): checked that it doesn't invite a second question.
- "X, או אולי Y?": if the judge still finds it after C, a second example in the one-question rule.

### D. Measuring
- **Evals (text mode):** the opening replayed (the first turn), double questions per step kind, `reads_instructions` with the new reply, the reaction said vs written.
- **Before / after on his real sessions** (`evals/session_metrics.py`, N+1): the baseline measured before building (below), then the same measures on every session after the fix -- `--split-version` with the new tutor prompt version.
- **Audit of real sessions** (`evals/audit_step_changes.py`): reacted first, by meaning; and with A, the written reaction vs her first words. Run on his sessions after deploying, and on the test account first.

### What was built instead of A (23.10)
- The tutor prompt's step rules: EVERY answer of his gets a reply to what he said, above all at a step change; a story gets a sentence about ITS content, not a generic "יופי"; the reaction comes first even when the reply says what to say next.

## Results (23.10)
- **Baseline** (`session_metrics`, the patient's 6 sessions 15-22.10): no reaction at 9/29 step changes (31%), double questions 8/128 turns, greeting 0/6, repeated questions 2 (the names game's repeats excluded).
- **Replay** (`evals/replay_turns.py`: each flagged turn replayed on Gemini Live from the real conversation, 2 runs): **B fixed** -- asked again 2/4 with 3.5 ("איזה מקום נוסף עלה בדעתך?"), 0/4 with B (she helped him find the name instead). **A not reproducible in text** -- at the 9 moments she skipped it for real, 3.5 reacted in 7/9 replayed step changes; A's parameter brought a reaction said twice, a turn with only the reaction, and an English "understood." -- shelved. The double questions didn't reproduce either (0/8 both).
- **Next:** the real check is his sessions on 3.6 -- `python -m evals.session_metrics --account <email> --split-version 3.6`. If the reaction misses stay, revisit A with his recorded audio as the replayed answer (closest to the voice-only failure).

## Files
| File | Purpose |
|---|---|
| `app/live_token.py` | `next_step`'s required `reaction`. |
| `static/app.js` | The reply puts her reaction first; a token reaction is held; the reaction saved in `steps_done`. |
| `app/transcripts.py` | `reaction` on a step report. |
| `prompts/tutor.yaml` | The step-change rule with the reaction field; never a question he answered; the greeting shape. |
| `app/steps.py`, `app/agent/plan_tools.py` | The opening's shape; `recall` as a statement. |
| `evals/` | Reaction said vs written; double questions per step kind. |
| `tests/` | The tool's schema; the page's reply; the saved reaction; the opening's rules. |

## Done when
- [ ] Every step change carries a written reaction, and the audit shows she says it (her first words) in (nearly) every one.
- [ ] No instructions read aloud with the new reply (evals).
- [ ] No question repeated after he answered it (the audit / the memory agent's tutor issues).
- [ ] The greeting has one question in (nearly) every run (evals), and in his sessions.
- [ ] `pytest` passes.

## Commit
`Sub-plan 18: she listens and asks well -- a reaction to every answer, one question at a time`
