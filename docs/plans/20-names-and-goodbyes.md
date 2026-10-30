# Sub-plan 20: Hearing the names right, and a clean goodbye

Part of the [master design](00-master-design.md). After [19](19-observability.md), before [20.5](20.5-leaving-a-conversation-out.md). (Was 13.5, then 14, then 15, then 16, then 17, then 18, then 19, until 2026-10-24.) Requested by Tomer (2026-10-11). **Reviewed against the code 29.10** (after 13-19 were built): the noise filter is already off during the names game (built in 13); the recheck moved out of the memory update (the recording isn't joined yet when it runs); leaving a conversation out (was C) is now [20.5](20.5-leaving-a-conversation-out.md); the tasks below are in build order. **Built and deployed 29.10 (tasks 1-6).** After the first live test (29.10) the noise filter is back ON during the names game: off, noise in the room interrupted her question and the game stalled. And a turn of hers that was cut off no longer counts for the question gate (13.5): her repeat of the cut question is played (it was held back, and he never heard the question). **30.10: no `custom_vocabulary` for the transcription.** Replaying a session's audio to Gemini Live with and without it: with the names list, an unclear answer came out as the list's first name (3 of 3) and a long unclear line as the whole list word for word (2 of 3); without it, the line was right (3 of 3). It had been sent since 02 (the profile's names since 15.5, today's names since 12). The page's own matching (Design A) now catches the names. The manual and live checks (tasks 2, 3, 6) and the recheck's dry run (task 5) are still to do. Changes from the sketch:
- **Result values:** names-game results are `uncued`/`cued`/`failed` (the memory agent's values), so the recheck writes those, not `self_found`/`not_found`.
- **Corrections both ways:** the recheck corrects a lenient "yes" the recording contradicts too.
- **The `misheard` flag** uses the caregiver page's fields (`tutor_said`, `he_said`, `evidence`) plus `names`.
- **Joining a recording never needs Gemini:** without a key, only the recheck waits.
- **`נדבר` isn't a goodbye in "נדבר על…".** Her goodbye mark clears when a whole turn of hers goes on without one.
- **Console checks:** the page exposes `window.tutorDebug` with `?debug=1`.
- **The Node 24 command** is `node --test "tests/js/*.test.mjs"`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the names game is scored from what he really said, a goodbye never loops, transcription markers never show, and the plan builder's prompt carries no repo notes.

**Architecture:** page code (`static/app.js`) for the goodbye and the markers, and for catching his names-game answers live (a primed caption and `soundsLike`, in its own tested module `static/sounds_like.js`); a new job (`app/names_recheck.py`) that listens to the recording after both the memory update and the recording's join are done.

**Tech Stack:** FastAPI, Firestore (and the in-memory store for tests), google-genai (an audio part for the recheck), vanilla JS pages, pytest, `node --test` (Node 24) for `static/sounds_like.js`.

**Spec:** this file (Why, Goal, Design below).

## Global Constraints
- The repo is public: no names, words or transcripts of his in code, tests or this file. Test data is invented.
- Real eval answers go in `*.local.json` only.
- Gemini credit: the recheck is **one** model call per session, only when the session had a names game **and** a recording; never retried more than once (the sweep).
- Every new caregiver-page text is Hebrew; every prompt text is English (as today).
- A model or storage failure in the recheck never breaks `/end`, `/audio/finish` or the sweep (logged, like the memory update).
- The live catching adds no model calls: its notes are a few words of text in the live session.
- `static/sounds_like.js` stays a dependency-free ES module (the page imports it; Node tests it as is, without a build step).
- Changing any text she reads bumps `prompt_version` in `prompts/tutor.yaml` (3.6 -> 3.7).
- Production deploys only on Tomer's explicit "deploy"; commit and push only when he asks (so the commit step is at the end, not per task).

## Review Focus
1. **An unclear recording** (low confidence, he mumbled, the recording cut): the live result stays. Only a confident disagreement changes it. -> test in Task 5.
2. **The recheck triggered twice** (`/audio/finish`, `/end` and the sweep race): one model call, one `misheard` flag. -> claim test in Task 5.
3. **Goodbye words inside other words** ("בייגלה" matches `/ביי/` today): the page matches whole words only. -> manual check in Task 3 (the page has no JS test harness).
4. **A false match on a short name or a common word** (a 3-letter name inside "אני לא יודע", a name that differs from a common word by one sound): no match, so no note and no fixed caption. -> `node --test` cases in Task 6.
5. **The priming isn't supported on his phone** (no `phrases`, no Hebrew on-device): the caption works exactly as today, and the page log says so once. -> manual check in Task 6, on his device.

Also tested, though less likely: the recording ends before the game's last answer (Task 5), and a goodbye with a Hebrew prefix, "ולהתראות" (Task 3).

---

## Why
- **A names-game answer misheard live (a patient session, 11.10).** He said a name correctly. Gemini, listening to the session's recording afterwards, heard it clearly (95%+ sure). But the live model answered as if he hadn't found it, and the live transcript wrote something else. So the game recorded "failed" for a name he found.
  - The suspected contributor, the noise filter cutting a quick answer, was handled in 13 by turning the filter off while the names-game step runs; that was reverted 29.10 (noise interrupted her questions), so the filter is on in the game too.
- **A goodbye loop (Tomer's test session, 11.10).**
  - At 6.6 minutes he said "להתראות". Gemini's transcript wrote **"מה הליטרות?"**; the browser caption had it right.
  - The page decides from **Gemini's transcript only** once it arrives (`addUserFinal` sets `s.lastUserText = u.gem`), so it refused her `end_session` ("he has not said goodbye yet").
  - She said goodbye again, he said goodbye again, and so on, until he pressed the end button. Still true in the code on 29.10.
- **Markers in the transcript (15.10):** Gemini's transcription of her voice wrote `<no speech detected>` at the end of her line. It shows in the captions, the saved transcript and the caregiver page, and the memory agent reads it. Still true on 29.10.
- **Repo notes in the plan builder's prompt (seen in a 19 trace, 28.10):** "see docs/plans/00-master-design.md", and "(12)" in two schema descriptions.
## Goal
1. **The names game is scored right**, even when the live model mishears him.
2. **No goodbye loops.** When he says goodbye, she hangs up after her own goodbye, even if one transcript mishears him.
3. **No `<...>` markers** anywhere he or the family or an agent reads.
4. **The plan builder's prompt has only what it can use**: no repo paths, no plan numbers.

## Design

### 0. Steps mode by default: moved to [13.5](13.5-tool-based-planner.md) (2026-10-12)

### A. Hearing the names game right
- **Live (prompt): lenient, then ask once.** `NamesGameStep.RULES` (`app/steps.py`) says today "no second try". New rules, in order:
  - his speech may be unclear after a stroke: an answer that **sounds like** the name (a sound or two off, slurred, cut at the start or the end) **counts as right** ("נכון!");
  - an answer she **can't make out** gets one "סליחה, לא שמעתי טוב, תגיד שוב?" before she says the name (a right second try counts as found on his own);
  - an answer that is **clearly a different word** gets the name, warmly, with no second try.

  Being told "no" when he was right is the mistake that discourages him; a lenient "yes" is corrected in the score by the recheck.
- **Live (code):** the noise filter was off during the names-game step (13); back on since 29.10 (noise cut her questions).
- **Live (code, added 29.10): the page catches his answer, using the names it expects.** The page knows the game's names (new: the agenda's `game_names`), and it has two transcripts of each of his lines.
  - **The browser caption is primed with the names.** Chrome has an experimental `SpeechRecognition.phrases` (`SpeechRecognitionPhrase(phrase, boost)`), which biases recognition toward expected phrases. It may need on-device recognition (`processLocally`), and Hebrew support there isn't confirmed.
    - When the names-game step starts, the page restarts its recognizer with the names at boost 5. MDN warns that 9-10 makes it hear the name in other words.
    - It's feature-detected: an error (no support, no Hebrew on-device) is logged, and the page goes on with the plain recognizer.
    - After the step, the page goes back to the plain recognizer.
  - **A quick answer isn't dropped by the caption.** After her voice stops, the caption ignores 800 ms (her echo). During the game this is 300 ms: echo cancellation is on, and she never says a name before his answer (no hints).
  - **Matching, with the names as prior knowledge:** `soundsLike(heard, target)` (`static/sounds_like.js`, tested with `node --test`). It compares a consonant skeleton, so it tolerates the transcripts' typical Hebrew errors:
    - vowel marks, punctuation and the vowel letters ו/י (except a word's first letter) are dropped;
    - final forms become regular letters;
    - letters that sound alike count as one: ט/ת, כ/ק/ח, ס/ש/שׂ, א/ע/ה, ב/ו at a word's start.

    It allows edit distance 0 for skeletons up to 3 letters, 1 for 4-6, and 2 for 7 or more, against any run of 1-3 of his words. Every line of his during the game is checked, interim and final, from both transcripts, against the game's names not yet found.
  - **A match fixes the caption and the record:** the caption shows the name; the saved turn gets `matched_target`; the memory agent's transcript shows "(the page matched the names-game name: …)".
  - **A match tells her, as early as possible:**
    - *During his line* (the browser caption's interim results arrive while he is still talking), the page sends a silent note at once: `[His answer matched the name "…" -- he found it.]` It's in her context before she replies; whether it shapes the reply is tested in a session.
    - *If her reply still treated it as wrong* (`herReplyRejected` in `static/sounds_like.js`: no praise word, and she says the name herself or asks him to say it again; moving on counts as accepting -- 29.10, a plain list of praise words missed "מדויק!" and the correction made her repeat the question), the page sends, once her turn is complete, a note she answers: `[He actually said "…", the right name. Tell him warmly, in one short sentence, that he got it right, then go on with the game -- don't ask a question you already asked.]` He hears "אה, סליחה -- אמרת נכון!", once per name at most.
  - **Recorded:** `names_live` on the session, one entry per name: `{target, gem, live, matched_by, early_note, she_accepted, corrected}`. The recheck then shows how often the page's match agreed with the recording.
- **After the session (code, the main fix): a recheck job**, `app/names_recheck.py`. It can't be part of the memory update: `/end` runs the memory update while the page's `/audio/finish` joins the recording in parallel, so the recording is usually not there yet.
  - **Runs when both are done** (memory `done`, `audio_uri` set, the plan had a names game, `probe_results` has names-game items), from whichever finishes second: the end of `/audio/finish`, the end of `/end`, and the hourly sweep (for the rest). A claim (`names_recheck: processing`) makes it run once.
  - **One model call:** the recording (an audio part) plus the game's questions and target names; structured output: for each name, what he said (Hebrew), whether he found it, and a confidence.
  - **Applies only confident disagreements:** the session's `probe_results` entry gets the recording's result and `rechecked: true` (the live one kept as `live_result`); the check-in set's result for that session is corrected; one `tutor_issue` flag, `issue: misheard`, per session, listing the names.
  - **Statuses** on the session (`names_recheck`): `processing`, `agreed`, `changed`, `failed`, `skipped`. `skipped` covers no game, no recording, or recording off.
  - The next plan is not rebuilt: the correction reaches the next build.

### B. The goodbye (page code)
- **The main rule: her goodbye, then his reply (added 29.10).** Two people don't check each other's words at the end of a call. Once she has said goodbye, a **short** reply from him (up to 4 words in either transcript) is his goodbye, whatever the transcripts made of it. So `end_session` is accepted. A longer reply ("רגע, עוד דבר…") means he's still talking, and the old refusal applies. The goodbye words below matter only when she calls `end_session` before saying goodbye herself, or when his goodbye comes first.
  - **Her goodbye:** the moment her line first matches `GOODBYE_RE` (`s.herByeAt`, set in `addTutorText`), or the close step was given (`s.closing`).
  - **Not chosen:** making Gemini's speech detection more eager during the names game. In a really noisy room that ruins sessions; the recheck (A) covers the score instead.
- **Both transcripts count.** "Did he say goodbye?" checks Gemini's transcript **and** the browser caption of his last line, and also of the line before it (a goodbye split across two lines). `s.lastUserText` stays for the logs; a new `heSaidGoodbye()` does the check.
- **Whole words only.** `GOODBYE_RE` matches inside other words today (`ביי` in "בייגלה"). The new pattern matches whole words, allowing a one-letter prefix (ו/ש/ה/ב/ל/כ/מ: "ולהתראות").
- **Wider words:** add "נדבר", "יאללה" + goodbye, and "תודה רבה" + goodbye (the latter two are already covered by `ביי`/`להתראות`); "שיהיה לך…" counts **only after her goodbye** (`s.closing`, or her last line matched a goodbye).
- **Never a loop.** After two refusals, the next `end_session` is accepted. The silence nudge still ends it, as today.
- **Counted:** `goodbye_refusals` (int) goes in `/end`'s body, is saved on the session, and shows on the caregiver page's session row when > 0.

### B2. Transcription markers
- **Page:** text in angle brackets (`<...>`) is dropped from both transcripts (hers in `addTutorText`, his in `addUserFinal` / `setUserLive`) before it is shown, saved or matched.
- **Server:** `strip_markers(text)` in `app/transcripts.py`, used by `format_transcript` (the memory agent's input), for sessions saved before the fix.

### C. Moved to [20.5](20.5-leaving-a-conversation-out.md) (2026-10-29)

### D. The plan builder's prompt without our repo notes
- `techniques_text()` (`app/agent/next_class.py`) pastes `prompts/therapy_techniques.yaml` word for word, including its `#` comments ("see docs/plans/00-master-design.md") and its `prompt_version` line. **Fix:** drop the full-line `#` comments and the `prompt_version` line from the text; the file keeps them.
- Gemini's SDK sends a Pydantic class's docstring as the schema's `description`: `CheckInItem` and `CheckInProposal` (`app/schemas.py`) say "(12)". **Fix:** drop the plan numbers from those two docstrings. (Checked 28.10: every other prompt file is parsed as YAML, and the other structured outputs and tool descriptions are clean.)

## Files
| File | Purpose |
|---|---|
| `app/agent/next_class.py` | `techniques_text()` without comments and version (D); the readers in C's table use the filtered `list_sessions`. |
| `app/schemas.py` | No plan numbers in `CheckInItem`/`CheckInProposal` (D); `NamesHeard`/`NameHeard` (A). |
| `app/transcripts.py` | `strip_markers` (B2); `goodbye_refusals` on `EndRequest` (B). |
| `app/agent/memory_update.py` | `format_transcript` strips markers (B2). |
| `static/sounds_like.js` (new), `tests/js/sounds_like.test.mjs` (new) | `soundsLike(heard, target)` and its tests (A). |
| `app/main.py`, `app/class_plan.py` | The agenda's `game_names` (A). |
| `app/transcripts.py` | `TurnIn.matched_target`, `EndRequest.names_live` (A). |
| `static/app.js` | The primed caption, the 300 ms echo window, the match, the notes and `names_live` during the names game (A); markers dropped (B2); `repliedToHerBye()`, `heSaidGoodbye()`, whole-word `GOODBYE_RE`, at most two refusals, `goodbye_refusals` (B). |
| `app/main.py` | `goodbye_refusals` saved (B); the recheck after `/end` and `/audio/finish` and in the sweep (A). |
| `app/steps.py`, `prompts/tutor.yaml` | Ask once more on an unclear names-game answer; `prompt_version` 3.7 (A). |
| `app/names_recheck.py` (new) | The recheck job (A). |
| `app/check_in_set.py` | `correct_result` (A). |
| `app/agent/memory_tools.py` | `misheard` in `TUTOR_ISSUE_KINDS` (A). |
| `app/store.py` | `claim_names_recheck` (A). |
| `app/caregiver_api.py` | `goodbye_refusals` and `names_recheck` in the session row (A, B). |
| `static/caregiver.js` | The refusals and the `misheard` issue's label (A, B). |
| `tests/` | Per task below. |

## Tasks

### Task 1: The plan builder's prompt without repo notes (D)

**Files:** Modify `app/agent/next_class.py:75-76`, `app/schemas.py:170-181`. Test: `tests/test_prompts.py`.

**Interfaces:** Produces `techniques_text() -> str` (same name, cleaned output).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_techniques_text_has_no_repo_notes():
    text = techniques_text()
    assert "docs/" not in text and "prompt_version" not in text
    assert not any(line.lstrip().startswith("#") for line in text.splitlines())
    assert len(text) > 500  # the techniques themselves are still there

def test_schemas_sent_to_gemini_have_no_plan_numbers():
    for cls in (CheckInItem, CheckInProposal):
        assert not re.search(r"\(\d+(\.\d+)?\)", json.dumps(cls.model_json_schema()))
```

- [ ] **Step 2:** `pytest tests/test_prompts.py -k "repo_notes or plan_numbers" -v`. Expected: both FAIL.
- [ ] **Step 3:** In `techniques_text()`, drop the full-line `#` comments and the `prompt_version:` line (line-based, keeping inline text as is). Remove the "(12)" from the two docstrings.
- [ ] **Step 4:** Run the same command. Expected: PASS. Then run `pytest`. Expected: all pass.

### Task 2: No transcription markers (B2)

**Files:** Modify `app/transcripts.py`, `app/agent/memory_update.py:50-63`, `static/app.js` (`addTutorText`, `addUserFinal`, `setUserLive`). Test: `tests/test_memory.py`.

**Interfaces:** Produces `strip_markers(text: str) -> str` in `app/transcripts.py`: removes every `<...>` (no nested `<`/`>`) and collapses the spaces left behind.

- [ ] **Step 1: Write the failing tests**

```python
def test_markers_are_dropped():
    assert strip_markers("נהדר, ספר לי עוד <no speech detected>") == "נהדר, ספר לי עוד"
    assert strip_markers("<noise> כן ") == "כן"
    assert strip_markers("כן") == "כן"

def test_the_memory_agent_never_reads_markers():
    turns = [{"speaker": "tutor", "text": "שלום <no speech detected>", "t_start_s": 0},
             {"speaker": "patient", "text": "<noise>", "live_text": "שלום", "t_start_s": 2}]
    out = format_transcript(turns)
    assert "<" not in out and "שלום" in out
```

  The pattern is `<[^<>\n]{1,60}>` (a closed pair; speech never has one).
- [ ] **Step 2:** `pytest tests/test_memory.py -k markers -v`. Expected: FAIL (`strip_markers` not defined).
- [ ] **Step 3:** Implement `strip_markers` and apply it to both texts in `format_transcript`. In the page, apply the same regex to each incoming text piece before it's appended. A piece split across two messages ("<no spe" + "ech detected>") is caught by stripping the whole line's text after each append.
- [ ] **Step 4:** Run the same command, then `pytest`. Expected: PASS.
- [ ] **Step 5: Manual check (page):** in a short test session, the page log and the caregiver page's transcript show no `<...>`.

### Task 3: A clean goodbye (B)

**Files:** Modify `static/app.js` (`GOODBYE_RE`, `answerToolCall`'s `end_session` and `next_step` branches, `finishRemote`'s `/end` body), `app/transcripts.py` (`EndRequest`), `app/main.py` (`end_session`), `app/caregiver_api.py` (`SESSION_FIELDS`), `static/caregiver.js` (session row). Test: `tests/test_session_api.py`, `tests/test_caregiver.py`.

**Interfaces:** `EndRequest.goodbye_refusals: int = Field(default=0, ge=0, le=20)`; the session field `goodbye_refusals`; the page's `heSaidGoodbye(): boolean` and `repliedToHerBye(): boolean`.

- [ ] **Step 1: Write the failing tests**

```python
def test_end_saves_goodbye_refusals(client, store, ...):
    # start a session, then POST /end with {"reason": "tutor_goodbye", "goodbye_refusals": 1}
    assert store.get_session(pid, sid)["goodbye_refusals"] == 1

def test_end_without_refusals_saves_nothing_new(...):
    assert "goodbye_refusals" not in store.get_session(pid, sid)

def test_the_session_row_shows_goodbye_refusals(...):
    assert row["goodbye_refusals"] == 1
```

- [ ] **Step 2:** `pytest tests/test_session_api.py tests/test_caregiver.py -k goodbye -v`. Expected: FAIL.
- [ ] **Step 3: Server.** Add the field. `/end` saves it when > 0, in the same `update_session` as `steps_done`. Add it to `SESSION_FIELDS`.
- [ ] **Step 4: Page.**
  - `GOODBYE_RE`:
    - wrap the alternatives in `(?<![א-ת])[ושהבלכמ]?(?:…)(?![א-ת])`;
    - add `נדבר`;
    - add `SOON_BYE_RE = /שיהיה לך/`, which counts only when `s.closing` or her current/last line matched `GOODBYE_RE`.
  - `heSaidGoodbye()` tests the `gem` and `live` text of his last two user lines (keep the previous line object as `s.prevUserLine` in `ensureUserLine`).
  - Use it everywhere `GOODBYE_RE.test(s.lastUserText…)` is used: `next_step` and `end_session` in `answerToolCall`, and the silence check.
  - **Her goodbye, then his reply:** in `addTutorText`, set `s.herByeAt = performance.now()` the first time her current line matches `GOODBYE_RE` (and on `s.closing`). Add `repliedToHerBye()`: true when `s.herByeAt` is set, his last line started after it, and that line has 1-4 words in `gem` or `live`.
  - `end_session` is accepted if `heSaidGoodbye() || repliedToHerBye() || s.nudged || s.goodbyeRefusals >= 2`. On refusal, `s.goodbyeRefusals += 1`, and the log says which check failed.
  - Each user line keeps its start time (`u.startedAt` in `ensureUserLine`), so "after her goodbye" compares line starts, not the transcript's arrival.
  - Send `goodbye_refusals: s.goodbyeRefusals || 0` in the `/end` body.
- [ ] **Step 5: Caregiver page.** The row shows "⚠ סירוב פרידה ×N" when N > 0.
- [ ] **Step 6:** Run `pytest`. Expected: all pass.
- [ ] **Step 7: Manual check (page, in the browser console on a test session):**
  - `heSaidGoodbye()` with `gem: "מה הליטרות?"` and `live: "להתראות"` is true;
  - `GOODBYE_RE.test("בייגלה")` is false;
  - `GOODBYE_RE.test("יאללה ביי")` is true;
  - `GOODBYE_RE.test("ולהתראות")` is true;
  - in a test session, say goodbye with a nonsense word ("בלבלה") after her goodbye: she hangs up after her goodbye (page log: "end_session accepted (he replied to her goodbye)");
  - after her goodbye, a long reply ("רגע, אני רוצה לספר לך עוד משהו על היום") keeps the conversation going;
  - with the transcripts forced wrong (console: `s.prevUserLine = null` and override `heSaidGoodbye = () => false`), she never refuses more than twice.

### Task 4: Lenient on a near answer, asks once on an unclear one (A, prompt)

**Files:** Modify `app/steps.py:100-104` (`NamesGameStep.RULES`), `prompts/tutor.yaml` (`prompt_version: "3.7"`). Test: `tests/test_names_game.py`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_names_game_asks_once_more_when_his_answer_is_unclear():
    rules = NamesGameStep.RULES
    assert "סליחה, לא שמעתי טוב, תגיד שוב?" in rules
    assert "no second try" not in rules.lower()

def test_the_names_game_counts_an_answer_that_sounds_like_the_name():
    assert "sounds like" in NamesGameStep.RULES.lower()
```

- [ ] **Step 2:** `pytest tests/test_names_game.py -k unclear -v`. Expected: FAIL.
- [ ] **Step 3: Edit `NamesGameStep.RULES`.**
  - Replace "no second try" with the three rules in Design A, in that order: sounds like the name -> "נכון!"; can't make it out -> ask once "סליחה, לא שמעתי טוב, תגיד שוב?" (a right second try counts as found on his own); clearly a different word -> the name, warmly, and go on. One sentence on why: his speech may be unclear after a stroke.
  - Add: a note saying his answer matched the name means he found it.
  - Bump `prompt_version` to 3.7.
- [ ] **Step 4:** Run `pytest`. Expected: all pass. Fix any test that pins the old rules text or 3.6.

### Task 5: The recheck from the recording (A, the main fix)

**Files:**
- Create `app/names_recheck.py`.
- Modify:
  - `app/schemas.py`;
  - `app/store.py` (both stores and the protocol);
  - `app/check_in_set.py`;
  - `app/agent/memory_tools.py:70`;
  - `app/main.py` (`/end`, `/audio/finish`, `/internal/memory/sweep`);
  - `static/caregiver.js` (the `misheard` issue's Hebrew label).
- Create the test `tests/test_names_recheck.py`.

**Interfaces:**
- Produces in `app/schemas.py`:
  - `NameHeard(target: str, heard: str, found: bool, confident: bool)`;
  - `NamesHeard(names: list[NameHeard])`.

  Their docstrings have no plan numbers (see Task 1).
- Produces in `app/store.py`: `claim_names_recheck(pid, sid) -> bool`. It sets `names_recheck: processing` only if the field is unset, or `processing` for longer than `STALE_PROCESSING`. It is transactional in Firestore, like `claim_for_memory`.
- Produces in `app/check_in_set.py`: `correct_result(current: dict, sid: str, target: str, result: str) -> bool`.
- Produces in `app/names_recheck.py`:
  ```python
  def recheck_names_game(store, client, audio, settings, pid: str, sid: str, *, generate_fn=generate) -> str:
      """Returns the session's names_recheck status: agreed | changed | skipped | failed | not_ready | not_claimed."""
  ```
  - `not_ready` means the memory isn't done, or there's no `audio_uri` yet; it is not saved.
  - `skipped` means no names-game items in `probe_results`.
  - It is wrapped in `telemetry.job("names_recheck")` and never raises.
- Consumes `audio.load(uri) -> bytes`, `session["audio_type"]` and `run_memory_update`'s statuses.

- [ ] **Step 1: Write the failing tests** (FakeClient returns `NamesHeard` as parsed; the in-memory audio store holds invented bytes):

```python
def test_a_confident_disagreement_corrects_the_result_and_flags_misheard():
    # probe_results: {"word": "שולחן", "result": "not_found", "kind": "untreated"}; recording says found, confident
    assert recheck_names_game(...) == "changed"
    r = store.get_session(pid, sid)["probe_results"][0]
    assert (r["result"], r["live_result"], r["rechecked"]) == ("self_found", "not_found", True)
    assert store.get_check_in_set(pid)["items"][0]["results"][-1]["result"] == "self_found"
    flags = [f for f in store.list_flags(pid) if f.get("issue") == "misheard"]
    assert len(flags) == 1 and "שולחן" in flags[0]["note"]

def test_an_unconfident_disagreement_keeps_the_live_result():  # Review Focus 1
    assert recheck_names_game(...) == "agreed"
    assert store.get_session(pid, sid)["probe_results"][0]["result"] == "not_found"

def test_a_name_with_no_answer_in_the_recording_keeps_its_live_result():  # Review Focus 4
    # the model returns only 2 of 3 names
    assert third_result_unchanged

def test_no_recording_or_no_game_makes_no_model_call():
    assert recheck_names_game(...) in ("not_ready", "skipped") and fake.calls == 0

def test_it_runs_once_even_if_called_three_times():  # Review Focus 2
    for _ in range(3): recheck_names_game(...)
    assert fake.calls == 1 and len(misheard_flags) <= 1

def test_a_model_failure_is_recorded_not_raised():
    assert recheck_names_game(... server_error ...) == "failed"

def test_audio_finish_runs_the_recheck_when_the_memory_is_done(client, ...):
    # memory done first, then POST /audio/finish -> names_recheck set
def test_end_runs_the_recheck_when_the_recording_was_joined_first(client, ...):
```

- [ ] **Step 2:** `pytest tests/test_names_recheck.py -v`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement.**
  - **The model call:** the memory update's models (`_models(settings)`), `temperature=0`, `response_schema=NamesHeard`. Contents: one audio part (`types.Part.from_bytes(data=..., mime_type=session["audio_type"])`) and an English instruction listing each question and target from the plan's names-game step.
  - **The instruction asks for:**
    - what he said in reply to each question, in Hebrew;
    - whether it is the target, also counting his right second try after "תגיד שוב";
    - `confident: false` when unsure.
  - **Apply only `confident` disagreements;** save `names_recheck` and `names_recheck_heard` (the list) on the session.
  - **Hook it in three places:**
    - the end of `upload_audio_finish`;
    - after `build_next_plan` in `/end`;
    - in the sweep, for ended sessions from the last 2 days with memory done, an `audio_uri` and no `names_recheck`.
  - Add `misheard` to `TUTOR_ISSUE_KINDS`, and its Hebrew label ("שמעה לא נכון במשחק השמות") on the caregiver page.
- [ ] **Step 4:** Run `pytest tests/test_names_recheck.py -v`, then `pytest`. Expected: PASS.
- [ ] **Step 5: Dry run on a real session (credit: one call).** Run the recheck locally on the 11.10 session against production Firestore (a scratchpad script, read-only: print the result, don't save). Expected: the misheard name comes back `found: true, confident: true`. Put its output in a `*.local.json`, not the repo.

### Task 6: Catching his answer live (A, the page)

**Files:**
- Create `static/sounds_like.js`, `tests/js/sounds_like.test.mjs`.
- Modify:
  - `app/class_plan.py:115` / `app/main.py:253` (the agenda's `game_names`);
  - `app/transcripts.py` (`TurnIn.matched_target: str | None = Field(default=None, max_length=80)`; `EndRequest.names_live: list[NameLive] = Field(default=[], max_length=12)`);
  - `app/main.py` (`/end` saves `names_live`);
  - `app/agent/memory_update.py` (`format_transcript`);
  - `static/app.js`.
- Tests: `tests/test_session_api.py`, `tests/test_memory.py`, `tests/js/sounds_like.test.mjs`.

**Interfaces:**
- Produces in `static/sounds_like.js`:
  - `export function skeleton(text: string): string`: the consonant skeleton (rules in Design A);
  - `export function soundsLike(heard: string, target: string): boolean`.
- Produces in `app/transcripts.py`: `NameLive(target: str, gem: str = "", live: str = "", matched_by: Literal["gemini", "caption", ""] = "", early_note: bool = False, she_accepted: bool | None = None, corrected: bool = False)`, with strings capped at 200.
- The agenda from `/start` gets `game_names: list[str]`: the names-game step's targets, or `[]`.
- Consumes `NamesGameStep.names()` (`app/steps.py:115`).

- [ ] **Step 1: Write the failing tests.** Invented names and words only.

```js
// tests/js/sounds_like.test.mjs -- run: node --test "tests/js/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { soundsLike, skeleton } from "../../static/sounds_like.js";

test("the transcripts' usual Hebrew errors still match", () => {
  assert.ok(soundsLike("טבריה", "תבריה"));          // ט/ת
  assert.ok(soundsLike("זה כרמל", "קרמל"));         // כ/ק, inside a longer line
  assert.ok(soundsLike("הוֹלַנְד", "הולנד"));          // vowel marks
  assert.ok(soundsLike("ירושלים", "ירושלם"));       // a vowel letter missing
  assert.ok(soundsLike("תל אביב", "תל-אביב"));      // two words, punctuation
  assert.ok(soundsLike("רושלים", "ירושלים"));       // the start cut (distance 1, length 5)
});
test("no false matches", () => {
  assert.ok(!soundsLike("אני לא יודע", "דני"));     // a short name: exact skeleton only
  assert.ok(!soundsLike("שולחן", "שלום"));
  assert.ok(!soundsLike("", "חיפה"));
  assert.ok(!soundsLike("בייגלה", "בגדד"));
});
test("final forms are regular letters", () => {
  assert.equal(skeleton("ים"), skeleton("ימ"));
});
```

```python
def test_start_sends_the_names_games_names(client, ...):
    assert body["agenda"]["game_names"] == ["<the invented targets>"]

def test_end_saves_names_live(client, store, ...):
    # POST /end with names_live=[{"target": "חיפה", "live": "חיפה", "matched_by": "caption", "corrected": True}]
    assert store.get_session(pid, sid)["names_live"][0]["corrected"] is True

def test_the_memory_agent_sees_the_pages_match():
    turns = [{"speaker": "patient", "text": "היפה", "matched_target": "חיפה", "t_start_s": 3}]
    assert "the page matched the names-game name: חיפה" in format_transcript(turns)
```

- [ ] **Step 2:** `node --test "tests/js/*.test.mjs"` and `pytest -k "game_names or names_live or pages_match" -v`. Expected: both FAIL.
- [ ] **Step 3: Implement `static/sounds_like.js`.**
  - Edit distance between `skeleton(target)` and the skeleton of every run of 1-3 consecutive words in `heard`.
  - Allowed: 0 for a skeleton of up to 3 letters, 1 for 4-6 letters, 2 for 7 or more.
  - The run's skeleton length must be within ±1 of the target's.
- [ ] **Step 4: Server.** Add `game_names`, the two fields, and the line in `format_transcript`. `upsert_turns` saves `matched_target` like the other turn fields.
- [ ] **Step 5: Page (`static/app.js`).**
  - Import: `const { soundsLike } = await import(`./sounds_like.js${ASSET_QUERY}`);`.
  - **When the names-game step starts:**
    - `s.gameNames = agenda.game_names`;
    - `s.namesLive = {}`;
    - restart the recognizer with `phrases`, if `"phrases" in SR.prototype` (try `processLocally = true` when the property exists). On `onerror` with `phrases-not-supported`, `language-not-supported` or `service-not-allowed`, log `names priming not available (<error>)` once and restart the plain recognizer.
  - **When the step ends:** back to the plain recognizer.
  - **Echo window:** `s.echoUntil` uses 300 ms instead of 800 while `namesGameNow()`.
  - **Matching:**
    - In `setUserLive` and `addUserFinal`, while `namesGameNow()`, test the line's text against each name not yet found.
    - On the first match:
      - set `u.matchedTarget` and show the name in the caption;
      - record `s.namesLive[target]` (`matched_by`, `gem`, `live`);
      - if his line is still open (no reply of hers since it started), `sendSilentNote` the early note and set `early_note: true`.
  - **Correction:**
    - When her turn after a matched line completes, set `she_accepted` from her line (`herReplyRejected`, see Design A).
    - If it's false, send the correction note (`sendNote`), once per name, and set `corrected: true`.
  - **Saving:** `matched_target` goes in the turn's upload; `names_live: Object.values(s.namesLive)` goes in the `/end` body.
- [ ] **Step 6:** `node --test "tests/js/*.test.mjs"` and `pytest`. Expected: all pass.
- [ ] **Step 7: Live check on a test account** (credit: one short session per check).
  - **The early note:** in the names game, answer right but mumbled. The `tutor` trace's context shows the early note before her reply. Note whether she said "נכון!" (`she_accepted`).
  - **The correction:** say a near-miss she rejects. She corrects herself after her turn.
  - **The priming:** on a desktop Chrome and on his phone, the page log says whether priming was available.
  - Put the answers that came out of the session in a `*.local.json` if they're real speech.

## Done when
- [ ] A names-game answer the live model misheard is corrected from the recording, and shown as a `misheard` tutor issue; an unclear recording changes nothing.
- [ ] During the game, an answer that sounds like the name counts as right; when a transcript matches the name, the caption shows it and she is told (early, or corrected right after her reply); the priming is used where the browser has it.
- [ ] After her goodbye, a short reply from him ends the session whatever the transcripts heard; a long one doesn't; never more than two refusals; "בייגלה" is not a goodbye.
- [ ] No `<...>` transcription markers in the captions, the saved transcript or the memory agent's input.
- [ ] The plan builder's prompt has the techniques only: no file comments, no `docs/` references; the names-game set's schema has no plan numbers.
- [ ] `pytest` and `node --test "tests/js/*.test.mjs"` pass.

## Commit (when Tomer asks)
`Sub-plan 20: hearing the names right, and a clean goodbye`
