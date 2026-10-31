# Sub-plan 21: Editing the memory, and a face-lift

Part of the [master design](00-master-design.md). After [20.5](20.5-leaving-a-conversation-out.md), before [22](22-picture-sequences.md). Requested by Tomer (2026-10-30); the face-lift (Part D) added the same day, its mockups approved by him.

**Status (31.10): built and deployed (00113); then blue instead of teal, and the two free-text blocks made editable (not yet deployed).**
- Built as planned, with these choices:
  - **Errors.** An item or word that's no longer there, or a duplicate, gets 409. An empty or too-long text, or a full section, gets 422.
  - **Blocked words.** His own names, which code adds, skip a blocked word silently. The memory agent's `update_profile` is refused with an error it sees.
  - **Empty sections** show their heading and "+ הוספה", so the family can add to them.
  - **The end button** keeps its text, "סיום".
  - **The conversation cards** keep "תמלול מלא" visible; the other actions are in the "⋯" menu.
- **Checked in a headless browser:** his three screens at phone width, and the caregiver page in light and dark (static previews, invented content).
- **Left:** the three manual checks (Task 3, Step 3; Task 5, Step 6; Task 6, Step 6), after a deploy.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the family can fix what the app learned about him, directly on the caregiver page. They can edit and add memory items, edit or remove a session summary, and remove or add words in his profile's vocabulary (his names and places). A word they remove is never added back by the app. **Part D:** both pages get a calmer, warmer look. His app shows his practice streak and, after a session, only what went well. The caregiver page gets a summary on top and four tabs.

**Architecture:** every edit is code, not a model call. It follows the pattern of the existing `remove_item` (`app/agent/memory_edit.py`): the previous version goes into `memory_history`, a bucket backup is kept (`_backup`), and the text she reads is rendered again (`render_memory` / `render_inferred`). The family's removals go on a `vocabulary_blocked` list on the inferred profile, and the memory agent's `update_profile` refuses a blocked word.

**Tech Stack:** FastAPI, Firestore (and the in-memory store for tests), vanilla JS pages, pytest, `node --test` for the pages' pure modules.

**Spec:** this file (Why, Goal, Design below).

## Global Constraints
- The repo is public: no names, words or transcripts of his in code, tests or this file. Test data is invented.
- No model calls: an edit is applied at once and shows in the next session's prompt.
- Every edit can be undone: the replaced memory goes into `memory_history` (restorable from the existing versions list), and the replaced profile goes to the bucket backup.
- The limits the memory agent works under hold for the family too: `MAX_ITEM_CHARS` (200) per item, `MAX_ITEMS_PER_SECTION` (25) per section, `MAX_ABOUT`/`MAX_ABOUT_CHARS` (8 / 160) and `MAX_VOCABULARY`/`MAX_VOCABULARY_CHARS` (40 / 40) for the profile.
- Every new caregiver-page text is Hebrew. Only caregivers (`require_caregiver`) can edit.
- **Part D:** his app keeps its flow, its buttons and their size; nothing for him to learn again. His screens never show a miss, a "מתוך" or a zero.
- Production deploys only on Tomer's explicit "deploy"; commit and push only when he asks.

## Review Focus
1. **The memory changed while the page was open** (a memory update finished after the page loaded): an edit of an item that's no longer there is refused with 409 ("the memory changed, reload"), never applied to the wrong item. -> test in Task 1.
2. **A removed vocabulary word comes back in a later session** (the memory agent hears it again and adds it): the agent's `add` is refused for a blocked word, so the word stays out. -> test in Task 2.
3. **An uploaded profile** (`source: "uploaded"`, written by the family): it has no `vocabulary` list, since its words come from its "Vocabulary:" line. The vocabulary editor edits only the inferred profile and says so for an uploaded one; it never turns one kind into the other. -> test in Task 2.
4. **An edit to the newest summary**: the "Last time" line in her prompt changes too (`render_memory` reads `recent_summaries[-1]`). -> test in Task 1.
5. **An empty or whitespace-only edit**: refused with 422. Removing is a separate action, so an empty edit never removes an item by accident. -> test in Task 1.
6. **The streak before today's session, and after a missed day** (Part D): in the morning, before he practiced, yesterday's streak still counts ("4 ימים ברצף", not 0). After a missed day the screen says "היום מתחילים רצף חדש", never "0". -> test in Task 4.

---

## Why
- **The family can only remove.** Today the caregiver page can remove a memory item, remove a word-bank word, restore an older version, or rewrite the whole profile (which turns it into an "uploaded" profile that the app stops updating). They can't fix a wrong detail ("3 grandchildren", not 2), add something the tutor should know, or correct a session summary.
- **A misheard word can feed itself** (30.10, on a test account). The memory agent added a misheard word to the profile's vocabulary. The vocabulary is sent to Gemini Live as `custom_vocabulary`, so the transcription then heard that word at the start of almost every line. The transcripts went back to the memory agent, which kept it on the list. Removing it took a manual database edit. The family should be able to remove it, and once removed it must stay out. **Fixed at the root on 30.10:** the vocabulary isn't sent to the transcription any more (a replay of that session's audio with and without the list showed the list caused it). The words are still in the profile she and the plan builder read, though, so a wrong one there still misleads them, and the family still needs a way to remove it.

## Goal
On the caregiver page's memory card:
1. **Edit or add an item** in each memory section (about him, interests, what helped, what to avoid, how he speaks, homework).
2. **Edit or remove a session summary** (the last few, `recent_summaries`).
3. **His names and places** (the profile's vocabulary): see the words, remove one (it's blocked from coming back), add one.

## Design

### A. Memory items and summaries (`app/agent/memory_edit.py`)
- `edit_item(store, pid, section, old, new) -> dict`: replaces `old` with `new`, at the same place in the list.
- `add_item(store, pid, section, text) -> dict`: appends it, so it counts as newest and she reads it first. Refused when the section is full ("remove one first").
- `edit_summary(store, pid, date, old, new) -> dict` and `remove_summary(store, pid, date, old) -> dict`: a summary is found by its date and its exact text.
- All of them follow `remove_item`: `MemoryEditError` on bad input (unknown section, item not found, empty, too long, full); then `render_memory`, then `store.save_memory(pid, f"edit-{_stamp()}", new, current)`.
- **Added 31.10 (Tomer): the two free-text blocks.**
  - `edit_text(store, pid, old, text) -> dict`, at POST `/memory/edit-text`, edits her whole text ("מה המטפלת מקבלת בתחילת כל שיחה").
    - The text is rendered by code, so it is read back into the memory: each heading's "- " lines become that section, with the top line as the newest; the "Last time" lines become the last summary.
    - A deleted heading empties its section. A deleted "Last time" block removes the last summary.
    - Any other line is refused with 422, because the next render would drop it. A text that changed in the meantime (`old`) gets 409.
  - `edit_focus(store, pid, items) -> dict`, at POST `/memory/edit-focus`, replaces the focus points ("דגשים לשיחה הבאה"): one per line, at most 4. The next session's memory update sets new ones, as before.
- **The memory agent's next update** works from the edited sections like from any others. A family item isn't protected from it: the agent rarely removes items, and the versions list can bring one back. If that turns out wrong, protecting family items is a follow-up.

### B. The vocabulary (`app/patient_profile.py`, `app/agent/memory_tools.py`)
- The inferred profile gets `vocabulary_blocked: list[str]` (normalized words, at most 100).
- `remove_vocabulary(store, pid, word) -> dict` takes the word out of `vocabulary` and adds it to `vocabulary_blocked`. `add_vocabulary_word(store, pid, word) -> dict` adds it newest-first, as `add_vocabulary` does, and takes it off `vocabulary_blocked`. Both re-render the profile text with `render_inferred` and save it with `extra={"about", "vocabulary", "vocabulary_blocked"}`.
- **The memory agent:**
  - `update_profile` with `op: "add"` and a blocked word raises `ValueError("the family removed this word: don't add it")`;
  - `memory_update` loads `vocabulary_blocked` into the draft and saves it back unchanged.
- **Every other writer of the inferred profile** keeps `vocabulary_blocked`: `caregiver_api.set_need`, which re-renders the profile (`app/caregiver_api.py:386`), and `memory_update`.

### C. The caregiver page (`static/caregiver.js`)
- Each memory item gets "✎" next to the existing "✕". It opens an inline text box with "שמירה" / "ביטול". Each section ends with "+ הוספה".
- The summaries list ("שיחות אחרונות"): each summary has ✎ and ✕.
- A new block, "שמות ומקומות שלו (בפרופיל)", lists the vocabulary words as chips, each with ✕ ("להסיר? האפליקציה לא תוסיף אותה שוב"), plus a box to add a word. The blocked words show below in grey, each with "↩ להחזיר" (that's `add_vocabulary_word`). For an uploaded profile, the block says the words come from the profile's "Vocabulary:" line and the editor is hidden.
- After each edit: the card reloads, with the existing status line ("✓ נשמר. הגרסה הקודמת נשמרה ברשימת הגרסאות."). On 409: "הזיכרון השתנה בינתיים. רענן ונסה שוב."
- `versionKind` shows "· לפני עריכה" for `edit-` versions (it says "לפני הסרה" today).

### D. A face-lift for both pages (approved mockups: Tomer, 30.10)
**Look.** A deep blue for him and "go", a warm orange ("sun") for her, on a calm cool-grey ground; deep ink text, not black. The tokens live in `style.css`'s `:root` and the caregiver page uses the same ones. Fonts: **Rubik** for headings and buttons and **Assistant** for text, both with Hebrew. They are self-hosted as woff2 in `static/fonts/` (SIL OFL; no Google request from his device, and the app keeps working if Google is slow). The fallback is today's `"Segoe UI", Arial`.

**His app (`static/index.html`, `style.css`, `app.js`).**
- **Start screen:**
  - a greeting by the time of day ("בוקר טוב" / "צהריים טובים" / "ערב טוב") above "מוכן לשיחה של היום?";
  - his **streak** with a compliment that changes as the streak grows;
  - the reminder as one quiet line ("🔔 תזכורת יומית ב־10:00 · לשנות").
- **During the session:**
  - **Whose turn:** one large label, "היא מדברת…" in orange or "תורך לדבר" in blue, from the existing indicator states.
  - **The mic:** the level bar moves into a ring around her photo, which thickens with his voice.
  - **Captions:** older caption lines fade, so his eye lands on the newest one.
  - **Buttons:** "אני חושב…" and "השתקה" side by side, with "סיום השיחה" full width under them.
- **End screen, only what went well:**
  - "דיברנו היום N דק׳";
  - "שמות שמצאת לבד N" (the page's own names-game matches, 20);
  - the streak.

  No "מתוך", no misses, and a row whose number is 0 isn't shown. The details stay on the caregiver page.
- **The emergency button:** same place, always visible, but a red outline, not a solid red block.

**The streak (`app/reminders.py`, `/api/me`).** `practice_streak(store, pid, today) -> {"days": int, "today": bool}` counts the days in a row with a session of 2+ lines (`practiced_on`'s rule), ending today, or yesterday when he hasn't practiced yet today. Left-out sessions count: he did talk (20.5). `/api/me` returns it as `practice`. The page then chooses the text:
- `days >= 2`: "N ימים ברצף", with a compliment for the streak's size;
- `days == 1`: "התחלת רצף. נמשיך מחר?";
- `days == 0`: "היום מתחילים רצף חדש".

The compliments are fixed Hebrew lines in `static/praise.js`, chosen by the streak's size: 2, 3–4, 5–6, 7–13, 14+.

**The caregiver page (`static/caregiver.html`, `caregiver.css`, `caregiver.js`).**
- **Four summary tiles on top:**
  - the last conversation (when, minutes, mood);
  - what needs attention (open flags);
  - the names game over two weeks, with a small trend line;
  - the next lesson (ready / failed).
- **Four tabs instead of 17 collapsible sections.** The last open tab is remembered in `localStorage`, and `#tab` links open a tab.
  - סקירה: flags, progress, conversations;
  - השיעור הבא: plan, names game, the next prompt, notes;
  - מה היא יודעת: memory (with Part C's editors), profile, needs, word bank, adjustments;
  - כלים: export, voice settings, research, games, reset, the emergency info.
- **Conversations as cards** with result chips. Their buttons (transcript, prompt, recording, process, leave out) move into one "⋯" menu.
- **A dark mode** (`prefers-color-scheme`), for the caregiver page only. His app stays light: one look he knows.

## Files
| File | Change |
|---|---|
| `app/agent/memory_edit.py` | `edit_item`, `add_item`, `edit_summary`, `remove_summary` (A). |
| `app/patient_profile.py` | `remove_vocabulary`, `add_vocabulary_word`; `vocabulary_blocked` (B). |
| `app/agent/memory_tools.py`, `app/agent/memory_update.py` | A blocked word is refused, and the list is kept (B). |
| `app/caregiver_api.py` | `POST .../memory/edit-item`, `.../memory/add-item`, `.../memory/edit-summary`, `.../memory/remove-summary`, `.../vocabulary/remove`, `.../vocabulary/add`; `set_need` keeps `vocabulary_blocked`; the overview returns `vocabulary`, `vocabulary_blocked`, the profile's `source` and `recent_summaries`. |
| `static/caregiver.js`, `static/caregiver.html`, `static/caregiver.css` | The editors (C). |
| `docs/tools.md` | Regenerated (`python -m app.tools_catalog`) if `update_profile`'s description changes. |
| `static/style.css`, `static/index.html`, `static/app.js` | His app's look, the start and end screens (D). |
| `static/fonts/` (new) | Rubik and Assistant woff2, Hebrew + Latin, with their OFL license file. |
| `static/praise.js` (new) | `streakLine(practice) -> {title, praise}`: pure, dependency-free (D). |
| `app/reminders.py`, `app/main.py` | `practice_streak`; `/api/me` returns `practice` (D). |
| Tests | `tests/test_caregiver.py` (next to the `remove_item` tests), `tests/test_memory.py`, `tests/test_reminders.py` (the streak), `tests/js/praise.test.mjs`. |

## Tasks

### Task 1: Editing and adding memory items and summaries

**Files:** `app/agent/memory_edit.py`, `app/caregiver_api.py`; tests in `tests/test_caregiver.py`, next to the `remove_item` tests.

**Interfaces:**
- Produces:
  - `edit_item(store, pid, section: str, old: str, new: str) -> dict`;
  - `add_item(store, pid, section: str, text: str) -> dict`;
  - `edit_summary(store, pid, date: str, old: str, new: str) -> dict`;
  - `remove_summary(store, pid, date: str, old: str) -> dict`.
- Each returns the new memory, or raises `MemoryEditError`.
- The endpoints take a JSON body with the same names. They return `{"ok": True, "memory_prompt": ..., "backup": ...}`, 409 for not found, 422 for empty, too long or full.

- [x] **Step 1: Write the failing tests** (invented data):

```python
def test_edit_item_replaces_in_place_and_rerenders(store, pid):  # memory with personal_facts ["has 2 grandchildren", "likes tea"]
    new = edit_item(store, pid, "personal_facts", "has 2 grandchildren", "has 3 grandchildren")
    assert new["sections"]["personal_facts"] == ["has 3 grandchildren", "likes tea"]
    assert "has 3 grandchildren" in new["memory_prompt"] and "has 2" not in new["memory_prompt"]
    assert store.list_memory_history(pid)  # the old version is restorable

def test_edit_of_a_changed_item_is_refused(store, pid):  # Review Focus 1
    with pytest.raises(MemoryEditError): edit_item(store, pid, "personal_facts", "not there", "x")

def test_empty_edit_is_refused(store, pid):  # Review Focus 5
    with pytest.raises(MemoryEditError): edit_item(store, pid, "personal_facts", "likes tea", "   ")

def test_add_item_is_newest_and_full_section_refused(store, pid): ...
def test_editing_the_newest_summary_changes_last_time(store, pid):  # Review Focus 4
    new = edit_summary(store, pid, "2026-01-02", "<old text>", "He talked about the garden.")
    assert "He talked about the garden." in new["memory_prompt"]
def test_remove_summary(store, pid): ...
def test_edit_endpoints_need_a_caregiver_and_map_errors(client, ...):  # 409 / 422 / 403
```

- [x] **Step 2:** `pytest -k "edit_item or add_item or summary" -v`. Expected: FAIL (not defined).
- [x] **Step 3:** Implement the four functions, following `remove_item`. Normalize the text with `" ".join(text.split())` and apply the limits from Global Constraints.
- [x] **Step 4:** Add the endpoints, each with `_backup(archive, pid, store.get_memory(pid), "edit-item")` (and so on) and a `[caregiver]` log line, like `memory_remove_item`.
- [x] **Step 5:** `pytest`. Expected: all pass.

### Task 2: The vocabulary, with the blocked list

**Files:** `app/patient_profile.py`, `app/agent/memory_tools.py`, `app/agent/memory_update.py`, `app/caregiver_api.py`; tests in `tests/test_caregiver.py` and `tests/test_memory.py`.

**Interfaces:**
- Produces:
  - `remove_vocabulary(store, pid, word: str) -> dict` (the new profile);
  - `add_vocabulary_word(store, pid, word: str) -> dict`;
  - the profile field `vocabulary_blocked: list[str]`.
- Both raise `ValueError` for an uploaded profile or a word that isn't there. The endpoints map that to 409.
- Consumes `render_inferred` and `add_vocabulary`.

- [x] **Step 1: Write the failing tests:**

```python
def test_removed_word_leaves_the_vocabulary_and_the_text(store, pid):  # inferred, vocabulary ["Dalia", "Haifa"]
    prof = remove_vocabulary(store, pid, "Dalia")
    assert prof["vocabulary"] == ["Haifa"] and prof["vocabulary_blocked"] == ["Dalia"]
    assert extract_vocabulary(prof["text"]) == ["Haifa"]  # what she reads

def test_the_memory_agent_cannot_add_a_blocked_word(...):  # Review Focus 2
    # draft loaded from a profile with vocabulary_blocked ["Dalia"]
    with pytest.raises(ValueError): update_profile({"field": "vocabulary", "op": "add", "item": "Dalia"})
    # and after the memory update, the saved profile still has vocabulary_blocked ["Dalia"]

def test_adding_a_word_back_unblocks_it(store, pid): ...
def test_an_uploaded_profile_is_not_edited(store, pid):  # Review Focus 3
    with pytest.raises(ValueError): remove_vocabulary(store, pid, "Dalia")
def test_setting_a_need_keeps_the_blocked_list(client, store, ...): ...
```

- [x] **Step 2:** `pytest -k "vocabulary or blocked" -v`. Expected: FAIL.
- [x] **Step 3:** Implement B.
- [x] **Step 4:** Add the endpoints `.../vocabulary/remove` and `.../vocabulary/add`, with a backup of the profile. Add `vocabulary`, `vocabulary_blocked`, `source` and `recent_summaries` to the overview.
- [x] **Step 5:** `pytest`. Expected: all pass. If `docs/tools.md` changed, regenerate it, and check that `test_tools_catalog` passes.

### Task 3: The caregiver page

**Files:** `static/caregiver.js`, `static/caregiver.html`, `static/caregiver.css`.

**Interfaces:** consumes the endpoints from Tasks 1 and 2.

- [x] **Step 1:** Add the item editors (✎ and "+ הוספה"), the summaries list with ✎ and ✕, and the vocabulary block with its chips, grey blocked words and add box (Design C).
- [x] **Step 2:** `node --input-type=module --check < static/caregiver.js` (or the plain `--check` if it's not a module).
- [ ] **Step 3: Manual check on a test account:**
  - edit an item, add one, edit the last summary, and see each in "the prompt for the next session";
  - remove a vocabulary word, then confirm it's gone from "the prompt for the next session" and isn't back after a session;
  - restore a version from the versions list.

### Task 4: The streak

**Files:** `app/reminders.py`, `app/main.py`, `static/praise.js`; tests in `tests/test_reminders.py` and `tests/js/praise.test.mjs`.

**Interfaces:**
- Produces `practice_streak(store, pid: str, today: dt.date) -> dict` (`{"days": int, "today": bool}`).
- `/api/me` gets `"practice"`.
- `streakLine({days, today}) -> {title: string, praise: string}`.

- [x] **Step 1: Write the failing tests** (invented sessions):

```python
def test_the_streak_counts_days_in_a_row_ending_today():          # 3 days incl. today -> {"days": 3, "today": True}
def test_before_todays_session_yesterdays_streak_still_counts():   # Review Focus 6: yesterday + 2 before -> {"days": 3, "today": False}
def test_a_missed_day_starts_over():                               # practiced 2 days ago only -> {"days": 0, ...}
def test_a_one_line_session_isnt_practice_but_a_left_out_one_is():
def test_me_returns_the_streak(env):
```

```js
test("a streak gets its number and a compliment", ...)   // {days: 5} -> title "5 ימים ברצף", praise non-empty
test("one day, and zero, are never a sad number", ...)    // {days: 0} -> title "היום מתחילים רצף חדש"; no "0" in either text
```

- [x] **Step 2:** Run `pytest -k streak -v` and `node --test tests/js/*.test.mjs`. Expected: FAIL.
- [x] **Step 3:** Implement `practice_streak`, using `list_sessions(pid, 60, left_out=True)`, at most 60 days back. Then implement `streakLine` and the compliments.
- [x] **Step 4:** Both test commands. Expected: all pass.

### Task 5: His app's face-lift

**Files:** `static/style.css`, `static/index.html`, `static/app.js`, `static/fonts/`.

**Interfaces:** consumes `practice` from `/api/me` and `streakLine` (Task 4). The end screen's names count is the number of patient lines with `matchedTarget` (20).

- [x] **Step 1:** Add the fonts (woff2 + OFL license) and the `@font-face` rules. Then the new tokens in `:root`; every existing color goes through a token.
- [x] **Step 2:** The start screen: the greeting by time, the streak card, and the reminder as one quiet line.
- [x] **Step 3:** The session screen:
  - the turn label, from the existing `indicator` states;
  - the mic ring, from the existing mic level;
  - older captions faded (`.line:not(:last-child)`);
  - the button layout.
- [x] **Step 4:** The end screen: minutes, names found, the streak. A row whose number is 0 is left out.
- [x] **Step 5:** `node --check static/app.js`, `node --test tests/js/*.test.mjs`, `pytest`. Expected: all pass.
- [ ] **Step 6: Manual check** on a phone and on the tablet, at the largest text size. Check:
  - nothing is cut off or scrolls sideways;
  - the emergency button never covers a control;
  - the turn label follows her voice.

### Task 6: The caregiver page's face-lift

**Files:** `static/caregiver.html`, `static/caregiver.css`, `static/caregiver.js`.

**Interfaces:** reads the existing `/overview`, `/sessions` and `/progress`. No API change.

- [x] **Step 1:** The tokens and the fonts from Task 5, and a dark palette under `prefers-color-scheme: dark`.
- [x] **Step 2:** The four summary tiles, from data the page already loads.
- [x] **Step 3:** The four tabs. Each existing `<details>` section moves under its tab, keeping its `id`, so every existing handler and the `sec-*` toggles keep working. Add the `localStorage` memory and the `#tab` links.
- [x] **Step 4:** Conversation cards. The row's buttons move into a "⋯" menu, the same buttons with the same handlers.
- [x] **Step 5:** `node --check static/caregiver.js`, then `pytest`. Expected: all pass.
- [ ] **Step 6: Manual check on a test account:**
  - every action still works from its new place (transcript, prompt, recording, process, leave out / put back, restore, rebuild, export);
  - the page works in dark mode and on a phone.

## Done when
- [x] The family can edit and add memory items, and edit and remove summaries, from the caregiver page. Each edit is restorable and shows in the next session's prompt.
- [x] A vocabulary word removed on the page is gone from the profile she reads and isn't added back by the memory agent. It can be put back from the page.
- [x] His app has the new look and shows his streak. After a session it shows only what went well.
- [x] The caregiver page has the summary tiles, the four tabs and the conversation cards, and every existing action still works.
- [x] `pytest` and the JS tests pass.

## Commit (when Tomer asks)
`Sub-plan 21: editing the memory, and a face-lift`
