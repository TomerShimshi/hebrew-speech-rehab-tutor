# Sub-plan 17: Measuring progress like a therapist, and adjusting to it -- plus a summarizing activity

Part of the [master design](00-master-design.md). After [16](16-memory-built-by-code.md), before [17.5](17.5-practicing-the-missing-areas.md). Requested by Tomer (2026-10-15); split from the first plan 16 (2026-10-16; renumbered 16 -> 17 on 2026-10-19) -- this half is what touches the patient's sessions and the family's view; practice in the missing areas is [17.5](17.5-practicing-the-missing-areas.md). Updated 2026-10-21: the app adjusts the plans to his measured progress, like a therapist, with the family's veto (E). **Built 2026-10-21** (what's left: below).

## Why
- **The way progress is measured today is weak.** After each session the memory agent rates each area from what it heard (15.5): a judgment, on whatever that session happened to contain, asked differently every time. Therapists measure differently (below), and their way can be borrowed.
- **His kind of difficulty** (mild, high-level: proper names, longer speech) has a practice the app doesn't offer yet: summarizing a short text in his own words.
- **Measurements alone don't help him.** A therapist changes the plan as the patient improves or struggles; until now the app only showed the data (and, for the patient, left every change to the family).
- **A gap found in testing 15.5 (15.10):** the first needs-check session ran out of time after 3 of its steps (he talked about his project in the opening for 5.5 minutes -- the tutor staying with what he brings up, as intended). The repetition and goals checks never happened, and the fixed second session doesn't include them, so they were lost.

## What the research says
- **Measure with the same items, the same way, from a baseline.** Treatment studies probe a fixed set of items before practice starts (several times, to see it's stable), then repeatedly during and after it. They keep **treated** items and matched **untreated** ones, to tell real improvement from learning those items, and they check **maintenance** later ([Kendall et al., multiple-baseline SFA](https://pubs.asha.org/doi/10.1044/2015_AJSLP-14-0155); [sentence-production probes](https://kar.kent.ac.uk/115949/1/Measuring%20proximal%20outcomes%20of%20sentence%20production%20therapy%20%20probing%20treated%20and%20untreated%20constructions%20with%20a%20story%20completion%20test.pdf)). How often an untreated item is probed matters too: items probed repeatedly showed generalization that rarely-probed ones didn't. The names game (12) already works like this; connected speech doesn't.
- **Generalization has levels, and they can diverge.** Gains on practiced items, on the same words in a new form, on new words, and in conversation are separate results ([single-case study, UCL](https://discovery.ucl.ac.uk/id/eprint/10229543/)).
- **Home practice on a device improves the practiced skill, not automatically conversation.** The largest trial of self-managed computer therapy at home (Big CACTUS, 278 people) found a clear improvement in finding the practiced words, which did **not** carry over to conversation ([Big CACTUS](https://pmc.ncbi.nlm.nih.gov/articles/PMC7232133)). So conversation must be measured on its own.
- **What clinicians and researchers agree to measure** (the ROMA core outcome set): language (WAB-R), communication (the Scenario Test), emotional wellbeing (GHQ-12), quality of life (SAQOL-39), and the patient's own view of treatment ([ROMA](https://ro.ecu.edu.au/ecuworkspost2013/5802); [ROMA-2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10946976)). The app can't and shouldn't run these, but the therapist's formal scores and **his own view** belong next to the practice data.
- **For mild word-finding difficulty:** practice works better when he RETRIEVES the word himself than when he hears and repeats it, and better spaced over sessions than massed (Middleton et al.: [JSLHR 2016](https://pubs.asha.org/doi/10.1044/2016_JSLHR-L-15-0303), [learning principles](https://pmc.ncbi.nlm.nih.gov/articles/PMC5345556)). At the discourse level, reading a short text and summarizing it aloud (ARCS) showed carry-over to untrained speech in mild aphasia ([AJSLP 2017](https://pubs.asha.org/doi/10.1044/2017_AJSLP-16-0200); [ARCS-W, AJSLP 2020](https://pubs.asha.org/doi/10.1044/2020_AJSLP-19-00078)) -- small studies (1-5 participants).
- **Therapists adjust from measured progress, by explicit rules.** Goals are changed from repeated measures ([conversation-analysis study](https://scholarlycommons.pacific.edu/phs-facarticles/171)); a trial protocol: no gain over 3 consecutive visits -> change the approach, still none -> stop that exercise ([NCT03600987](https://cdn.clinicaltrials.gov/large-docs/87/NCT03600987/Prot_SAP_001.pdf)); progress -> new goals, less cueing; and decision frameworks try to make these choices explicit ([Barrow](https://barrowneuro.org/wp-content/uploads/BARROW.-Carpenter.-10.2024.-FINAL.pdf)). No agreed mastery threshold exists -- each program sets its own.
- **Adaptive digital programs:** adapting difficulty to performance is standard in them; an adaptive app beat workbooks in a small controlled trial ([Constant Therapy, 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC7907641)), though no study isolates the adaptivity itself; automatic decision-making for self-managed practice is active research ([therapy calculator, preprint](https://www.medrxiv.org/content/10.64898/2026.01.22.26344656.full.pdf)).
- **Testing what is preserved isn't worth it:** re-testing areas his assessment found preserved adds nothing his therapist doesn't know, takes time from what he needs, makes sessions feel like tests, and invites false alarms (a mishearing read as a difficulty). Ordinary conversation, which the app already rates (15.5), is enough to notice a change.

## Goal
1. **Naming and connected speech are measured like a therapist would:** a fixed probe set, a baseline, treated vs untreated items, maintenance -- scored by code.
2. **Conversation is measured on its own**, so the family sees whether practice reaches real talk.
3. **His own view and his therapist's formal scores** sit next to the app's data.
4. **A summarizing activity**, taking turns with the sequencing task.
5. **The plans follow his measured progress, like a therapist** (E): harder or easier within an area, more or less time on it, a new confirmed weakness added gradually -- by explicit rules, every change logged with its reason, and the family can lock an area or undo a change.
6. **No needs check is lost** when the first session runs out of time.

## Design

### A. An account with an uploaded profile (the patient) -- decided 2026-10-15, updated 2026-10-21
- **No new checks in his sessions.** The areas his assessment found preserved are not tested; the app keeps rating every area from his ordinary conversation (15.5).
- **His profile and his therapist's plan are the starting point**; from there the plans follow his measured progress (E), with the family's veto -- not only the family's say, as first decided.
- **A new difficulty:** if an area shows a difficulty in 2 of 3 sessions of ordinary talk, it is "confirmed": the app adds it gradually (E) and tells the family (a notice on the card, and a point for his therapist); the family can cancel. A sudden, steep decline is a different matter, handled today: the "sudden decline" flag and the tutor's safety rule.
- **A difficulty that eases:** mastered (E) -> harder items and less time on it, and a point for his therapist ("names seem to be improving -- is it worth shifting the focus?").
- Already adapting by itself, as today: the names game rotation and the word bank's spacing (12), the sequencing task's size (14).

### B. A summarizing activity (ARCS-style, by voice)
- **She reads him a short paragraph** (3-4 sentences) on something he cares about (technology, a place, a podcast topic -- written in simple Hebrew by the plan builder, never from his private life), then asks him to tell it in his own words; then one follow-up on his opinion.
- A step class with a builder tool (`add_summary`); the builder lists the paragraph's 3-5 main ideas; the memory agent reports which ones he conveyed; code scores (a progress series).
- **Its size adapts, like the sequencing task's:** code recommends the number of sentences and main ideas from his last results (grow after success, shrink when hard), and the tool checks the paragraph against it.
- **It takes turns with the sequencing task (14)** (decided 2026-10-15): one session has a sequencing task, the next a summary -- both discourse-level, ~2-3 minutes, so the session keeps its length. `finish` refuses a regular plan without the one whose turn it is. Sequencing's own two kinds keep taking turns among its sessions (each kind every fourth session).
- **Retrieval first:** the transcripts are checked that she gives a hint only AFTER he has really tried, in the names game and practice -- a prompt fix if not.

### C. Measuring like a therapist
- **A probe set per area,** like the names game's stable set (12): a few fixed items, asked the same way, without hints; half practiced (treated), half never practiced (untreated). Kept ~3 weeks, then renewed; the old set is probed once more later (maintenance). The framework (`app/probes.py`) is general, so 17.5 adds its areas to it.
- **A baseline first:** a new probe set is asked in 2 sessions before practice with it starts.
- **For the patient: naming and connected speech only.** Naming already has one (the names game, 12). Connected speech gets one: a fixed short story she tells and he retells, asked the same way, scored by the main ideas he conveyed.
- **Scored by code** from what he said, not by the agent's impression. The agent's per-session levels (15.5) stay, labeled as its impression.
- **Conversation, on its own:** measures the app already has, per session -- his own names found vs not found in free talk (12), how long his answers are, how often he gets stuck -- shown as their own series, never mixed with practice scores.
- **His own view:** once every ~2 weeks, at the end of a session, she asks one short question ("איך היה לך לדבר עם אנשים השבוע?") and the memory agent records his answer on a 1-5 scale with his words.
- **The therapist's scores:** the caregiver page gets a place to type a formal result with its date (e.g. "WAB-R AQ 92, 1.11"), shown on the progress charts as a marker.

### D. Missed needs checks carry over (found 15.10)
- After the first needs-check session, the code sees which check steps were never reached (the session's `steps_done` against its agenda) and puts them into the second session, each between two conversation topics -- never two checks in a row, never right after the greeting. If the second session runs out too, the plan builder's third session gets the rest (at most one per session).

### E. Adjusting to his progress, like a therapist (decided 2026-10-21)
- **HIS PROGRESS in the plan builder's context:** per practiced area (names, connected speech, summarizing; for a new account, every area it practices), the probe scores over time -- treated and untreated -- the summary and sequencing scores, and the area's current setting (level, share of the session) with the last decision and its reason.
- **Decisions by code, by explicit rules, per area -- never from one session,** only from code-scored probes, and never counting an attempt marked low-confidence (a doubtful transcription):
  - **Mastered:** about 80% on 3 probe sessions in a row, untreated items included -> the next level (harder items, longer tasks, fewer hints) and a smaller share of the session.
  - **Stalled:** no gain over about 3 probe sessions -> change the approach in that area (another kind of task or cue), and a point for his therapist.
  - **Getting worse** over 2-3 sessions -> easier items, a larger share, and a point for his therapist.
  - **A new confirmed weakness** (A, 17.5) -> added gradually: one short step every other session, growing while it stays.
- **The plan builder follows the setting:** each area's level and share go to it as part of HIS PROGRESS ("names: level 3, ~2 minutes; summarizing: 4 ideas"), and its tools check them (like the sequencing size); it chooses the content, the code chooses the dose.
- **Every change logged with its reason** ("names: 85% three probe sessions in a row -> harder names"), shown on the caregiver page and in the therapist export.
- **The family's veto:** lock an area ("from the therapist: keep it as it is") so the app never changes it; undo a decision (back to the previous setting). A lock or an undo is logged too.
- The thresholds (80%, 3 sessions) are our choice -- no agreed standard exists -- and are constants in one place, to tune after watching them work.

### F. The caregiver page and the export
- Per area: the baseline, then the probe scores over time (treated vs untreated, two lines), and maintenance points.
- The summary scores; conversation measures and his own view, as their own charts; the therapist's scores as markers.
- The therapist export (09) gets a page per area: probe items, scores, dates -- and the points for his therapist (15.5).
- **"Changes the app made":** each area's current level and share, the log of decisions with their reasons, and the lock / undo buttons.

## Files
| File | Purpose |
|---|---|
| `app/steps.py`, `app/agent/plan_tools.py`, `app/agent/next_class.py` | The summary step and tool; taking turns with sequencing. |
| `app/probes.py` (new) | Probe sets per area: choose, rotate, baseline, score (like `check_in_set.py`); naming and connected speech. |
| `app/agent/memory_tools.py`, `app/agent/memory_update.py`, `prompts/memory_update.yaml` | Report summary ideas and probe answers; his own view; "confirmed" and "lasting improvement" points for an uploaded profile. |
| `app/class_plan.py`, `app/agent/next_class.py` | Missed needs checks carry over. |
| `app/progress.py` (new) | The decision rules per area (mastered / stalled / worse / new), the setting (level, share), the log; locks and undo. |
| `app/agent/next_class.py`, `app/agent/plan_tools.py`, `prompts/next_class.yaml` | HIS PROGRESS in the builder's context; the tools check the area settings; the summary size. |
| `prompts/tutor.yaml` (if needed) | Retrieval first. |
| `app/caregiver_api.py`, `static/caregiver.*` | Probe charts, the summary series, conversation measures, his view, the therapist's scores, the export. |
| `tests/` | The summary step, its turn and its size; probe scoring; baseline; treated vs untreated; carry-over; each decision rule (and that one session or a low-confidence attempt never decides); locks and undo; the export. |

## What was built (2026-10-21)
- **The summary (B):** `SummaryStep` / `add_summary` (a Hebrew paragraph and its main ideas; one per session), `app/summarizing.py` (score, recommended size 3-6), `record_summary` (+ the extra round when it's missed), the session's `summarizing` result, a progress series. **Turns:** `discourse_turn` -- the other one than the last regular session's; HIS DISCOURSE TASK in the builder's context; `add_sequencing` / `add_summary` refuse the wrong one and `finish` requires the right one.
- **Carry-over (D):** `missed_checks` from the session's steps and `steps_done`; into the fixed second session (each after a short topic), then one per built plan (`add_one_check`), kept as `pending_checks` with the needs (the memory update merges into that doc now, instead of replacing it).
- **Measuring (C):** `app/probes.py` + `prompts/probe_stories.yaml` (6 everyday stories, 5 main ideas each): a story to retell every other regular session, each told twice, placed by code after the opening's next step; `record_story_probe`. His own view every ~14 days (`ViewStep`, placed before the last two steps so the wrap-up note doesn't cut it), `record_his_view` (1-5 with his words). Conversation measures by code per session (`talk`: answers, average words, long answers). The therapist's scores: entered on the caregiver page.
- **Adjusting (E):** `app/progress.py` -- series per area (naming from the names game, untreated included; connected speech from the story probe; summarizing; sequencing), the rules (mastered / worse / stalled), 3 new results between decisions, never a low-confidence result; a dry run on the real data (21.10) tightened them: worse and stalled need 3 earlier results, and no "stalled" at the top of the scale. Run before every plan (`apply_progress`): HIS PROGRESS in the builder's context, new decisions logged and turned into points for the therapist; the naming time is checked by `finish` (more: 2+ practice steps, less: at most 1). Lock / undo on the caregiver page.
- **The caregiver page (F):** "התאמות שהאפליקציה עשתה" (per area level, time, last decision, lock, undo, the log), the therapist's scores, charts for the story probe, answer length and his view; the session's summary line.
- Prompts: plan builder 0.22, memory update 0.14. `docs/tools.md` regenerated. Tests: `test_summarizing.py`, `test_progress.py`, carry-over in `test_needs_check.py`. `pytest`: 313 passed.
- **Checked end to end** on the test account's real data: the plan got the summary (its turn), the story probe and his view; the rules logged one decision.
- **Dry run for the patient** (21.10): naming "stalled" (78% average, no gain over two 3-session windows) -- it will become a point for his therapist and a "try another cue" note for the builder at his next plan; the family can lock or undo it.

**Not done yet:**
- The therapist export pages per area (F) -- the data is on the caregiver page.
- The "retrieval first" check of the transcripts (B).
- A new confirmed weakness in an area the app doesn't practice is only noted (practice for those areas is 17.5); in the practiced areas a decline already gives more time.
- The probe and view steps are placed outside the builder's time budget: a session with both is ~2 minutes longer than planned -- to watch.

## Done when
- [x] For the patient: no new checks; the plans follow his measured progress by the rules (E), every change logged with its reason; a confirmed weakness is added gradually with a notice; the family can lock an area or undo a change.
- [x] The summarizing activity works, takes turns with sequencing, adapts its size, and is scored by main ideas.
- [x] Naming and connected speech have probe sets with a baseline, treated and untreated items, scored by code, shown over time.
- [x] Conversation and his own view are shown on their own; the therapist's scores can be added.
- [x] A needs check missed in the first session happens in the next.
- [x] `pytest` passes.

## Commit
`Sub-plan 17: measuring progress like a therapist and adjusting to it, and a summarizing activity`
