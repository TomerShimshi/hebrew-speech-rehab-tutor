# Sub-plan 06: Games-app integration (Simon) + game homework + games-app recommendations

Part of the [master design](00-master-design.md). Depends on [05](05-next-class-builder.md) (lesson plans).

## Goal
The tutor and the plan builder **know how Dad is doing in the Simon games app**, and use it:
- The tutor can chat about it naturally ("I saw you played the change-a-word game yesterday…").
- The lesson plan assigns **game homework that fits the practice goal** (e.g. a name-retrieval day → the scrambled-words game in the "places" category). It's shown as a **button on the end screen** that opens that game on his profile.
- The agent writes **recommendations for the games app** (difficulty, bugs, new-game ideas), so the Simon app can evolve with his needs.

It must keep working as Simon gains more games: **no hard-coded list of 5 games**.

## Out of scope
- **Any change to the Simon repo.** Integration is read-only. Ideas for Simon go in as recommendations instead.
- The GitHub-issue button for recommendations, and the UI to review them (08). Until then they're visible in Firestore.
- Changing game difficulty automatically.

## What Simon looks like today (checked 2026-10-03)
- Hosted on Render, with progress in **Upstash Redis**, namespaced **per profile**: keys `<profile>:<game key>`. The profiles are `efraim` (Dad), `tomer` and `other`. A URL with `?user=efraim` opens directly on his profile.
- **5 games** and their keys:
  - Simon `progress_v1`: `best_length`, `rounds_played`, `rounds_correct`, `step_ms`
  - memory `memory_progress_v1`: `pair_count`, `moves`, `mismatches`, `completed`
  - sub-words `subword_progress_v1`: `base_words`, `words_found_count`, `hints_used`
  - scrambled words `scramble_progress_v1`: `category`, `words_shown`, `words_solved_count`, `hints_used`, `revealed_count`
  - change-a-word `change_word_progress_v1`: `pairs_shown`, `changes_solved`, `first_words_solved`, `hints_used`, `revealed_count`

  Plus `engagement_v1` (`visit_dates`). Every game record is `{"sessions": [{id, date, ...fields}]}`.
- Routes: `/simon`, `/memory`, `/subword`, `/scramble`, `/change`, `/progress`.

## Design decisions
- **Reading Simon (read-only).** The Upstash REST API is called with Upstash's **read-only token**: the tutor app physically cannot change Simon's data. The URL and read-only token go in Secret Manager. That makes 3 secrets, within the 6 free.
- **Accounts → Simon profiles.** `SIMON_PROFILES` in `.env` (e.g. `<dad's email>=efraim,<tomer's email>=tomer`). It's passed to Cloud Run like the allowlist. An account without a mapping simply has no games data. **Never mixed**, same principle as the per-account memory.
- **Discovering games generically.**
  - A `SCAN` for `<profile>:*` finds **every** key the profile has.
  - Any key holding `{"sessions": [...]}` is a game. `engagement_v1` is read as visit days.
  - A **catalog** gives known games a Hebrew name, the page route, the skills each one trains, and how to read its fields: `prompts/games_catalog.yaml` in this repo, or, if Simon ever publishes one, an Upstash key `games_catalog_v1` that takes priority.
  - **A new game that isn't in the catalog** is still shown: its key and raw recent sessions go to the model as "unknown game; interpret the fields", and the code computes generic trends.
- **Trends in code, not by the model** (`app/games.py`). Per game:
  - sessions in the last 7 and 30 days, and days since last played
  - each numeric field's recent average vs. earlier (e.g. `hints_used` down, `words_solved_count` up)
  - the last 3 sessions raw

  Plus visit days from `engagement_v1`. The model gets these facts and doesn't have to compute anything.
- **Where games data is used:**
  1. **The plan builder (call #3)** gets a "GAMES" section in its context. The plan gains:
     - `game_homework`: 0–2 items, each `{game_id, why}` (the reason links it to the practice goal, e.g. "places category, names practice")
     - `games_note`: one sentence the tutor can use ("ראיתי ששיחקת אתמול במשחק החלפת המילה", "I saw you played the change-a-word game yesterday")
  2. **The tutor prompt at `/start`** gets a short **deterministic "recent games" line**, computed in code with no model call, so she knows about games played *after* the plan was built. Nothing blocks.
  3. **Games-app recommendations:** the plan builder may also output 0–2 `games_app_feedback` items `{game_id, kind: tune_difficulty|bug|ux|new_game|platform, title, rationale, evidence}`.
     - They're stored de-duplicated in `patients/{email}/games_app_recommendations` (key `game_id+kind+title`), with `status: new` and a count of how often each one was suggested.
     - Rules for the builder: base them on game data and his speech goals, **never on transcripts alone**; suggest new games for skills that are practiced in speech but have no game.
     - Platform example: "publish a `games_catalog_v1` key so the tutor learns about new games automatically".
- **Homework on the end screen.** `/end` already returns statuses. The ended screen ("כל הכבוד!") shows **big buttons for the planned game homework**, linking to `SIMON_APP_URL/<route>?user=<profile>`. The links are built in code from the catalog and mapping, never written by the model. The tutor also mentions the game naturally in her closing.
- **Fresh plans when he plays.** The hourly sweep already exists. It now also **rebuilds the next plan** when an account has played games **after its plan was built** (a deterministic check of the latest game date vs. `built_at`). This replaces the separate "refresh at start" call from the master design: same effect, and it never blocks `/start`.
- **Privacy:** games data stays in Upstash and Firestore. Only trends and recent sessions go to Gemini, and nothing personal goes into the repo (the profile mapping lives in `.env`).

## Files
| File | Purpose |
|---|---|
| `app/games.py` | `UpstashReader` (REST GET/SCAN, read-only, 5 s timeout, tolerant like Simon's `kv_store`); `load_catalog()`; `games_snapshot(profile)` → known + unknown games with trends and visits; `render_games_for_plan()`; `recent_games_line()`; `game_link(game_id, profile)`. |
| `prompts/games_catalog.yaml` | The 5 games: id/key, Hebrew name, route, skills, how to read the fields, what "progress" means for each. |
| `app/schemas.py` | `ClassPlan` gains `game_homework[]`, `games_note`, `games_app_feedback[]`. |
| `prompts/next_class.yaml` | How to use the games data: homework matched to the goal, the games note, recommendation rules. |
| `app/agent/next_class.py` | Adds the games section to the context; saves the recommendations (dedup). |
| `app/store.py` | `add_games_recommendation` (dedup + count); `latest_plan_built_at`. |
| `app/main.py` | `/start`: a recent-games line in the prompt. `/end`: returns the homework buttons (links built in code). Sweep: rebuilds stale plans after new game activity. |
| `app/config.py`, `deploy/*.sh`, `.env.example` | `SIMON_APP_URL`, `SIMON_PROFILES`, the Upstash URL and read-only token as secrets. |
| `static/index.html`, `static/app.js`, `static/style.css` | Game homework buttons on the ended screen. |
| `prompts/tutor.yaml` | Mention games naturally (the games note / recent line), and the homework in the closing. |
| `tests/` | A fake Upstash: discovery with and without a catalog, an unknown game, trends, the profile mapping (no mixing), the links, dedup, the stale-plan rebuild, and Upstash being down (never blocks). |

## Tasks
1. [x] Tomer: get Upstash's **read-only** REST token and Simon's Render URL into `.env` (see below).
2. [x] `games.py` + catalog + tests against a fake Upstash; then a **read-only live check** of Dad's and Tomer's real Simon data (print the snapshot).
3. [x] Plan builder: games context, homework, note, recommendations; a dry run on Tomer's account.
4. [x] `/start` games line, `/end` homework buttons, sweep rebuilds stale plans; secrets and env in the scripts.
5. [x] End-to-end: play a Simon game as `tomer` → the sweep rebuilds the plan → the next session mentions it and the end screen offers game homework.
6. [x] Commit and push.

## Manual steps for Tomer
1. **Upstash console** → your Redis database → **REST API** section → copy `UPSTASH_REDIS_REST_URL` and the **Read-Only Token** (*not* the regular token). Put them in `.env` as `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_READONLY_TOKEN`. `setup_gcp.sh` will move them into Secret Manager.
2. In `.env`: `SIMON_APP_URL=https://<your simon>.onrender.com` and `SIMON_PROFILES=<dad's email>=efraim,<your email>=tomer`.

## Done when
- [x] `pytest` passes (116 tests).
- [x] The live read-only snapshot shows Dad's and Tomer's real games, separately, with sensible trends.
- [x] After a session, the plan has game homework tied to the goal, and the end screen shows working buttons that open the right game on the right profile.
- [x] Playing a game, then waiting for the sweep, gives a rebuilt plan; the next session's tutor knows about the game.
- [x] Recommendations appear de-duplicated in Firestore.
- [x] Upstash being unreachable never blocks or breaks a session (no games data, everything else works).

## Commit
`Sub-plan 06: read-only Simon games integration, game homework and games-app recommendations`

## Notes from building it (2026-10-04)
- **Live read-only check** with the real data, per profile:
  - **Dad (`efraim`):** scrambled words 8 sessions this week, solved words from about 8.8 to **19.3** per session (animals: 27 words, 2 hints); Simon best sequence 2 → 6; change-a-word 6/6; memory game mismatches up (7 → ~19 at 10 pairs, a possible difficulty signal).
  - **Tomer (`tomer`):** separate data.
  - **The token is truly read-only:** a write attempt got **403 Forbidden**.
- **Dry run** (Tomer's memory + games): game homework fitted the goal (scrambled words + change-a-word on a name day); end-screen links `…/scramble?user=tomer`, `…/change?user=tomer`; a natural games note (it said "yesterday" for a game played today, a small imprecision from the `3.5-flash-lite` fallback under quota); no recommendations (correct: nothing in the data called for one).
- **Tests never reach the real Upstash:** `conftest` always overrides the games reader with a fake.
- **Deployed** as revision `hebrew-tutor-00019`. The Upstash URL and read-only token are in Secret Manager (`upstash-url`, `upstash-readonly-token`), and `SIMON_APP_URL` / `SIMON_PROFILES` come from `.env`.
- **The games were too much of a side note (Tomer's sessions ArHS6N1S / qMS36sZp).** The tutor mentioned the games only when he asked, and then read out a statistic ("9 words in the tools category"). The plan's game homework was **never** said in the closing, and the game never connected to the conversation. Fixes:
  - **Tutor v1.4:** the games are part of his practice. In the **opening**, if he played since last time, she asks about the game **first**, with an open question ("איך היה?", "איזו מילה הייתה הכי קשה?", "How was it? Which word was hardest?"), no scores. She uses the game's category and words as conversation material, and follows up whenever he mentions a game word.
  - **The closing always suggests the plan's game homework**, linked to today, mentioning the button.
  - **`recent_games_line` now includes the last category and the actual words** ("כלי עבודה: מגרפה, מברג, פטיש…", tools: rake, screwdriver, hammer…).
  - **Builder v0.5:** a `games_link_activity`, an in-session talking activity built on what he played.

  Replayed live with real games data: she opened with "ראיתי ששיחקת היום באפליקציה, איך היה?" ("I saw you played in the app today, how was it?"), asked which tools he played, turned "it was hard to find מגהץ" into "when do you use an iron at home?", then bridged to the other homework. A previous replay showed the closing suggesting the game ("כדאי לשחק במילים המבולגנות בקטגוריית המקומות", "worth playing scrambled words in the places category").
- **Status at commit (2026-10-04):** Tomer verified the end-to-end flow on the remote (revision `hebrew-tutor-00020`). The games are mentioned and suggested, and they're woven into the conversation. The stale-plan rebuild and recommendation de-dup are covered by tests. No recommendation has been produced from real data yet, because nothing in the data called for one so far.
