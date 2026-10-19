# Sub-plan 17: Measuring progress the way therapists do, and a summarizing activity

Part of the [master design](00-master-design.md). After [16](16-memory-built-by-code.md), before [17.5](17.5-practicing-the-missing-areas.md). Requested by Tomer (2026-10-15); split from the first plan 16 (2026-10-16; renumbered 16 -> 17 on 2026-10-19) -- this half is what touches the patient's sessions and the family's view; practice in the missing areas is [17.5](17.5-practicing-the-missing-areas.md). **Reviewed; to build.**

## Why
- **The way progress is measured today is weak.** After each session the memory agent rates each area from what it heard (15.5): a judgment, on whatever that session happened to contain, asked differently every time. Therapists measure differently (below), and their way can be borrowed.
- **His kind of difficulty** (mild, high-level: proper names, longer speech) has a practice the app doesn't offer yet: summarizing a short text in his own words.
- **A gap found in testing 15.5 (15.10):** the first needs-check session ran out of time after 3 of its steps (he talked about his project in the opening for 5.5 minutes -- the tutor staying with what he brings up, as intended). The repetition and goals checks never happened, and the fixed second session doesn't include them, so they were lost.

## What the research says
- **Measure with the same items, the same way, from a baseline.** Treatment studies probe a fixed set of items before practice starts (several times, to see it's stable), then repeatedly during and after it. They keep **treated** items and matched **untreated** ones, to tell real improvement from learning those items, and they check **maintenance** later ([Kendall et al., multiple-baseline SFA](https://pubs.asha.org/doi/10.1044/2015_AJSLP-14-0155); [sentence-production probes](https://kar.kent.ac.uk/115949/1/Measuring%20proximal%20outcomes%20of%20sentence%20production%20therapy%20%20probing%20treated%20and%20untreated%20constructions%20with%20a%20story%20completion%20test.pdf)). How often an untreated item is probed matters too: items probed repeatedly showed generalization that rarely-probed ones didn't. The names game (12) already works like this; connected speech doesn't.
- **Generalization has levels, and they can diverge.** Gains on practiced items, on the same words in a new form, on new words, and in conversation are separate results ([single-case study, UCL](https://discovery.ucl.ac.uk/id/eprint/10229543/)).
- **Home practice on a device improves the practiced skill, not automatically conversation.** The largest trial of self-managed computer therapy at home (Big CACTUS, 278 people) found a clear improvement in finding the practiced words, which did **not** carry over to conversation ([Big CACTUS](https://pmc.ncbi.nlm.nih.gov/articles/PMC7232133)). So conversation must be measured on its own.
- **What clinicians and researchers agree to measure** (the ROMA core outcome set): language (WAB-R), communication (the Scenario Test), emotional wellbeing (GHQ-12), quality of life (SAQOL-39), and the patient's own view of treatment ([ROMA](https://ro.ecu.edu.au/ecuworkspost2013/5802); [ROMA-2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10946976)). The app can't and shouldn't run these, but the therapist's formal scores and **his own view** belong next to the practice data.
- **For mild word-finding difficulty:** practice works better when he RETRIEVES the word himself than when he hears and repeats it, and better spaced over sessions than massed (Middleton et al.: [JSLHR 2016](https://pubs.asha.org/doi/10.1044/2016_JSLHR-L-15-0303), [learning principles](https://pmc.ncbi.nlm.nih.gov/articles/PMC5345556)). At the discourse level, reading a short text and summarizing it aloud (ARCS) showed carry-over to untrained speech in mild aphasia ([AJSLP 2017](https://pubs.asha.org/doi/10.1044/2017_AJSLP-16-0200); [ARCS-W, AJSLP 2020](https://pubs.asha.org/doi/10.1044/2020_AJSLP-19-00078)) -- small studies (1-5 participants).
- **Testing what is preserved isn't worth it:** re-testing areas his assessment found preserved adds nothing his therapist doesn't know, takes time from what he needs, makes sessions feel like tests, and invites false alarms (a mishearing read as a difficulty). Ordinary conversation, which the app already rates (15.5), is enough to notice a change.

## Goal
1. **Naming and connected speech are measured like a therapist would:** a fixed probe set, a baseline, treated vs untreated items, maintenance -- scored by code.
2. **Conversation is measured on its own**, so the family sees whether practice reaches real talk.
3. **His own view and his therapist's formal scores** sit next to the app's data.
4. **A summarizing activity**, taking turns with the sequencing task.
5. **For an uploaded profile, the app watches, confirms and suggests** -- changes to what he practices go through the family and his therapist.
6. **No needs check is lost** when the first session runs out of time.

## Design

### A. An account with an uploaded profile (the patient) -- decided 2026-10-15
- **No new checks in his sessions.** The areas his assessment found preserved are not tested; the app keeps rating every area from his ordinary conversation (15.5) -- for the family's eyes.
- **A new difficulty:** if an area shows a difficulty in 2 of 3 sessions of ordinary talk, the card marks it "confirmed" and the app suggests a point for his therapist. Practice in it starts only if the family sets the level on the card (then as in 17.5). A sudden, steep decline is a different matter, handled today: the "sudden decline" flag and the tutor's safety rule.
- **A difficulty that eases:** his focus (names, longer speech) comes from his profile and his therapist, so the app doesn't move it. When the probes (B) show ~3 weeks of success, including untreated items, it suggests a point for his therapist ("names seem to be improving -- is it worth shifting the focus?"). If the family updates his profile or the card, the plans follow.
- Already adapting by itself, as today: the names game rotation and the word bank's spacing (12), the sequencing task's size (14).

### B. A summarizing activity (ARCS-style, by voice)
- **She reads him a short paragraph** (3-4 sentences) on something he cares about (technology, a place, a podcast topic -- written in simple Hebrew by the plan builder, never from his private life), then asks him to tell it in his own words; then one follow-up on his opinion.
- A step class with a builder tool (`add_summary`); the builder lists the paragraph's 3-5 main ideas; the memory agent reports which ones he conveyed; code scores (a progress series).
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

### E. The caregiver page and the export
- Per area: the baseline, then the probe scores over time (treated vs untreated, two lines), and maintenance points.
- The summary scores; conversation measures and his own view, as their own charts; the therapist's scores as markers.
- The therapist export (09) gets a page per area: probe items, scores, dates -- and the points for his therapist (15.5).

## Files
| File | Purpose |
|---|---|
| `app/steps.py`, `app/agent/plan_tools.py`, `app/agent/next_class.py` | The summary step and tool; taking turns with sequencing. |
| `app/probes.py` (new) | Probe sets per area: choose, rotate, baseline, score (like `check_in_set.py`); naming and connected speech. |
| `app/agent/memory_tools.py`, `app/agent/memory_update.py`, `prompts/memory_update.yaml` | Report summary ideas and probe answers; his own view; "confirmed" and "lasting improvement" points for an uploaded profile. |
| `app/class_plan.py`, `app/agent/next_class.py` | Missed needs checks carry over. |
| `prompts/tutor.yaml` (if needed) | Retrieval first. |
| `app/caregiver_api.py`, `static/caregiver.*` | Probe charts, the summary series, conversation measures, his view, the therapist's scores, the export. |
| `tests/` | The summary step and its turn; probe scoring; baseline; treated vs untreated; carry-over; the export. |

## Done when
- [ ] For the patient: no new checks; a confirmed change or a lasting improvement becomes a point for his therapist; his focus changes only through the family.
- [ ] The summarizing activity works, takes turns with sequencing, and is scored by main ideas.
- [ ] Naming and connected speech have probe sets with a baseline, treated and untreated items, scored by code, shown over time.
- [ ] Conversation and his own view are shown on their own; the therapist's scores can be added.
- [ ] A needs check missed in the first session happens in the next.
- [ ] `pytest` passes.

## Commit
`Sub-plan 17: measuring progress like a therapist, and a summarizing activity`
