# Sub-plan 18: One question at a time -- in the greeting too

Part of the [master design](00-master-design.md). After [17.5](17.5-practicing-the-missing-areas.md), before [19](19-names-goodbyes-and-excluded-sessions.md). Requested by Tomer (2026-10-22). **To plan in detail and build later.**

## Why
- **Found by the evals' judge (22.10):** scoring the step-change test runs by meaning (`evals/score_step_change.py`, `prompts/eval_judge.yaml`) showed double questions the old "?" count missed entirely (0 by punctuation vs 3-8 by meaning, per variant). Most are in **the greeting**: "איך עברו עליך היומיים האחרונים? הצלחת קצת לנוח ולהתרענן?" -- in almost every run.
- **The likely cause:** the opening step gives her both a recall line (from last time) and an opener question, and the start note adds when they last spoke; she turns the recall into a question of its own and adds the opener. "X, או אולי Y?" questions also still appear elsewhere (16.10's rule reduced but didn't end them).
- One question at a time is a clinical point for him (word-finding: one thing to hold in mind), not only style.

## Goal
1. **The greeting asks one question:** a warm hello, ONE sentence recalling last time (a statement, not a question), and ONE question.
2. **No glued "X, או אולי Y?" questions** anywhere -- measured, not assumed.
3. **Every change is checked with the evals first** (text mode), then on his real sessions.

## Design (to detail)
- **The opening step (`OpeningStep`):** its rules say the shape explicitly -- hello, the recall as a statement ("בפעם הקודמת סיפרת לי על..."), then ONE question; the plan builder's `recall` field is written as a statement, its `opener` as the one question.
- **The start note** (`app/session_prompt.py`): checked that it doesn't invite a second question (the timing words, "CURRENT STEP").
- **"X, או אולי Y?":** if the judge still finds it after the greeting fix, a targeted line in the one-question rule with a second example.
- **Measuring:** `evals/live_step_change.py` replays the opening too (it does: the first turn), and the scorer reports double questions per step kind, so the greeting is visible on its own; `evals/audit_step_changes.py` counts double questions in real sessions by meaning.

## Done when
- [ ] In the evals, the greeting has one question in (nearly) every run, with no rise elsewhere.
- [ ] In his real sessions (the audit), double questions in the greeting are gone or rare.
- [ ] `pytest` passes.

## Commit
`Sub-plan 18: one question at a time, in the greeting too`
