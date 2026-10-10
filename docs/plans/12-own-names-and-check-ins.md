# Sub-plan 12: Names he finds on his own, and check-ins that actually happen

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
- **Short sessions leave no room, and his topic leads.** The prompt allows a check-in only "when the conversation is near its topic, never in the middle of his story", so when he steers elsewhere (the Golan, while the items were about Caesarea), the moment never comes.
- **An interrupted check-in is dropped.** On 9.10 she started the סי סנטר item, he spoke over her, and she never came back to it.
- **A misheard goodbye.** On 9.10 he said "אני רוצה ללכת" (meaning: walk the new promenade). She moved straight to the closing at 6.3 minutes. The wrap-up note only comes at ~9 minutes.
- **A possible rule conflict (not proven).**
  - Since 8.5, every check-in is about his own life (the grounding guard).
  - Since prompt 1.5, the tutor must "never give him a name from his own life as the answer".
  - The hint ladder's last step is "say the word yourself".

  Together these may make her avoid items she can't finish.
- **Stale items.** Because they're never asked, היכל נעמי, זכרון יעקב and סי סנטר came back in 3–4 plans in a row.
- **Lost evidence.** On 9.10 he paused, described it ("מרחצאות... ברכות מים חמים") and found **חמת גדר** on his own. That's the best sign of progress there is (naming in real conversation), and today it isn't recorded, because only practiced words count.

## Goal
1. **Record names he finds on his own** (with effort), and names he **tried for and couldn't find**, as their own category. They feed the word bank and the next plans, without mixing into the check-in measure.
2. **No early goodbyes:** the tutor never starts the closing before about **8 minutes**, unless he asks to stop or is clearly tired. That leaves room for the naming practice.
3. **Make the check-ins happen:** 1–2 in every session.

## Why names found on their own don't replace the check-ins (decided with Tomer, 2026-10-10)
- **They only show successes.** A name he can't find, he talks around ("המקום עם המים החמים") or avoids, so it never appears. Only asking directly shows whether he can retrieve it.
- **The progress measure needs a fixed comparison.** Check-ins ask practiced ("treated") and never-practiced ("untreated") names the same way, without hints, every session. Names that come up on their own change with the topic, so there's no trend to compare.
- **So they work together:**
  - During the session, the tutor asks the check-ins, and the memory agent also notes the names he found or couldn't find.
  - All of these go into the word bank, each with its source.
  - The next plan picks its check-ins and practice items from the word bank, with names he couldn't find first in line.

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

  If the tutor did practice it afterwards, the existing results apply, as today.
- **Transcription errors.** Names from free talk have no planned answer to check against. They're marked low-confidence when the two transcript versions (the live captions and the model's own transcription) disagree. Example: the model's version of "בריכת המשושים" was "פרחת המשולשים". A low-confidence `self_found` is shown but doesn't move the schedule.
- **The word bank keeps where each name came from.** A new `source` field on each word: `practiced` / `self_found` / `not_found`.
  - **Code** decides "treated" from the source, not just from being in the bank. `next_class.py` today treats anything in the bank as treated. A name that was only found or missed in free talk was never practiced, so it's still "untreated" for the check-in comparison.
  - **Schedule** (plain code, as today):
    - `self_found`: like uncued (the interval grows).
    - `not_found`: due next session.
- **Also recorded:** a name the tutor started to ask but the session moved on before he answered. It goes into the session's notes, not the word bank, so the plan builder knows it wasn't really asked.

### B. Plans built from them (plan builder)
- Names he **couldn't find** are first in line for **practice items**. Once practiced, they become "treated" check-in candidates.
- Names he **found on his own** can be check-ins (as untreated, until practiced): a good test of whether it sticks.
- **No stale items.** A check-in item that was in the last two plans and never asked is replaced or moved to the first slot, not repeated a third time unchanged. The never-asked count is computed in code from the session records.

### C. No early goodbyes (tutor prompt + time notes from the app)
- **Time notes from the app (code).** The page already sends her a note at ~9 minutes ("time to wrap up"). It will also send short, silent time notes, which Dad never sees or hears:
  - **~3 min:** "[About 3 minutes have passed, about 6 to go. It is NOT time to close: keep the conversation going.]"
  - **~6 min:** "[About 6 minutes have passed, about 3 to go. Not time to close yet.]", plus, if the session has check-in items: "If you haven't asked a check-in item yet, now is a good moment."

  This gives her the clock she doesn't have: the same approach that fixed "yesterday" (facts from code, not a stricter rule).
- **Prompt rules:**
  - Before the wrap-up note: no summary, no homework, no "נהניתי לשמוע", no goodbye.
  - When a story or the plan feels finished, that's the moment for the **next thread**: the next plan item, a check-in, or one of his interests. It is not the end.
  - Exceptions, as today: he asks to stop, or he's clearly tired (the fatigue protocol). She also checks an ambiguous phrase first (below), instead of treating it as a goodbye.
- **Code backstop:** if she calls `end_session` before ~8 minutes without his goodbye, the page logs it as `tutor_early_goodbye`, so the caregiver page and the next checks show it. The page doesn't block it: by then she has already said goodbye out loud, and holding him on the line would be worse.
- **Homework moves fully to the closing.** Today the plan's homework line ("Homework to give at the end") may be what triggers her closing. Its wording in TODAY'S PLAN will say "only after the wrap-up note".

### D. Check-ins that happen (tutor prompt)
- **At least one check-in in every session**, ideally two, **by about minute 6** (the time note reminds her). If the conversation hasn't come near an item's topic by then, use the item's lead-in or a gentle explicit transition ("רגע, נזכרתי במשהו…").
- **Come back after an interruption.** If he spoke over a check-in question, return to it at the next pause.
- **Resolve the rule conflict.** The "never give him a name from his own life as the answer" rule is about invented people and places. For a check-in or practice item that is in TODAY'S PLAN (the plan builder already checked it against his data, 8.5), the last hint step (say it yourself, let him use it) is allowed. "HIS LIFE IS HIS" still wins: if he says it's wrong, she believes him at once.
- **Ambiguous goodbyes.** If he says something like "אני רוצה ללכת" in the middle of a topic, check gently ("לטייל בטיילת, או שאתה רוצה לסיים להיום?") before closing.
- The ~6-minute time note reminds her about check-ins. It doesn't detect live whether one was asked (that's hard to spot reliably): it only reminds her.

### E. Caregiver page
- In each session: **who ended it and when**, including "the tutor said goodbye early" (`tutor_early_goodbye`).
- In each session: "**מצא לבד**" (found on his own) and "**לא מצא**" (couldn't find) lines, beside the check-in results.
- In the word bank: a source column, and the new results counted separately.
- In the progress graph: names found on his own over time, as their own series (not mixed into the check-in measure).
- In the therapist export: the names he found on his own and couldn't find, since the last export. This is useful to his speech therapist.

## Files
| File | Purpose |
|---|---|
| `app/schemas.py` | `WordResult.self_found` / `not_found`; `WordStats.source`. |
| `app/word_bank.py` | Schedule for the new results; low confidence doesn't move the schedule for `self_found`. |
| `app/agent/memory_tools.py`, `prompts/memory_update.yaml` | `record_word_result` with the new results and when to use them (names only, visible effort); asked-but-interrupted check-ins into the session notes. |
| `app/agent/next_class.py`, `prompts/next_class.yaml` | "Treated" from the source; names he couldn't find go to practice first; stale never-asked check-ins replaced. |
| `prompts/tutor.yaml` | No closing before the wrap-up note (no summary / homework / goodbye); a finished thread leads to the next one; check-ins by ~minute 6; return after an interruption; hint ladder allowed for planned items; ambiguous goodbyes. |
| `static/app.js` | Time notes at ~3 and ~6 minutes; log `tutor_early_goodbye` when she ends before ~8 minutes without his goodbye. |
| `app/class_plan.py` | The homework line says "only after the wrap-up note". |
| `app/schemas.py` (end reasons) | `tutor_early_goodbye`. |
| `app/caregiver_api.py`, `static/caregiver.*` | Found on his own / couldn't find in sessions, the word bank, progress and the export. |
| `tests/` | The new results and their schedule; treated vs untreated by source; the stale-item rule; fake memory-agent runs on a transcript like 9.10 (חמת גדר recorded as `self_found`; fluent names not recorded). |

## Check before deploying
- **Re-run the memory agent on 9.10's transcript (dry run, nothing saved).** Expected: חמת גדר → `self_found`, בריכת המשושים → `self_found` low-confidence or not recorded, רמת הגולן (said fluently) → not recorded.
- **Build a plan for Dad (dry run, nothing saved).** Expected: no check-in repeated a third time; any `not_found` name is in practice, not in the check-ins.

## Done when
- [ ] In Dad's next 5 sessions, the tutor doesn't start the closing before ~8 minutes (unless he asked to stop).
- [ ] In Dad's next 5 sessions, at least one check-in was asked in at least 4.
- [ ] Names he found on his own or couldn't find appear on the caregiver page, separate from the check-in results.
- [ ] A name only found in free talk is never counted as "treated".
- [ ] `pytest` passes.

## Commit
`Sub-plan 12: names he finds on his own, and check-ins that actually happen`
