# Sub-plan 12: Names he finds on his own, no early goodbyes, and a separate check-in

Part of the [master design](00-master-design.md). After [11](11-whatsapp-reminder.md). Requested by Tomer (2026-10-10).

## Why
Tomer noticed that Dad's sessions stopped producing word results. Looking at the sessions (no code changed), the reasons were:
- **The marking works; the tutor stopped asking.** The memory agent records only words the tutor practiced and check-in items she actually asked. On 4.10 she asked check-ins in both sessions. On 8.10–9.10 (5 sessions) the check-in answers mostly never came up: 2 results in total, both from one session.
- **She ends the sessions herself, early.** In 7 of the 8 sessions since 2.10, the tutor started the closing (summary, homework, goodbye) between minute **2.9 and 6.2**. The prompt says "do NOT start closing on your own; you'll get a note at ~9 minutes". The "end button" sessions were Dad pressing it *after* her goodbye. She has no clock: she sees the whole conversation at once, so when a story ends or the plan feels covered, it "feels" done.

  | Session | She started closing at | Ended |
  |---|---|---|
  | 9.10 | 5.9 min | 6.3 |
  | 8.10 11:00 | 3.9 min | 4.3 |
  | 8.10 10:44 | 8.3 min | 8.7 |
  | 8.10 10:37 | 2.9 min | 3.2 |
  | 8.10 10:24 | 5.4 min | 5.8 |
  | 4.10 12:09 | 4.5 min | 5.0 |
  | 4.10 10:49 | 6.2 min | 6.6 |
  | 2.10 | 4.6 min | 5.0 |
- **Woven-in check-ins wait for a moment that doesn't come.** The prompt allows a check-in only "when the conversation is near its topic, never in the middle of his story". When he steers elsewhere (the Golan, while the items were about Caesarea), the moment never comes.
- **An interrupted check-in is dropped.** On 9.10 she started the סי סנטר item, he spoke over her, and she never came back to it.
- **A misheard goodbye.** On 9.10 he said "אני רוצה ללכת" (meaning: walk the new promenade). She moved straight to the closing at 6.3 minutes.
- **A possible rule conflict (not proven).**
  - Since 8.5, every check-in is about his own life (the grounding guard).
  - Since prompt 1.5, the tutor must "never give him a name from his own life as the answer".
  - The hint ladder's last step is "say the word yourself".

  Together these may make her avoid items she can't finish.
- **Stale items.** Because they're never asked, היכל נעמי, זכרון יעקב and סי סנטר came back in 3–4 plans in a row.
- **Lost evidence.** On 9.10 he paused, described it ("מרחצאות... ברכות מים חמים") and found **חמת גדר** on his own. That's the best sign of progress there is (naming in real conversation), and today it isn't recorded, because only practiced words count.

## Goal
1. **Record names he finds on his own** (with effort), and names he **tried for and couldn't find**, as their own category. They feed the word bank and the next plans, without mixing into the check-in measure.
2. **No early goodbyes:** the tutor never starts the closing before about **8 minutes**, unless he asks to stop or is clearly tired.
3. **The check-in becomes its own short moment** ("a short names game"), at a fixed point in every session, instead of being woven into the conversation.

## Decisions (with Tomer, 2026-10-10)

### Names found on their own don't replace the check-ins
- **They only show successes.** A name he can't find, he talks around ("המקום עם המים החמים") or avoids, so it never appears. Only asking directly shows whether he can retrieve it.
- **The progress measure needs a fixed comparison.** Check-ins ask practiced ("treated") and never-practiced ("untreated") names the same way, without hints, every session. Names that come up on their own change with the topic, so there's no trend to compare.
- **So they work together.**
  - The check-in measures naming on request.
  - The names he finds on his own (or doesn't) measure naming in real conversation.
  - Both feed the word bank and the next plans.

### The check-in is a separate moment, not woven in (common practice)
How naming check-ins ("probes") are usually done in anomia therapy and research:
- A **short, fixed task**: the same items, asked the same way, at the same point in the session.
- **Before that day's practice.**
- **No hints or feedback during it.** A miss is recorded; the name is practiced afterwards.
- **Treated and untreated lists** that stay **stable** for weeks.
- **Conversation is where the practice happens, and it's measured separately.** Naming scores don't reliably predict word-finding in real talk, and practicing names in context transfers better than drills alone.

Sources: [anomia treatment outcomes](https://utoronto.scholaris.ca/items/27a6b06d-4a15-4920-b134-c1f3a3ba00e2), [cueing therapy case series](https://discovery-pp.ucl.ac.uk/id/eprint/1412975), [SFA in fluent aphasia](https://researchwith.montclair.edu/en/publications/semantic-feature-analysis-treatment-for-anomia-in-two-fluent-apha/), [Boyle 2014](https://pubs.asha.org/doi/10.1044/2014_AJSLP-13-0004), [drill vs discourse methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC3349434), [VoiceAdapt RCT 2025](https://mhealth.jmir.org/2025/1/e67711).

Our woven-in check-ins broke three of these:
- they were often never asked
- the question changed with the conversation
- she started the hint ladder right after a miss

### When: after a short warm-up, before the practice
- **Not near the end:**
  - **Same-session priming:** after talking about related places, it measures that day's practice, not what he kept.
  - **Fatigue:** after a stroke, tiredness builds within a session and would blur the results.
  - **It might never happen:** sessions end early (above).
  - **Ending on a miss:** a session shouldn't end on a name he couldn't find (the fatigue protocol says end on a success).
- **Not at the very first second:** he needs to warm up, and she needs to hear how he is.
- **So:**
  1. The opening (greeting, how he feels, small talk; about 2 minutes). This is also where she senses his state today.
  2. The names game (about 1–2 minutes).
  3. The main conversation and practice.
  4. The closing.

  If the opening shows he's tired or low, she **skips** the game that day, and it's recorded as skipped.

## Design

### A. Names he finds on his own (memory agent)
- **What counts.** Only **names** (places, people, landmarks), his core difficulty, and only with **visible effort**:
  - a pause or hesitation before it
  - describing it instead of naming it
  - a self-correction ("פרחת... בריכת המשושים")
  - asking himself "איך קוראים לזה"

  Names he says fluently are not recorded: he says many, and they'd bury the signal.
- **Two new results**, beside uncued / cued / failed:
  - `self_found`: he found it himself after the effort.
  - `not_found`: he tried and gave up, or talked around it, and the tutor didn't practice it.

  If the tutor practiced it afterwards, the existing results apply, as today.
- **Transcription errors.** Names from free talk have no planned answer to check against. They're marked low-confidence when the two transcript versions (the live captions and the model's own transcription) disagree. Example: the model's version of "בריכת המשושים" was "פרחת המשולשים". A low-confidence `self_found` is shown but doesn't move the schedule.
- **The word bank keeps where each name came from.** A new `source` field on each word: `practiced` / `self_found` / `not_found`.
  - **Code** decides "treated" from the source, not just from being in the bank. `next_class.py` today treats anything in the bank as treated. A name that was only found or missed in free talk was never practiced, so it's still "untreated" for the comparison.
  - **Schedule** (plain code, as today):
    - `self_found`: like uncued (the interval grows).
    - `not_found`: due next session.

### B. The names game (check-in) lists (plan builder + code)
- **Stable lists, not new items in every plan.** Each account has a **check-in set** stored beside the plan:
  - 3–5 **treated** names (practiced in conversation)
  - 3–5 matched **untreated** names (never practiced; same kind, same difficulty)

  The set stays for **about 3 weeks** (or ~10 sessions), then the plan builder proposes the next set, and the old one is kept for comparison.
- **Each session asks 2–3 of them, in rotation** (chosen in code: the least recently asked first; treated and untreated mixed). So each name is asked every few sessions, always the same way.
- **One fixed question per name**, written once when the set is made (a describing question: "איך נקרא בית הכנסת בקיסריה שבנוי בצורת ספר תורה?"). The same words every time.
- **Untreated names are never practiced** while the set is active. The plan builder's practice items must not include them (checked in code).
- **Where names come from:**
  - names he **couldn't find** (`not_found`) go to **practice** first, and later into a treated set
  - names he **found on his own** can enter an untreated set
  - everything from his own data, as today (the 8.5 grounding guard)
- **The plan builder keeps choosing the practice:** practice items, activity, topics. It no longer picks check-ins for each session.

### C. The names game in the session (tutor prompt + a cue from the app)
- **A cue from the app (code).** At about **2 minutes**, the page sends a silent note, which Dad never sees or hears: "[Now is the time for the short names game: at the next natural pause, after he finishes his sentence.]" She doesn't need to judge the moment, and it can't slip away.
- **How she runs it (prompt):**
  - **Introduce it lightly, as a game, never a test:** "בוא נעשה משחק קצר של שמות: אני אתאר, ואתה תגיד לי איך קוראים לזה."
  - **Ask the item's fixed question, word for word.** Then wait: give him real time, at least ~10 seconds of silence is fine.
  - **No hints during the game.** If he finds it, a short warm "נכון!". If not, she says the name warmly in one sentence ("זה היכל נעמי, בית הכנסת היפה שלכם") and moves on. No hint ladder, no second try.
  - 2–3 names, then a natural bridge into the conversation: "יופי, ועכשיו ספר לי…".
  - **If he's tired or low in the opening:** she skips the game and says nothing about it. She calls a `skip_names_game` note so it's recorded. The live model has one tool today (`end_session`); this adds a second, which only logs.
  - **If he interrupts:** she finishes the item at the next pause. The game is short, so it's easy to return to.
- **The answers are scored as today** (the memory agent, `probe=true`, his first attempt): uncued / failed. There's no "cued", since there are no hints in the game.
- **A name he missed in the game** may be practiced later in the same conversation, with the hint ladder. The game result stays as recorded.
- **Resolve the rule conflict.** "Never give him a name from his own life as the answer" is about invented people and places. For a name in TODAY'S PLAN or the names game (checked against his data, 8.5), saying the name is allowed. "HIS LIFE IS HIS" still wins: if he says it's wrong, she believes him at once, and the name is reported as a tutor issue (as today).

### D. No early goodbyes (tutor prompt + time notes from the app)
- **Time notes from the app (code).** Besides the ~2-minute names-game cue and the existing ~9-minute wrap-up note, short silent notes:
  - **~4 min:** "[About 4 minutes have passed, about 5 to go. It is NOT time to close: keep the conversation going.]"
  - **~7 min:** "[About 7 minutes have passed, about 2 to go. Not time to close yet.]"

  This gives her the clock she doesn't have: the same approach that fixed "yesterday" (facts from code, not a stricter rule).
- **Prompt rules:**
  - Before the wrap-up note: no summary, no homework, no "נהניתי לשמוע", no goodbye.
  - When a story or the plan feels finished, that's the moment for the **next thread** (the next plan item, a practice name, one of his interests), not the end.
  - Exceptions, as today: he asks to stop, or he's clearly tired (the fatigue protocol).
- **Ambiguous goodbyes.** If he says something like "אני רוצה ללכת" in the middle of a topic, she checks gently ("לטייל בטיילת, או שאתה רוצה לסיים להיום?") before closing.
- **Code backstop:** if she calls `end_session` before ~8 minutes without his goodbye, the page logs it as `tutor_early_goodbye`. It's shown on the caregiver page and counted in the checks. The page doesn't block it: by then she has said goodbye out loud, and holding him on the line would be worse.
- **Homework moves fully to the closing.** The plan's homework line will say "only after the wrap-up note", since today it may be what triggers her closing.

### E. Caregiver page
- In each session:
  - **The names game:** asked (which names, ✓/✗), or skipped and why.
  - **Who ended the session and when**, including "the tutor said goodbye early" (`tutor_early_goodbye`).
  - "**מצא לבד**" (found on his own) and "**לא מצא**" (couldn't find) lines.
- **The check-in set:** its treated and untreated names, since when, and each name's results over time. A button to start a new set.
- **The word bank:** a source column, with the new results counted separately.
- **The progress graph:**
  - the names game as the main naming measure (treated vs untreated)
  - names found on his own as their own series
- **The therapist export:** the names-game results by set, and the names he found or couldn't find since the last export.

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `WordResult.self_found` / `not_found`; `WordStats.source`; the check-in set; `tutor_early_goodbye`. |
| `app/word_bank.py` | Schedule for the new results; low confidence doesn't move the schedule for `self_found`. |
| `app/check_in_set.py` (new) | The stable set; choosing 2–3 names per session in rotation; when to propose a new set; untreated names kept out of practice. |
| `app/agent/memory_tools.py`, `prompts/memory_update.yaml` | `record_word_result` with the new results (names only, visible effort); names-game answers as probes (first attempt, no "cued"). |
| `app/agent/next_class.py`, `prompts/next_class.yaml` | "Treated" from the source; propose a check-in set (fixed questions) when one is due; practice from `not_found` names first; no untreated names in practice; no per-session check-ins. |
| `app/class_plan.py` | TODAY'S PLAN shows the names-game items (fixed questions); the homework line says "only after the wrap-up note". |
| `prompts/tutor.yaml` | The names game (when, how, no hints, skipping); no closing before the wrap-up note; a finished thread leads to the next one; ambiguous goodbyes; the rule conflict. |
| `app/live_token.py` | The `skip_names_game` tool (log only). |
| `static/app.js` | Notes at ~2 (names game), ~4 and ~7 minutes; `skip_names_game`; log `tutor_early_goodbye`. |
| `app/caregiver_api.py`, `static/caregiver.*` | The names game per session, the check-in set and "new set", found on his own / couldn't find, the word bank source, progress and the export. |
| `tests/` | The new results and their schedule; treated vs untreated by source; the set's rotation and lifetime; untreated never in practice; the time notes; `tutor_early_goodbye`; fake memory-agent runs on a transcript like 9.10 (חמת גדר → `self_found`; fluent names not recorded). |

## Check before deploying
- **Re-run the memory agent on 9.10's transcript (dry run, nothing saved).** Expected: חמת גדר → `self_found`, בריכת המשושים → `self_found` low-confidence or not recorded, רמת הגולן (said fluently) → not recorded.
- **Build Dad's first check-in set (dry run, nothing saved).** Tomer reviews the names and questions before it goes live. Expected: everything from his data; untreated names not in practice.

## Done when
- [ ] In Dad's next 5 sessions, the names game happened (or was skipped with a reason) in every one, at about minute 2–3.
- [ ] In Dad's next 5 sessions, the tutor doesn't start the closing before ~8 minutes (unless he asked to stop).
- [ ] The names game feels light to him (Tomer asks him after a few sessions).
- [ ] Names he found on his own or couldn't find appear on the caregiver page, separate from the names game.
- [ ] A name only found in free talk is never counted as "treated"; an untreated name is never practiced.
- [ ] `pytest` passes.

## Commit
`Sub-plan 12: names he finds on his own, no early goodbyes, and a separate check-in`
