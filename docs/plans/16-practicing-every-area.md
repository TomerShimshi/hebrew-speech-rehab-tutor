# Sub-plan 16: Practicing every area, and measuring progress the way therapists do

Part of the [master design](00-master-design.md). After [15.5](15.5-first-sessions-needs-check.md), before [17](17-names-goodbyes-and-excluded-sessions.md). Requested by Tomer (2026-10-15). **Reviewed 2026-10-15 (decisions below); to build later.**

## Why
- **15.5 finds his needs in seven areas, but the app practices only three** (conversation, naming, connected speech). Repetition, understanding and speech clarity are shown to the family as "not practiced in the app yet". For a new account with a difficulty there, the app would see it and do nothing about it.
- **The way progress is measured today is weak.** After each session the memory agent rates each area from what it heard (15.5): a judgment, on whatever that session happened to contain, asked differently every time. Therapists measure differently (below), and their way can be borrowed.
- For the patient's account these three areas are preserved (his assessment), so part A matters mostly for other accounts. Part B (measuring) matters for everyone, him included.

## What the research says
- **Measure with the same items, the same way, from a baseline.** Treatment studies probe a fixed set of items before practice starts (several times, to see it's stable), then repeatedly during and after it. They keep **treated** items and matched **untreated** ones, to tell real improvement from learning those items, and they check **maintenance** later ([Kendall et al., multiple-baseline SFA](https://pubs.asha.org/doi/10.1044/2015_AJSLP-14-0155); [sentence-production probes](https://kar.kent.ac.uk/115949/1/Measuring%20proximal%20outcomes%20of%20sentence%20production%20therapy%20%20probing%20treated%20and%20untreated%20constructions%20with%20a%20story%20completion%20test.pdf)). How often an untreated item is probed matters too: items probed repeatedly showed generalization that rarely-probed ones didn't. The names game (12) already works like this; the other areas don't.
- **Generalization has levels, and they can diverge.** Gains on practiced items, on the same words in a new form, on new words, and in conversation are separate results; one can improve while another doesn't ([single-case study, UCL](https://discovery.ucl.ac.uk/id/eprint/10229543/)).
- **Home practice on a device improves the practiced skill, not automatically conversation.** The largest trial of self-managed computer therapy at home (Big CACTUS, 278 people) found a clear improvement in finding the practiced words, which did **not** carry over to conversation ([Big CACTUS](https://pmc.ncbi.nlm.nih.gov/articles/PMC7232133)). So conversation must be measured on its own, never inferred from the practice scores.
- **What clinicians and researchers agree to measure** (the ROMA core outcome set): language (WAB-R), communication (the Scenario Test), emotional wellbeing (GHQ-12) and quality of life (SAQOL-39), plus the patient's own view of treatment, still without an agreed measure ([ROMA](https://ro.ecu.edu.au/ecuworkspost2013/5802); [ROMA-2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10946976)). The app can't and shouldn't run these, but they show that the therapist's formal scores and **his own view** belong next to the practice data.
- **Repetition:** massed repetition practice improves repetition itself, with modest and variable carry-over to spontaneous speech ([review, Western](https://www.uwo.ca/fhs/lwm/teaching/EBP/2012_13/Spratt_J.pdf); [massed sentence repetition](https://pubs.asha.org/doi/10.1044/2016_AJSLP-15-0151)).
- **Understanding:** the treatment evidence is limited and variable ([Patterson & Purdy](https://www.medbridge.com/educate/courses/auditory-comprehension-deficit-in-aphasia-examining-the-evidence-janet-patterson-mary-purdy)); yes/no questions differ in difficulty in a graded way (a small study: [Carter 1999](https://digital.library.txstate.edu/items/5e191cbd-2958-4e04-89c2-773abc5784e0)), which supports graded practice and graded measuring.
- **For mild word-finding difficulty (the patient's kind):** practice works better when he RETRIEVES the word himself than when he hears and repeats it, and better spaced over sessions than massed (Middleton et al.: [JSLHR 2016](https://pubs.asha.org/doi/10.1044/2016_JSLHR-L-15-0303), [learning principles](https://pmc.ncbi.nlm.nih.gov/articles/PMC5345556)) -- small studies, consistent. At the discourse level, reading a short text and summarizing it aloud (ARCS) showed carry-over to untrained speech in mild aphasia ([AJSLP 2017](https://pubs.asha.org/doi/10.1044/2017_AJSLP-16-0200); [ARCS-W, AJSLP 2020](https://pubs.asha.org/doi/10.1044/2020_AJSLP-19-00078)) -- 1-5 participants per study.
- **Testing what is preserved isn't worth it:** re-testing areas his assessment found preserved adds nothing his therapist doesn't know, takes time from what he needs, makes sessions feel like tests, and invites false alarms (a mishearing read as a difficulty). Ordinary conversation, which the app already rates (15.5), is enough to notice a change.
- **Speech clarity:** home and remote programs are feasible and improve communication and participation ratings, but listener-rated clarity changed little in small studies ([Be Clear, telerehabilitation](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8870717/)); which cue helps (slower, or louder) differs per person and can be predicted from his baseline ([dysarthria strategies](https://doaj.org/article/6df9c872ad5343ad87470fde1adbf8d2)).

## Goal
1. **The three missing areas can be practiced** -- only for an account whose needs show a difficulty there.
2. **Every area is measured like a therapist would:** a fixed probe set, a baseline, treated vs untreated items, maintenance -- scored by code where possible.
3. **Conversation is measured on its own**, so the family sees whether practice reaches real talk.
4. **His own view and his therapist's formal scores** sit next to the app's data.

## Design

### A0. A difficulty is confirmed before it is practiced, and practice is gradual (decided 2026-10-15)
One hard session can be tiredness, a bad day, or a mishearing. So, per area:
1. **Seen once** -> the area is marked "to check again" on the card; nothing is practiced.
2. **A light re-check** in the next 2-3 sessions: one short, natural item of that area inside the talk (accounts without an uploaded profile; see A1 for the patient).
3. **Confirmed** (a difficulty in 2 of those 3) -> practice starts small: one short step in that area every other session. It grows (every session, longer) while the difficulty stays, and fades out when the probes (B) come back fine for ~3 weeks.
4. **Not confirmed** -> back to "fine", kept on the card as a one-time note.
- The family can confirm or cancel at any stage on the card, and its word wins.

### A1. An account with an uploaded profile (the patient) -- decided 2026-10-15
- **No new checks in his sessions.** The areas his assessment found preserved are not tested; the app keeps rating every area from his ordinary conversation (15.5) -- for the family's eyes.
- **A new difficulty:** if an area shows a difficulty in 2 of 3 sessions of ordinary talk, the card marks it "confirmed" and the app suggests a point for his therapist. Practice in it starts only if the family sets the level on the card -- then gradually, as in A0. (A sudden, steep decline is a different matter, handled today: the "sudden decline" flag and the tutor's safety rule.)
- **A difficulty that eases:** his focus (names, longer speech) comes from his profile and his therapist, so the app doesn't move it. When the probes (B) show ~3 weeks of success, including untreated items, it suggests a point for his therapist ("names seem to be improving -- is it worth shifting the focus?"). If the family updates his profile or the card, the plans follow.
- Already adapting by itself, as today: the names game rotation and the word bank's spacing (12), the sequencing task's size (14).

### A2. A summarizing activity (for him, and anyone with mild high-level difficulty)
- **ARCS-style, by voice:** she reads him a short paragraph (3-4 sentences) on something he cares about (technology, a place, a podcast topic -- written in simple Hebrew by the plan builder, never from his private life), then asks him to tell it in his own words; then one follow-up on his opinion. A step class with a builder tool; the memory agent reports how many of the paragraph's main ideas he conveyed (the builder lists them), code scores.
- **How often: it takes turns with the sequencing task (14)** (decided 2026-10-15): one session has a sequencing task, the next a summary, and so on -- both are discourse-level, ~2-3 minutes, so the session keeps its length and he gets both every other session. The code enforces it the same way (`finish` refuses a regular plan without the one whose turn it is). Sequencing's own two kinds keep taking turns among its sessions, so each kind now comes every fourth session.
- Also for him: the transcripts are checked that she gives a hint only AFTER he has really tried (retrieval first), in the names game and practice -- a prompt fix if not.

### A3. Practice steps for the missing areas (new step classes, builder tools)
Each is a step class (13.5): content by the builder, rules by code, offered to the builder only for an area whose difficulty is confirmed (A0) or set by the family (A1).
- **Repetition** (`add_repetition`): a ladder from his own topics -- words, then short phrases, then a longer sentence (lengths set by code from his last results). She says each once; he repeats; one retry; a warm reaction, never "wrong". Scored by code: the words of his repetition against the target (both transcripts; a low-confidence flag when they disagree).
- **Understanding** (`add_understanding`): graded yes/no questions (simple facts -> about him -> comparisons -> reversible, "האם הכלב רדף אחרי החתול, או החתול אחרי הכלב?"), then two- and three-part spoken requests ("ספר לי X, ואחר כך Y"), then a short story with questions. The memory agent reports right/wrong per item; code scores. Voice only: no "point to" or "show me" tasks.
- **Clarity** (`add_clarity`): phrases from his life said with ONE cue -- slower, or louder, or "clearly, every sound" -- the cue chosen per person from his baseline (which one helped). Measured by how well the transcription caught the target phrase: a rough proxy for a listener (stated as such), plus, optionally, a family rating ("understood all / most / some").

### B. Measuring like a therapist (all areas)
- **A probe set per area,** like the names game's stable set (12): a few fixed items, asked the same way, without hints, at the start of practice in that area; half practiced (treated), half never practiced (untreated). Kept ~3 weeks, then renewed; the old set is probed once more later (maintenance).
- **A baseline first:** the probe set is asked in 2 sessions before practice in that area starts, so the family sees where he began.
- **For the patient: probe sets for naming and connected speech only** (his areas), none for the preserved ones. Naming already has one (the names game, 12); connected speech gets one (a fixed short story retold, asked the same way, scored by main ideas).
- **Scored by code** from what he said (repetition: words matched; understanding: right/wrong; naming: as in 12), not by the agent's impression. The agent's per-session levels (15.5) stay, labeled as its impression.
- **Conversation, on its own:** measures the app already has, per session -- his own names found vs not found in free talk (12), how long his answers are, how often he gets stuck -- shown as their own series, never mixed with practice scores.
- **His own view:** once every ~2 weeks, at the end of a session, she asks one short question ("איך היה לך לדבר עם אנשים השבוע?") and the memory agent records his answer on a 1-5 scale with his words.
- **The therapist's scores:** the caregiver page gets a place to type a formal result with its date (e.g. "WAB-R AQ 92, 1.11"), shown on the progress charts as a marker.

### C. The caregiver page and the export
- Per area: the baseline, then the probe scores over time (treated vs untreated, two lines), and maintenance points.
- Conversation measures and his own view, as their own charts.
- The therapist export (09) gets a page per area: probe items, scores, dates -- and the points for his therapist (15.5).

## Decided (2026-10-15)
- A difficulty is confirmed over 2-3 sessions before practice; practice starts small and grows or fades with the probes; the family can confirm or cancel (A0).
- The patient: no new checks; the app watches, confirms and suggests, and changes to what he practices go through the family and his therapist (A1). Probe sets for naming and connected speech only; the summarizing activity (A2).
- The summarizing activity takes turns with the sequencing task, session by session (A2).

## Files
| File | Purpose |
|---|---|
| `app/steps.py`, `app/agent/plan_tools.py` | Repetition, understanding, clarity steps and tools (gated: confirmed or family-set); the summarizing step. |
| `app/agent/memory_update.py`, `app/patient_profile.py` | An area's status: seen once -> re-check -> confirmed / not; practice dose up / down from the probes. |
| `app/probes.py` (new) | Probe sets per area: choose, rotate, score (like `check_in_set.py`). |
| `app/agent/memory_tools.py`, `prompts/memory_update.yaml` | Report probe answers per item; his own view. |
| `app/caregiver_api.py`, `static/caregiver.*` | Baselines, treated/untreated lines, conversation measures, his view, the therapist's scores, the export. |
| `tests/` | Gating; probe scoring by code; baseline before practice; treated vs untreated; the export. |

## Done when
- [ ] A difficulty seen once is re-checked, and practiced only when confirmed (or set by the family) -- gradually.
- [ ] For the patient: no new checks; a confirmed change or a lasting improvement becomes a point for his therapist; his focus changes only through the family.
- [ ] The summarizing activity works, scored by main ideas.
- [ ] Each area has a probe set with a baseline, treated and untreated items, scored by code, shown over time.
- [ ] Conversation and his own view are shown on their own.
- [ ] The patient's sessions change only by the summarizing activity and his probe sets (A1, A2, B).
- [ ] `pytest` passes.

## Commit
`Sub-plan 16: practicing every area, measured like a therapist`
