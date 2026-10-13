# Sub-plan 14: Telling things in order (sequencing and story retell)

Part of the [master design](00-master-design.md). After [13.5](13.5-tool-based-planner.md), before [15](15-names-goodbyes-and-excluded-sessions.md). (Was 13.5 until 2026-10-12.) Requested by Tomer (2026-10-12). Reviewed and updated after 13.5 (2026-10-12).

## Why
- **The patient's speech therapist works on sequencing a lot.** She shows him a set of pictures, and he tells their story in chronological order. Practicing the same skill at home supports her work.
- **The sessions need content that holds a real conversation.** A story task fills real talking time and isn't over after one answer.
- **Today there are only two story activities:** "procedure telling" and "a story from his life in order" (`prompts/therapy_techniques.yaml`). There is no scrambled-events task, no story retell, and no scoring of order.

## What the research says
- **Sequencing and story retelling are standard discourse work in aphasia therapy.**
  - Picture sequences such as the "Broken Window" cards are a common measure, scored for accuracy and completeness ([NCT05561400](https://clinicaltrials.gov/study/NCT05561400)).
  - There are treatments built on sequential pictures ([ECU, intensive discourse treatment](https://thescholarship.ecu.edu/handle/10342/4921)) and on personal stories ([Frontiers 2024](https://www.frontiersin.org/journals/stroke/articles/10.3389/fstro.2024.1393676/epub)).
- **Story telling reflects everyday language better than picture naming** ([den Ouden 2026](https://talkbank.org/aphasia/publications/2026/denOuden26.pdf)).
- **Pictures aren't required:** retelling with and without pictures showed no group difference, though individuals differed ([Doyle 1998](https://aphasiology.pitt.edu/1124/)). So a voice-only version is reasonable, and pictures can come later.
- **Use NEW stories:** familiar stories (Cinderella-like) can hide story-level difficulties that new stories reveal ([preprint](https://easychair.org/publications/preprint/WZ4R/open)).
- **Score by story parts:** setting, what started it, what was tried, the outcome, the reaction ("story grammar", [Richardson & Hudspeth](https://aphasiology.pitt.edu/2593)).

## Goal
A sequencing task regularly (at least every other session, more when his results call for it), at his level, scored by code, with its own progress series. Voice only in this round.

## Decisions (with Tomer, 2026-10-12)
- **Two task types, both with one right order** (so they can be scored deterministically, and they're the closest to his therapist's work):

  | Type | How it sounds |
  |---|---|
  | `scrambled` | She says 4–6 events of a short everyday story **out of order** ("הוא שילם בקופה… הוא נכנס לסופר…"). He tells the story in the right order ("קודם… אחר כך… בסוף"). The voice version of the picture cards. |
  | `retell` | She tells a **new** short story (4–6 events: a setting, a problem, what was done, the outcome). He retells it in order. |

  "Procedure" and "a story from his life in order" stay **activities** (`ActivityStep`), as today: they have no fixed order to score. A story-parts score for them can come later.
- **How often: the plan builder decides, with a minimum enforced by code.** Not the tutor (she doesn't see his progress over time), and not in every session (it would repeat, and take ~2–3 of the 9 minutes every time).
  - If none of his last 2 plans had a sequencing step, `finish` refuses a regular plan without one.
  - Beyond that, the builder chooses from his results (HIS SEQUENCING, below): low scores → more often; high scores → less often, or harder.
  - In the session, she may skip it if he seems tired (like the names game). The memory agent records it; the next plan counts it as a session without sequencing.

## Design

### A. A step class, like the others (13.5)
```python
class SequencingStep(Step):
    kind = "sequencing"
    TOOL = "add_sequencing"
    task: Literal["scrambled", "retell"]
    title: str           # ENGLISH, for the family: "buying groceries"
    events: list[str]    # HEBREW, in the CORRECT order, one short sentence each, in her voice
    told_order: list[int] = []   # filled by code when it's added: the scrambled order (scrambled only)
    RULES = "..."        # fixed, below
    MINUTES = 2.5; MIN_MINUTES = 2.0; MIN_ANSWERS = 2
```
- **The plan builder adds it** with `add_sequencing`, at the place it chooses (usually after the names game and a warm-up topic, not right after the opening).
- **The tool's checks:**
  - 3–6 events;
  - the number of events HIS SEQUENCING recommends (±1);
  - an everyday, adult situation, never from his own life (so there's one right order he can't know in advance): no names of his people or places;
  - the events short and clearly ordered (each one can only come in its place).
- **Code scrambles `scrambled` when the step is added,** into an order that's never the original, never the reverse, and has at most one event still next to its correct neighbour. The model doesn't do it: it would scramble poorly, or keep the correct order.
- **Her step text contains both orders:** "say them in THIS order: …" and "the correct order is: …", so she can help.
- **Measured like every step (13.5):** `sequencing` is timed from her `next_step` reports automatically.

### B. Its fixed rules (`RULES`, the lessons of 12–13)
- **The one long turn of the session:** in this step she may say all the events (or the story) in ONE turn, slowly, one short sentence per event, with a small pause between them. Only then does she ask her one question. This overrides "keep your turns short" for this step only.
- **Introduce it lightly, as a game:** `scrambled`: "אספר לך כמה דברים שקרו, אבל בבלגן, ואתה תספר לי את הסיפור לפי הסדר". `retell`: she tells the story once, then "ספר לי את הסיפור במילים שלך, מההתחלה".
- **She lets him tell it all the way through,** without correcting him. She repeats all the events once if he asks.
- **Then, if the order is off, she helps with ONE question at a time** ("מה קרה קודם, הוא נכנס לסופר או שילם?"), never the answer first. A warm word for the order he got right.
- **After the task, a short conversation:** link the story to his life ("קרה לך פעם משהו כזה?") for an exchange or two. A talking step is a real conversation (13.5). This is why `MIN_ANSWERS` is 2.
- **If he seems tired, she skips it,** says nothing about it, and moves on.

### C. The plan builder
- **HIS SEQUENCING, a new context section, computed in code:** his recent sequencing results (task, events, score, help) and the recommended number of events:
  - full marks two sessions in a row → one more event (up to 6), or a less familiar situation;
  - under half right → one fewer (down to 3), a more familiar routine;
  - otherwise the same.
- **The guide (`GUIDE`):** new stories every time, everyday and adult (a visit to the doctor, buying a gift, fixing a leaking tap), events that can only come in one order, the two types rotated.
- **`finish` checks the minimum frequency** (above).

### D. Scoring (memory agent + code)
- **A new memory tool, `record_sequencing`:**
  - the order he told the events in, as the events' numbers (e.g. `[1, 3, 2, 4, 5]`; events he left out are simply absent);
  - whether he needed her help;
  - `skipped` (with why) if she didn't run it.
- **Matching is by meaning, not word for word:** his telling goes through Gemini's transcription, which mishears (12). The result is marked low-confidence when the two transcripts disagree in a way that changes the order. The recording-based recheck of plan 15 can be applied here later.
- **Code computes the score, not the model:**
  - the share of neighbouring pairs he told in the right order: `[1,3,2,4,5]` → 1→3 ✓, 3→2 ✗, 2→4 ✓, 4→5 ✓ = 3 of 4 = 75%;
  - how many events he included;
  - with or without help.
- **Saved on the session** (`sequencing`), with the task itself: what was asked and what he told.

### E. Caregiver page and export
- **Session line:** "סיפור לפי סדר (מעורבב, 5 אירועים): 4 מתוך 5 בסדר הנכון · בלי עזרה", or "דולג (עייף)".
- **Progress:** a new series, the share in the right order over time (by type), and the recommended number of events.
- **The therapist export:** the tasks and their scores. Useful to his speech therapist, since it's her kind of task.

## Later: pictures like the therapist's → [plan 16](16-picture-sequences.md)
Not in this round. Decide after seeing how the voice-only version goes.

## Files
| File | Purpose |
|---|---|
| `app/steps.py` | `SequencingStep`: content fields, `RULES`, `GUIDE`, times, `MIN_ANSWERS`. |
| `app/sequencing.py` (new) | Scrambling (never the original, the reverse or near them); the order score; the recommended number of events from recent results. |
| `app/agent/plan_tools.py` | `add_sequencing` (generated from the class) with its checks; `finish`'s minimum-frequency check. |
| `app/agent/next_class.py`, `prompts/next_class.yaml` | HIS SEQUENCING in the context; a line on when to choose it. |
| `app/agent/memory_tools.py`, `app/agent/memory_update.py`, `prompts/memory_update.yaml` | `record_sequencing`; the score computed and saved on the session. |
| `app/caregiver_api.py`, `static/caregiver.*` | The session line, the progress series, the export. |
| `tests/` | Scrambling (never the original / reverse); the score (in order, reversed, one swap, an event left out); the recommended number; the tool's checks; `finish`'s frequency rule; the memory tool; the page data. |

## Check before deploying
- **Build a plan for each account (dry run, nothing saved):** a new everyday story, events in the right order, the recommended number of events; the scrambled order isn't close to the original.
- **A live test on Tomer's account:** she says the events clearly and slowly in one turn, doesn't correct mid-way, helps with one question at a time, and then talks about it with him.

## Done when
- [ ] Sequencing comes up at least every other session, and it holds a few minutes of real talk.
- [ ] Its score shows on the session, in progress, and in the therapist export.
- [ ] `pytest` passes.

## Commit
`Sub-plan 14: telling things in order (sequencing and story retell)`
