# Sub-plan 14: Telling things in order (sequencing and story retell)

Part of the [master design](00-master-design.md). After [13.5](13.5-tool-based-planner.md), before [15](15-names-goodbyes-and-excluded-sessions.md). (Was 13.5 until 2026-10-12.) Requested by Tomer (2026-10-12).

## Why
- **The patient's speech therapist works on sequencing a lot.** She shows him a set of pictures, and he tells their story in chronological order. Practicing the same skill at home supports her work.
- **The sessions need more content that holds a longer conversation.** A story task fills real talking time, and it isn't over after one answer, unlike a name.
- **Today the plan builder has only two story activities:** "procedure telling" and "a story from his life in order" (`prompts/therapy_techniques.yaml`), and only on "discourse" days. There is no scrambled-events task, no story retell, and no scoring of order.

## What the research says
- **Sequencing and story retelling are standard discourse work in aphasia therapy.**
  - Picture sequences such as the "Broken Window" cards are a common measure, scored for accuracy and completeness ([NCT05561400](https://clinicaltrials.gov/study/NCT05561400)).
  - There are treatments built on sequential pictures ([ECU, intensive discourse treatment](https://thescholarship.ecu.edu/handle/10342/4921)) and on personal stories ([Frontiers 2024](https://www.frontiersin.org/journals/stroke/articles/10.3389/fstro.2024.1393676/epub)).
- **Story telling reflects everyday language better than picture naming** ([den Ouden 2026](https://talkbank.org/aphasia/publications/2026/denOuden26.pdf)).
- **Pictures aren't required:** retelling with and without pictures showed no group difference, though individuals differed ([Doyle 1998](https://aphasiology.pitt.edu/1124/)). So a voice-only version is reasonable, and pictures can come later.
- **Use NEW stories:** familiar stories (Cinderella-like) can hide story-level difficulties that new stories reveal ([preprint](https://easychair.org/publications/preprint/WZ4R/open)).
- **Score by story parts:** setting, what started it, what was tried, the outcome, the reaction ("story grammar", [Richardson & Hudspeth](https://aphasiology.pitt.edu/2593)).

## Goal
One sequencing task in most sessions, at his level, scored by code-checked rules, with its own progress series. Voice only in this round.

## Design

### A. Four sequencing tasks (voice only)
| Type | How it sounds |
|---|---|
| `scrambled` | She says 4–6 events of a short everyday story **out of order** ("הוא שילם בקופה… הוא נכנס לסופר…"). He tells the story in the right order, with "קודם… אחר כך… בסוף". The voice version of the picture cards. |
| `retell` | She tells a **new** short story (4–6 events, with a setting, a problem and an outcome). He retells it in order. |
| `procedure` | How to do something he knows, step by step (preparing a Friday dinner, planting a tree). |
| `personal` | An event from his own life, in order: beginning, middle, end. |

### B. The plan builder writes it
- **A new `sequencing` field in the plan:** `type`, `title` (English), and `events`: the story's events in Hebrew, **in the correct order**, as she says them (short sentences, one event each). `procedure` and `personal` have no fixed events: they're open, and scored by their parts.
- **Code scrambles the events** for `scrambled`, in an order that's never the original or almost the original. The model doesn't do it: it would scramble poorly, or keep the correct order.
- **New stories every time,** everyday and adult (no children's stories), never from his own life for `scrambled` / `retell` (so there's one right order that he can't know in advance).
- **Difficulty from his results** (computed in code, given to the builder):
  - full marks two sessions in a row → one more event (up to 6) or a less familiar situation;
  - under half right → one less (down to 3), a more familiar routine.
- **Rotates the four types,** and leans on `scrambled` and `retell`, the closest to his therapist's work.
- **In every regular plan**, not only on "discourse" days. On a "discourse" day it is the main activity.

### C. In the session
- **Steps mode (13):** a "sequencing" step after the names game and the practice items. Without steps mode, it's an item in TODAY'S PLAN.
- **How she runs it (prompt):**
  - She introduces it lightly: "אספר לך כמה דברים שקרו, אבל בבלגן, ואתה תספר לי את הסיפור לפי הסדר".
  - She says each event slowly and clearly, and repeats all the events once if he asks.
  - She lets him tell it **all the way through** without correcting him.
  - Then she helps with **one** question at a time if the order is off ("מה קרה קודם, הוא נכנס לסופר או שילם?").
  - Never the answer first. A warm word for the order he got right.
  - For `retell`: she tells the story once, then asks "ספר לי את הסיפור במילים שלך, מההתחלה".

### D. Scoring (memory agent + code)
- **A new tool, `record_sequencing`:** the order he told the events in, as the events' numbers (e.g. `[1, 3, 2, 4, 5]`); whether he needed her help; and, for `retell` / `personal` / `procedure`, which story parts he included (setting, starting event, attempt, outcome, reaction).
- **Code computes the score, not the model:** the share of neighbouring events in the right order (here 3 of 4 = 75%), and the number of story parts. That's reliable even if the agent's judgement varies.
- **Saved on the session** (`sequencing`), with the task itself, so the caregiver page can show what was asked and what he told.

### E. Caregiver page and export
- **Session line:** "סיפור לפי סדר (מעורבב, 5 אירועים): 4 מתוך 5 בסדר הנכון · בלי עזרה".
- **Progress:** a new series, the share in the right order over time (by type), plus the number of story parts in retells.
- **The therapist export:** the tasks and their scores. Useful to his speech therapist, since it's her kind of task.

## Later, a separate step: pictures like the therapist's
- The tablet shows 4 picture cards out of order. He arranges them (taps), then tells the story.
- Needs a picture set (made once, reviewed by the family), and the tutor has to know the pictures (their descriptions, or the images sent to the live model).
- Not in this round. Decide after seeing how the voice-only version goes.

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `Sequencing` in the plan (type, title, events); `record_sequencing` results. |
| `app/sequencing.py` (new) | Scrambling (never the original or near it); the order score; difficulty from recent results. |
| `prompts/next_class.yaml`, `prompts/therapy_techniques.yaml` | Writing the task (new everyday stories, events in order, the four types, difficulty). |
| `app/class_plan.py`, `app/agenda.py` | TODAY'S PLAN shows the task (with the scrambled order); the sequencing step. |
| `prompts/tutor.yaml` | How to run it (no corrections mid-way, one question at a time, never the answer first). |
| `app/agent/memory_tools.py`, `prompts/memory_update.yaml` | `record_sequencing`. |
| `app/caregiver_api.py`, `static/caregiver.*` | The session line, the progress series, the export. |
| `tests/` | Scrambling (never the original); the score (in order / reversed / one swap); difficulty steps; the agenda step; the tool; the page data. |

## Check before deploying
- **Build a plan for the patient (dry run, nothing saved):** a new everyday story, events in the right order, at his level; the scrambled order isn't close to the original.
- **A live test on Tomer's account:** she says the events clearly, doesn't correct mid-way, helps with one question at a time.

## Done when
- [ ] Most sessions have a sequencing task, and it holds a few minutes of real talk.
- [ ] Its score shows on the session and in progress, and in the therapist export.
- [ ] `pytest` passes.

## Commit
`Sub-plan 14: telling things in order (sequencing and story retell)`
