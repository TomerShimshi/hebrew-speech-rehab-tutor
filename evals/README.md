# Evals: checking the tutor's behavior with the real model

Tools for questions like "does she acknowledge his answer before moving on?" -- run against Gemini
(the real model and the real prompt), not the unit tests' fakes. They read production data (a
session's plan, an account's prompt) and call the models; they never change anything.

Run from the repo root (they need `.env` and `gcloud auth application-default login`):

| Script | What it does |
|---|---|
| `python -m evals.live_step_change --account <email> --session <id> --variant current --runs 3 --out <dir>` | Replays a real session's plan steps on **Gemini Live**, his answers as text, the page's rules simulated (the question guard, min answers). A variant changes one prompt rule; each run is saved as JSON. |
| `python -m evals.score_step_change <dir>` | Scores those runs per variant with the judge (below). |
| `python -m evals.audit_step_changes --account <email> --since 3.5` | The same check on **real sessions** (her first words after each step change) -- run after a prompt change, on the sessions since. |
| `python -m evals.check_judge` | Checks the judge against hand-labeled turns (`evals/judge_cases.yaml`): agreement per field, and the cases it gets wrong. Run after changing the judge's prompt or model; add a case whenever it gets one wrong. |

## The judge

`evals/judge.py`, with its prompt in **`prompts/eval_judge.yaml`** (versioned like the other prompts):
one structured-output call per tutor turn, judged **by meaning**, because the transcript's punctuation
is unreliable (a question can lose its "?", a statement can gain one). It returns:

- `reacted` -- her turn opens with a reaction to his answer (not a generic "בוא נעבור");
- `real_questions` -- separate questions she asks him ("נכון?" isn't one; "X, או ש-Y?" is two; "ספר לי..." is one);
- `invites_answer` -- the turn ends with something for him to answer (a goodbye counts: he says goodbye back);
- `reads_instructions` -- app or instruction text said aloud.

The scorer turns these into: reacted first (at step changes), **double questions** (`real_questions >= 2`),
**dangling turns** (after his answer, no step change and `invites_answer` false), and instructions read
aloud -- with the old punctuation counts ("?" in the transcript) beside them, to see the gap.

## Credit (mind it)

These call paid models. The judge is cheap and is **batched** (one call per ~25 turns) and **cached on
disk** by turn and judge-prompt version (`EVALS_CACHE`, default: the system temp folder), so rescoring is
free; `check_judge` is one call. The expensive part is `live_step_change`: each run is a full simulated
Gemini Live session (audio) -- run as few as answer the question (2-3 per variant), not dozens.

## Privacy (the repo is public)

- Nothing personal goes into this folder: run logs go to `--out` (a folder outside the repo, e.g. the
  scratchpad), and the scripts print to the terminal only.
- Real answers for a replay go in a file named `*.local.json` (git-ignored), passed with `--answers`:
  `{"story_probe": ["his retelling", "his answer to the link question"], "his_view": ["..."]}`.
  Without it, a neutral simulated speaker answers.

## What text-mode testing can and can't show

Text stands in for his voice, so these runs show **what she says and in what order around a tool
call** -- not audio behavior (freezes, the transcript lagging behind her voice, mishearing). A result
here is a filter (21.10: reversing the call order brought back double questions, so it was dropped
before reaching him); the real check is `audit_step_changes` on his sessions afterwards.

## History

- 21.10 (`live_step_change`, 3-4 runs per variant): the plain "call first, then react and continue"
  rule reacted 100% in text mode (the real sessions: ~2/3 -- the failure is audio-only); a stronger
  wording also 100%, no regressions; "react first, then call" 94% with 5 double questions. The
  stronger wording was deployed (tutor prompt 3.5).
- 22.10 (17.5): a neutral plan with the new steps (`evals/plans/missing_areas.json`), 3 runs: reacted
  first 24/24, nothing read aloud; the flagged double questions were the understanding items' intended
  multi-part requests (the judge now counts one ordered request as one -- prompt 1.3) and the greeting
  (plan 18); 5 dangling turns in a closing music topic, as before. The judge was batched and cached.
