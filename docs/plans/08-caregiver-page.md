# Sub-plan 08: Caregiver page

Part of the [master design](00-master-design.md). Depends on [07](07-web-search-subagent.md). Builds on the admin screen from [4.5](04.5-memory-reset.md).

## Goal
Tomer (and the family) can **see what the tutor knows and plans, and correct it**, without opening the Firestore console:
- how sessions went
- what she remembers
- what the next lesson will be
- what the research found
- what the games app could improve

## What changed since the master design (checked 2026-10-05)
- **The patient profile is a private markdown file in the bucket**, not Firestore fields (`speech_profile`, `therapist_goals`…). Editing a medical summary in a web form is risky, so the file stays edited by hand. Instead, the page gets a per-account **"notes for the planner"** box (therapist goals, things to focus on or avoid). It's saved in Firestore and read by the plan builder.
- **The Simon repo is public** (`TomerShimshi/simon`), so any issue on it is public. Instead of a GitHub token, the "Create GitHub issue" button **opens GitHub's new-issue form, already filled in**, in a new tab. Tomer reads it, edits it if needed, and submits it himself. This means no token, no secret, and nothing posted automatically. The issue text contains only game data (game, kind, title, rationale, numeric evidence): no names, no transcript.
- **Already stored and ready to show:**
  - session summaries, mood, highlights, difficulties and check-in results
  - the word bank
  - `memory_history`
  - warning flags
  - games-app recommendations
  - research notes
  - the next plan with its research decision
- **Speech recognition makes mistakes**, so a wrong "fact" can enter the memory (e.g. a misheard name). The page must be able to **remove a single memory item**, not only reset everything.

## Out of scope (→ 09)
- Graphs (check-in trends, mood over time), audio recordings, "export for therapist".
- Per-account voice settings (silence length, tap-to-talk).
- Editing the bucket profile file.

## Design
- **A separate page, `/caregiver`** (`static/caregiver.html` + `caregiver.js`), in Hebrew, right-to-left, readable on a phone.
  - The "ניהול" ("admin") link on the start screen opens it.
  - It reuses `auth.js` for Google sign-in.
  - The reset tool from 4.5 moves here.
- **Who:** `CAREGIVER_EMAILS` only. The server enforces it with `require_caregiver` (403 for Dad's account, 401 without sign-in). Only allowlisted accounts can be viewed (404 otherwise).
- **One page for every account (every "patient")**, including Tomer's own test account. The account picker at the top lists all allowlisted accounts, and every section below shows the chosen account's own data. Nothing is mixed between accounts. The page opens on the signed-in caregiver's own account when it's allowlisted, so Tomer can validate the page against the sessions he did himself before relying on it for Dad.
- **Always visible:**
  - **Open warning flags**, each with its evidence and a "טופל" ("handled") button.
  - **Emergency information:** BE-FAST signs; call Magen David Adom on 101.
  - **Tips for the family:** wait for him; don't finish his sentences; ask yes/no questions; write key words down.
- **Sections**, each collapsible, read first, with a few actions:
  1. **Sessions:** the newest first, each with its date, length, mood, summary, highlights / difficulties and check-in results (✓ on his own / ~ with a hint / ✗). Opens the full transcript: both versions of each of his lines (Gemini's and the browser's), plus her lines.
  2. **Next lesson:** the plan exactly as the tutor will get it (`render_class_plan`), plus the research decision (question / status / reason) and when and after which session it was built. Button: **"לבנות מחדש"** ("rebuild now") runs the plan builder now (e.g. after editing the notes).
  3. **Notes for the planner:** a free-text box (up to ~1,500 characters) saved per account. The builder gets it as "NOTES FROM THE FAMILY / THERAPIST" and the prompt says to follow it. It's **never** sent to research (the research question is still generic and checked).
  4. **Memory:**
     - the `memory_prompt` and each section's items, with an ✕ on each item to **remove** it. The current memory is backed up first, the same way as a reset.
     - **History:** earlier versions (one per session), each with a **"שחזור"** ("restore") button. Restore makes that version current; the current version is backed up first and also saved into the history, so a restore can itself be undone.
  5. **Word bank:** a table of word, attempts, ✓ / ~ / ✗ counts, last result and next due date, sorted by next due date.
  6. **Research notes:** each question with its summary and techniques, and their sources as links (trusted / general web).
  7. **Games-app suggestions:** each with its game, kind, title, rationale, evidence and how often it was suggested. Status buttons: accepted / rejected / done. The **"פתיחת issue ב-GitHub"** ("open a GitHub issue") button opens the prefilled form, and the body ends with a short "for Claude Code" task description.
  8. **Reset** (from 4.5): forget memory / delete everything, with the typed confirmation.
- **Cost:** only Firestore reads (sessions list limited to the last 30; a transcript loads only when opened) and, for "rebuild", one plan-builder run. Well within the free tier.

## API (`app/caregiver_api.py`, a FastAPI router; all routes need `require_caregiver`; `{email}` must be allowlisted)
| Route | Purpose |
|---|---|
| `GET /api/caregiver/accounts` | allowlisted accounts + overview (replaces `/api/admin/accounts`) |
| `GET /api/caregiver/{email}/overview` | open flags, memory, next plan (rendered) + research info, planner notes, research notes, games suggestions |
| `GET /api/caregiver/{email}/sessions` | the last 30 sessions (summary fields, no turns) |
| `GET /api/caregiver/{email}/sessions/{sid}` | one session + its turns |
| `GET /api/caregiver/{email}/memory/history` | earlier memory versions |
| `POST /api/caregiver/{email}/memory/remove-item` | `{section, item}`: remove one memory item (backup first) |
| `POST /api/caregiver/{email}/memory/restore` | `{version}`: restore a history version (backup first) |
| `PUT /api/caregiver/{email}/notes` | save the planner notes |
| `POST /api/caregiver/{email}/plan/rebuild` | rebuild the next plan now |
| `POST /api/caregiver/{email}/flags/{id}/resolve` | mark a flag handled |
| `POST /api/caregiver/{email}/recommendations/{id}` | `{status}`: accepted / rejected / done |
| `POST /api/caregiver/{email}/reset` | the 4.5 reset (replaces `/api/admin/reset`) |

## Files
| File | Purpose |
|---|---|
| `app/caregiver_api.py` | The routes above. |
| `app/store.py` | `list_sessions`, `list_flags` / `resolve_flag`, `list_recommendations` / `set_recommendation_status`, `memory_history` / `restore_memory`, `get_notes` / `save_notes`, `list_technique_notes` (+ in-memory versions). |
| `app/agent/next_class.py`, `prompts/next_class.yaml` | Planner notes in the builder's context. |
| `static/caregiver.html`, `static/caregiver.js`, `static/style.css` | The page. |
| `static/index.html`, `static/app.js` | The "ניהול" link opens `/caregiver`; the old admin screen is removed. |
| `tests/test_caregiver.py` | Caregiver-only access (403 / 401 / 404 for a non-allowlisted account); each action; memory item removal and restore (with backup, other accounts untouched); notes reach the builder but never research; the GitHub link text has no personal data. |

## Tasks
1. [x] **Read-only page:** the page shell, account picker, flags, emergency info and tips, sessions + transcripts, next lesson, memory, word bank, research notes, games suggestions; the reset moves in. Tests. **Deploy → Tomer looks.**
2. [x] **Actions:** resolve flags, suggestion statuses + GitHub link, remove a memory item, restore a version, planner notes + rebuild. Tests. **Deploy → Tomer tries them.**
3. [x] Commit and push.

## Notes from building it
- **Rebuild now** was moved forward from task 2 at Tomer's request. It lets a prompt or code change be tried on the next lesson right away, without waiting for a session to end. It replaces the saved plan only when the build succeeds.
- **Checking the notes were used.**
  - Each plan records which saved notes it saw (`notes_used_at`, set by the code). The page shows "built with the notes saved at …", or a warning to rebuild when the notes changed after the plan was built.
  - The builder also writes one sentence on how it applied them (`notes_applied`). It's shown only on the caregiver page, never to the tutor, and it's the model's own account.
- **Plan language.**
  - The plan was half Hebrew, half English and hard to read. Each `ClassPlan` field now has a fixed language in its schema description: **English** for every instruction or description, **Hebrew** only for the exact words the tutor says (recall, warm-up, lead-ins, questions, hints) and the targets.
  - The renderer puts every Hebrew sentence on its own indented line. A mostly-English line may keep a short quoted Hebrew phrase.
  - Check-ins read lead-in → ask → answer (the order she says them); practice reads ask → hints → answer.
  - The page sets the text direction per line (`unicode-bidi: plaintext`).
  - The tutor gets the same text (builder prompt v0.8).
- **Removing a memory item** rewrites the tutor's summary with one small model call (`remove_fact` in `memory_update.yaml`). It refuses a reply that looks broken, and nothing changes if it fails. Every edit or restore first saves the replaced version into `memory_history` (ids `edit-…` / `restore-…`, with microseconds so two edits never collide) and backs it up to the bucket.
- **The progress dots** appear where the click happened. The first version put the status at the bottom of the memory section, out of view.
- **The flags area** always shows a line ("no open flags") so it's visibly there.
- **Shared FastAPI dependencies** moved to `app/deps.py`, because importing the caregiver router from `main.py` was circular. Tests still override the same function objects.
- **The GitHub link** is built on the server. His Latin-script names, the account name and the games profile name are replaced with `[name]`. Names written in Hebrew letters aren't caught, so Tomer reviews the form before submitting.

## Manual steps for Tomer
- None needed (no new secrets). Try the page on both a computer and a phone.

## Done when
- [x] `pytest` passes.
- [x] Dad's account can't open the page or its API (403); signed-out gets 401.
- [x] Tomer can read a session's transcript and see the next lesson as the tutor gets it, for his own account (checked against sessions he remembers) and for Dad's.
- [x] Switching accounts shows only that account's data (tests).
- [x] Removing a wrong memory item, or restoring an earlier version, is reflected in the next session (and a backup exists).
- [x] Planner notes change the next plan after "rebuild".
- [x] The GitHub button opens a prefilled issue form on the Simon repo with no personal data.

## Commit
`Sub-plan 08: caregiver page with sessions, memory editing and restore, planner notes`
