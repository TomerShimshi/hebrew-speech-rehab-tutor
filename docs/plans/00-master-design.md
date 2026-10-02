# Hebrew Speech Rehab Tutor — Implementation Plan

## Context
Tomer's father (~70) recently had a stroke and now struggles to speak Hebrew. We are building a small, private web app where he talks out loud in Hebrew with a voice tutor running on the **Gemini Live native-audio model**, chosen for low latency. Between sessions, three separate `SUMMARY_MODEL` calls do all the "thinking":
- remembers what was discussed last time
- tracks goals and target words
- reads his progress in the Simon games app (`../simon`, which will keep growing)
- searches for therapy advice
- prepares each session's lesson plan
- recommends changes to the games app

Decisions so far:
- Python FastAPI + vanilla JS.
- Google sign-in restricted to an email allowlist.
- Read-only access to the Simon progress data in Upstash.
- One repo at the root of `hebrew_helper/`. The empty nested `hebrew-speech-rehab-tutor/` folder (no commits, same remote) is deleted.
- Deploy with `gcloud run deploy`. AI Studio supplies the Gemini API key and is where prompts get tested.
- A communication-therapist review of this plan has been applied (see "Therapy design").

## Execution approach: 9 separate sub-plans, each finished, committed and pushed on its own
This big plan stays the **master design**. It is split into 9 sub-plan files that live in the repo:
```
docs/plans/00-master-design.md      ← this document (design reference, milestone list)
docs/plans/01-gcp-skeleton.md
docs/plans/02-voice-agent-v0.md
docs/plans/03-auth-db-transcripts.md
docs/plans/04-memory-update.md
docs/plans/04.5-memory-reset.md        ← added: caregiver UI to forget memory / reset an account + mic mute
docs/plans/05-next-class-builder.md
docs/plans/06-games-integration.md
docs/plans/07-web-search-subagent.md
docs/plans/08-caregiver-page.md
docs/plans/09-polish.md
```
Each sub-plan file contains:
- Goal
- Scope, and what is explicitly out of scope
- Files to add or change
- Step-by-step tasks
- Manual steps for Tomer (GCP console, keys)
- "Done when" checks and tests
- Commit message

**Workflow for each sub-plan:**
1. Refine the sub-plan (a quick plan-mode pass, using what the previous step taught us).
2. Implement only that sub-plan.
3. Run its tests and "done when" checks, and have Tomer verify.
4. Tick its checklist, then `git commit` and `git push origin main`.
5. Stop. The next sub-plan starts in a new round.

**This round:**
- (a) Delete the empty nested `hebrew-speech-rehab-tutor/` so `hebrew_helper/` is the one repo (remote `TomerShimshi/hebrew-speech-rehab-tutor`).
- (b) Write `docs/plans/00`–`09`. File 00 is this document; files 01–09 are expanded from the milestone sections below.
- (c) Implement **sub-plan 01** only.
- (d) Commit and push after 01 passes its checks.

**Sub-plan 01 details (for this round)**
- **Code**
  - `app/main.py`: FastAPI; `GET /api/health` returns `{status, gemini_key_configured}` and never the key's value; static files are served from `/`.
  - `app/config.py` (pydantic-settings).
  - `static/index.html`: RTL Hebrew, large font, one big "שנתחיל?" button (not wired up yet).
  - `tests/test_health.py`.
  - `Dockerfile` (python:3.12-slim, uvicorn on `$PORT`), `requirements.txt` (fastapi, uvicorn, pydantic-settings), `requirements-dev.txt` (pytest, httpx).
  - `.gitignore`, `.env.example`, `README.md`.
- **`deploy/setup_gcp.sh`** (idempotent; takes `PROJECT_ID`, `REGION=us-central1`, `BILLING_ACCOUNT`):
  - enable the Cloud Run, Artifact Registry, Cloud Build and Secret Manager APIs (Firestore is enabled in sub-plan 03)
  - create the `gemini-api-key` secret from a prompt or stdin
  - grant the Cloud Run runtime service account `secretAccessor`
  - create a $1 budget alert
- **`deploy/deploy.sh`**: `gcloud run deploy hebrew-tutor --source . --region us-central1 --min-instances 0 --max-instances 1 --memory 512Mi --set-secrets GEMINI_API_KEY=gemini-api-key:latest --allow-unauthenticated`. The login gate comes in sub-plan 03.
- **Manual steps for Tomer**
  - create the GCP project and link billing
  - create the API key in AI Studio for that project
  - `gcloud auth login`
  - run both scripts. I'll run them with him if the gcloud CLI is set up on this machine; I'll check `gcloud --version` first.
- **Done when**
  - `pytest` passes
  - the page loads locally and at the Cloud Run URL
  - `/api/health` on Cloud Run shows `gemini_key_configured: true`

## Milestones (each becomes one sub-plan file)
The rest of this document is the target design.

**M1: Skeleton web app on GCP.** In the repo, delete the nested `hebrew-speech-rehab-tutor/`. Add the FastAPI app with `GET /api/health` and a static Hebrew RTL `index.html` with one big "שנתחיל?" button (not wired up yet). Add `Dockerfile`, `requirements*.txt`, `.gitignore`, `.env.example`, `app/config.py`, one pytest, and a README. Add `deploy/setup_gcp.sh`: create or select a project, enable Cloud Run, Artifact Registry, Cloud Build, Secret Manager and Firestore, create a budget alert, and put `GEMINI_API_KEY` in Secret Manager. Add `deploy/deploy.sh` (`gcloud run deploy --source . --min-instances 0 --max-instances 1`).
*Done when:* the Cloud Run URL shows the page, `/api/health` returns OK, and the secret is mounted, with `/api/health` reporting `gemini_key_configured: true` and never the value.

**M2: First voice-agent draft** (no DB, no memory)
- `prompts/tutor.yaml` v0: role, style rules, a simple session structure, safety rules.
- `app/prompts.py` to render it.
- `POST /api/session/start` mints an ephemeral token locked to the Live model and prompt.
- Browser: mic capture and playback worklets, a direct WebSocket to Gemini Live, big RTL captions, the "סיום" end button, VAD at ~4–5 s silence, and the always-visible emergency button.

*Done when:* Tomer holds a natural Hebrew conversation on the tablet with low latency, and the tutor doesn't cut him off.

**M3: Login + Firestore + transcript saved**
- Firebase Auth Google sign-in with `ALLOWED_EMAILS`; the API rejects anyone else.
- Firestore: `patients/abba`, `sessions/{id}`, `turns/{n}`.
- `POST /api/session/{id}/turns`, flushed every ~10 s and at the end, saved deterministically.
- Security rules that deny all client access.

*Done when:* after a session, the full transcript appears in Firestore in order, and a non-allowlisted account gets a 403.

**M4: Memory update (call #2)**
- `schemas.py` (`MemoryEdit`, `SessionMetrics`), `memory_store.py`, `prompts/memory_update.yaml`.
- The generic `agent/runner.py` function-calling loop with the memory tools: `read_memory`, `update_memory`, `record_word_result`, `save_session_metrics`, `raise_flag`.
- The `memory_prompt` rewrite, with history kept.
- `/end` runs it; the `prepare` step recovers an unfinished session.
- The tutor prompt now includes `memory_prompt`.

*Done when:* the second session opens by recalling the first, and memory history shows both versions.

**M4.5: Forget memory / reset an account + microphone mute** (added at Tomer's request)
- A caregiver-only "ניהול" screen: forget an account's memory (transcripts kept) or delete all of its data, with typed confirmation and a JSON backup in the private bucket. It's an early slice of the caregiver page (08).

*Done when:* "forget memory" makes the next session greet like a first meeting, and Dad's account can't see or call it.

**M5: Next-class builder (call #3) + ClassPlan**
- The `ClassPlan` schema, `prompts/next_class.yaml`, `therapy_techniques.yaml` and the `get_therapy_technique` tool.
- The next ClassPlan is saved as `next_plan` and rendered into the tutor prompt.
- The profile fields `speech_profile`, `therapist_goals` and `avoid` are edited in Firestore by hand for now.
- Includes the baseline plan type for the first 2 sessions.

*Done when:* each session follows its plan (probe words, primary goal, homework), and changing `speech_profile` changes the exercises.

**M6: Games-app integration**
- `app/games.py`: the read-only Upstash client, catalog discovery (`games_catalog_v1` → `games_catalog.yaml` → key SCAN), and trends.
- Tools `list_games` and `read_game_progress`.
- Call #1 (session refresh), with its deterministic needs-refresh check.
- `GamesAppRecommendation` output in call #3.
- Homework recommends real games.

*Done when:* new Simon game activity triggers a refresh, and the tutor mentions real results and recommends a specific game.

**M7: Web-search sub-agent**
- `agent/search_agent.py` using `gemini-2.5-flash` + `google_search`, with `prompts/search_agent.yaml`, JSON output and the `technique_notes` cache.
- Exposed as a tool in calls #1 and #3.

*Done when:* a plan that faces a new difficulty cites a grounded, sourced technique, and a repeated question hits the cache.

**M8: Caregiver page**
- `/caregiver` for `CAREGIVER_EMAILS`.
- Flags banner, sessions and transcripts, profile and therapist editing, memory history with rollback, recommendations with the "Create GitHub issue" button, family tips.

*Done when:* Tomer can manage everything without the Firestore console.

**M9: Polish**
- Audio recording to Cloud Storage with a 90-day lifecycle, and "review with audio" items.
- Graphs for probes, mood and words.
- The mood-faces check-in, tap-to-talk mode, target words shown pointed, a PWA manifest, and "export for therapist".
- Final free-tier check.
- Afterwards, the paid-tier switch.

## Two-model design (no tools in the live conversation)
| | **Live model** (`LIVE_MODEL`, gemini-3.8-live) | **Agent model** (`SUMMARY_MODEL`, gemini-3.8-flash) |
|---|---|---|
| Job | Only talk with Dad: encourage him, cue him, practice with him, give homework | Every tool call: memory, progress, research, planning, recommendations |
| Tools | **Only `end_session`** (she hangs up after her goodbye; added in 02). Nothing else, so no added latency | Function-calling loop (at most ~8 rounds) plus structured output |
| Input | System prompt = `prompts/tutor.yaml` + the rendered **ClassPlan** + consolidated memory | Firestore data, Upstash data, YAML knowledge, web search |

**The transcript is saved deterministically, never by an LLM.** The browser sends transcript turns to `POST /api/session/{id}/turns` every ~10 s and once more at the end. Plain Python writes them to Firestore. The Opus audio upload goes to Cloud Storage the same way.

**Three separate `SUMMARY_MODEL` calls, each with its own prompt YAML, tools and output schema:**
| # | When | Call | Output |
|---|---|---|---|
| 1 | Session start, **only when needed** | **Session refresh.** A deterministic check runs first: is there no plan yet, has there been new game activity or a therapist/profile edit, have ≥3 days passed, or is this a baseline session? If none apply, the stored next-session plan is used as-is and the LLM is not called. | An updated `ClassPlan` |
| 2 | Right after the session ends | **Memory update.** Reads the transcript and uses tools to update memory sections, word results, metrics and flags, then rewrites the `memory_prompt`. | The update to the saved memory (previous version kept in history) |
| 3 | After #2 finishes | **Next-class builder.** Reads the *updated* memory, games progress, therapist goals and techniques, and files games-app recommendations. | The next `ClassPlan` + rendered Live prompt, saved as `next_plan` |

**Web-search sub-agent.** Google Search grounding is free only on `gemini-2.5-flash` (500 requests/day; not free on 3.x). It also can't be combined with function calling in the same request. So calls #1 and #3 get a `search_therapy_advice(question, context)` tool, which **starts a separate sub-agent call** with these settings:
- `SEARCH_MODEL=gemini-2.5-flash` with the `google_search` tool.
- Its own system prompt, `prompts/search_agent.yaml`. The prompt:
  - casts it as a research assistant to a speech-language pathologist
  - tells it to prefer clinical sources (ASHA, Aphasia United, AARP, PubMed/PMC, peer-reviewed aphasiology, Israeli/Hebrew SLP sources)
  - requires every claim to cite a source URL (taken from grounding metadata)
  - requires practical, home-practice-safe techniques adapted to Hebrew and the patient's `speech_profile`
  - forbids medical, medication or prognosis advice
  - requires it to say "no reliable evidence found" rather than guess
  - requires it to return JSON: `{summary, techniques[{name, how_to, hebrew_example, source_url}], confidence}`
- The patient context passed in is minimal: the profile type, the goal and the difficulty. No names or personal details.
- Results are cached in `technique_notes`, keyed by a normalized question, and shown on the caregiver page.

## Session lifecycle
**1. Pre-session** (`POST /api/session/prepare`, run when the app opens)
- If the deterministic check says nothing changed, the stored `next_plan` is used immediately.
- Otherwise call #1 (session refresh) runs while the screen shows "מכין את השיעור…" ("preparing the lesson…").
- The `ClassPlan` is saved on the session doc.

**2. Live session** (`POST /api/session/start`)
- The backend renders the tutor YAML with the ClassPlan and memory.
- It mints a one-use **ephemeral token** whose config is locked with `live_connect_constraints`: the system instruction, the Hebrew voice, input and output transcription, VAD settings, session resumption and context compression. **No tools.**
- The browser connects **directly to Gemini** over WebSocket. The API key never reaches the browser, and audio never passes through our backend.
- In the browser:
  - An AudioWorklet captures 16 kHz PCM from the mic, and another plays the 24 kHz PCM the model sends back.
  - `MediaRecorder` also saves an Opus recording of his mic for the therapist to review.
  - Big RTL captions show both sides. When the tutor says a ClassPlan target word, the client matches it in the transcript and shows it in large, fully pointed Hebrew (a written cue, with no tool call needed).
- Transcript turns are flushed to the backend every ~10 s.
- **VAD / wait time:** automatic VAD with low end-of-speech sensitivity and `silence_duration_ms` of about **4000–5000**. A large "אני חושב…" ("I'm thinking…") button holds the turn open. The caregiver page can switch him to **tap-to-talk** mode, which uses manual `activityStart`/`activityEnd`.
- The target length is ~10–12 min, under the 15-min limit for audio sessions.

**3. Post-session** (`POST /api/session/{id}/end`, or run lazily on the next prepare if the tab was simply closed)
- The final transcript flush happens deterministically.
- Then call #2 (memory update) runs, followed by call #3 (next-class builder). Both run inside the `/end` request, not as a background task. Cloud Run throttles the CPU once a response has been sent, so a background task could stall. Meanwhile the browser shows a friendly "כל הכבוד! נתראה מחר" ("Well done! See you tomorrow") screen, and the model calls take ~20–40 s. If the tab closes before they finish, the next `prepare` sees the unfinished state and runs whatever is left. The session status moves `ended → memory_updated → next_plan_ready`, so a failed step can be retried on its own.

## Agent tools (SUMMARY_MODEL only)
- **Read**
  - `read_memory(section)`
  - `list_sessions(n)`
  - `read_session_transcript(id)`
  - `read_word_bank(filter)`
  - `read_therapist_goals()`
  - `read_baseline()`
- **Games, discovered generically**
  - `list_games()`: loads the catalog from Upstash key `games_catalog_v1` if the Simon app publishes one. Otherwise it falls back to `prompts/games_catalog.yaml` in this repo plus an Upstash `SCAN` for `*progress*` keys.
  - `read_game_progress(key, n)`: returns raw recent sessions plus computed trends (count, frequency, last played, best/avg).
  - Nothing is hard-coded to today's 3 games. New games show up through the catalog or through new keys, and the LLM interprets their progress JSON.
- **Knowledge**
  - `get_therapy_technique(situation)`: looks up the curated `prompts/therapy_techniques.yaml`.
  - `search_therapy_advice(query)`: grounded web search, as described above.
- **Write**
  - `update_memory(section, op: add|replace|remove, content)`, validated with Pydantic
  - `record_word_result(word, result, cue_level, asr_confidence)`: a deterministic spaced-retrieval merge in Python
  - `save_session_metrics(...)`
  - `raise_flag(kind, severity, evidence)`
  - `add_games_app_recommendation(...)`

## Therapy design (research + therapist review)
- **Dose.** Daily sessions of 10–12 min add about 1.2 h/week on top of human therapy. That is a sensible supplement: RELEASE found the best gains at 2–4 h/week and 20–50 h in total ([NIHR](https://evidence.nihr.ac.uk/alert/therapy-for-language-problems-after-a-stroke-is-most-effective-when-given-early-and-intensively/), [Stroke 2022](https://www.ahajournals.org/doi/10.1161/STROKEAHA.121.035216)). An optional second short session later in the day is allowed.
- **One primary goal per session.** Six activities in 10 minutes would be too many, so activities rotate across days. Structure of each session:
  1. **Check-in**: mood picked on a 1–5 faces scale on screen, plus a short greeting that recalls last time (~1 min)
  2. **Warm-up**: automatic speech (~1 min)
  3. **Probe**: 5 treated + 5 untreated words, uncued, same scoring every time (~2 min)
  4. **Main block**: the primary goal, with many practice attempts (~5 min)
  5. **Functional/script or conversation** (~2 min)
  6. **End on a success**: praise the effort, give homework (games + one line to practice with his son)
- **The profile decides the exercises.** The caregiver page has a `speech_profile` field (aphasia / apraxia / dysarthria / mixed / unknown) that his human therapist fills in.
  - **Unknown:** only low-risk activities (automatic speech, repetition, conversation).
  - **Aphasia:** a cueing hierarchy: semantic cue → **Hebrew root/pattern cue** → spoken CV-syllable cue ("שוּ…", never the letter name) → sentence completion → model the word and have him repeat it. Plus SFA and script training ([ASHA](https://www.asha.org/practice-portal/clinical-topics/aphasia/), [Hebrew morphology therapy](https://www.tandfonline.com/doi/full/10.1080/02687038.2023.2257354)).
  - **Apraxia:** "watch me, listen, say it with me", a slow rate, many repetitions of the same word ([ASHA AOS](https://www.asha.org/practice-portal/clinical-topics/acquired-apraxia-of-speech/)).
  - **Dysarthria:** breath support, loudness, rate control, over-articulation ([ASHA](https://www.asha.org/practice-portal/clinical-topics/dysarthria-in-adults/)).
- **Baseline.** The first 2 sessions use a `baseline` plan type:
  - naming ~30 everyday Israeli items, by definition/description
  - repeating words of 1, 2 and 3 syllables
  - yes/no questions and one-step commands
  - reading single words aloud
  - counting 1–10
  - a 1-minute free-talk sample

  The result is labelled "observations for the therapist", **never a diagnosis**.
- **Comprehension vs. production.** Include yes/no reliability pairs ("קוראים לך X?" / "קוראים לך Y?", "Is your name X?" / "Is your name Y?"). Until his yes/no answers prove reliable, the tutor must not act on them.
- **Errors.** After 2 failures, give the model word and have him repeat it. Try the same word again 2–3 minutes later in the session, and avoid letting him repeat the same error ([review](https://pmc.ncbi.nlm.nih.gov/articles/PMC10023178/)).
- **Fatigue and frustration.** The tutor watches for:
  - long pauses
  - errors rising across a run of items
  - "עזוב" ("forget it") / "לא יכול" ("I can't")
  - the same wrong answer repeated

  When it sees them, it drops to an easy task and ends early on a success.
- **Style**
  - slow, short sentences, one question at a time
  - always addresses him in the masculine form
  - adult and respectful: no childish tone, no over-praise, never "לא נכון" ("wrong")
  - never finishes his sentence
  - doesn't correct gender-agreement errors unless that is the target
  - never guesses what he meant and moves on as if he confirmed it
  - no medical, medication or prognosis advice
- **Hebrew content**
  - counting in the feminine form, days of the week, months
  - songs to confirm with the family: ירושלים של זהב, התקווה, Naomi Shemer songs, Shabbat songs
  - blessings, if the family is observant
  - `language_history` in the profile, because many Israelis his age learned Hebrew as a second language
- **Speech recognition is unreliable on impaired speech.** The agent treats transcripts as uncertain. Every scored item carries an `asr_confidence`. Items it is unsure about are listed as "review with audio" for the therapist, and game difficulty is never changed based on transcripts alone.
- **Emergency (always on, on the client).** A visible "מרגיש פתאום לא טוב?" ("Suddenly not feeling well?") button opens a full-screen BE-FAST message with **"התקשרו למד״א 101"** ("Call Magen David Adom 101") ([BE-FAST](https://www.stroke.org/en/about-stroke/stroke-symptoms)). The memory-update call (#2) also compares the session to his baseline and recent sessions. A sudden decline raises a **high-severity flag** that shows as a banner on the caregiver page. The live model is never trusted to detect this.
- **Human therapist in the loop.** Before sessions start, his therapist signs off on the profile, the goals and an "avoid" list. The app supplements therapy and does not replace it.

## Prompt & knowledge files (`prompts/`, versioned; `prompt_version` is saved on each session)
- `tutor.yaml`: the Live model's role and goal, style rules, session structure, the cueing hierarchies for each profile, the fatigue protocol, safety rules, and `{placeholders}` where the ClassPlan and memory go.
- `session_refresh.yaml`: instructions for call #1.
- `memory_update.yaml`: instructions for call #2, including the consolidation rules and the size budget.
- `next_class.yaml`: instructions for call #3.
- `search_agent.yaml`: the system prompt for the web-search sub-agent (described above).
- `therapy_techniques.yaml`: the curated techniques above, with Hebrew example phrasings.
- `games_catalog.yaml`: the fallback description of each game (name, skills, URL, progress key, adjustable settings).

## Schemas (`app/schemas.py`, Pydantic, also used as `response_schema`)
- **`ClassPlan`**
  - `plan_type` (baseline/regular)
  - `speech_profile`
  - `primary_goal`
  - `probe_set{treated[], untreated[]}`
  - `targets[{word, pointed_form, root, semantic_cue, syllable_cue, sentence_completion}]`
  - `script_lines[]`
  - `automatic_items[]`
  - `conversation_topics[]`
  - `fatigue_plan{easy_fallback}`
  - `avoid[]`
  - `homework{games[{game_id, reason}], family_practice_line}`
  - `recall_from_last_time`
- **`SessionMetrics`**
  - `mood_score`
  - probe accuracy (treated vs. untreated)
  - accuracy per word by cue level
  - median response latency
  - independent vs. assisted turns
  - fatigue markers and the minute they started
  - `review_with_audio[]`
  - `flags[]`
- **`MemoryEdit`**, **`GamesAppRecommendation{game_id, kind: tune_difficulty|bug|ux|new_game|platform, title, rationale, evidence, suggested_change, priority}`**, **`ConsolidatedMemory`**

## Games-app feedback loop (future-proof)
- After each session the agent reviews games progress against his speech goals and files `GamesAppRecommendation`s. They are deduplicated by `game_id + kind + title` and deliberately include "platform" items, such as "publish a `games_catalog_v1` key so the tutor discovers new games automatically".
- Games are linked to therapy goals. For example, the sub-word game practices this week's Hebrew roots.
- On the caregiver page, Tomer reviews each recommendation and clicks **"Create GitHub issue"** to open an issue on `TomerShimshi/simon`. This uses a fine-grained token that can only write issues on that repo. Nothing is posted automatically. The issue body is written so it can be handed straight to Claude Code.
- **No code changes to the Simon repo in this project.**

## Data (Firestore; client access denied by security rules, only the backend service account reads and writes)
- `patients/abba`: the profile:
  - how to address him
  - family names
  - interests and songs
  - `language_history`
  - `speech_profile`
  - `therapist_goals`
  - `avoid[]`
  - settings (VAD mode, silence ms)
- `patients/abba/memory/current`:
  - `memory_prompt`
  - `word_bank{word:{attempts, results_by_cue, next_due}}`
  - `scripts[]`
  - `next_plan` (ClassPlan + rendered Live prompt)
  - `baseline`
  - `memory/history/{session_id}` keeps previous versions
- `patients/abba/sessions/{id}`: `class_plan`, `prompt_version`, metrics, summary, status, `audio_uri`. The `turns/{n}` subcollection holds the full transcript (a subcollection because Firestore caps a document at 1 MiB).
- `patients/abba/{flags, games_app_recommendations, technique_notes}/{id}`
- **Audio:** a Cloud Storage bucket in us-central1 (free tier: 5 GB), holding ~1 MB of Opus per session. A lifecycle rule deletes recordings after 90 days.

## Caregiver page (`/caregiver`, restricted to `CAREGIVER_EMAILS`)
- Always visible: flags banner, emergency info, and communication tips for the family (wait for him, don't finish his sentences, use yes/no questions, write down key words).
- Graphs: probe trend (treated vs. untreated), mood over time, word-bank progress.
- Sessions: transcripts with audio playback and the items marked "review with audio".
- Editing: profile, therapist goals, the avoid list and VAD mode. A "memory history" view shows previous memory versions and can roll back to one.
- Games-app recommendations, with the GitHub-issue button.
- "Export for therapist": a printable summary.

## Repo layout (root of `hebrew_helper/`)
```
app/main.py, config.py, auth.py (firebase-admin + allowlists), live_token.py
app/agent/runner.py        generic SUMMARY_MODEL function-calling loop (max rounds, timeout)
app/agent/tools.py         tool declarations + handlers (above)
app/agent/refresh.py       call #1: deterministic needs-refresh check + LLM refresh → ClassPlan
app/agent/memory_update.py call #2: transcript → memory edits, word results, metrics, flags, memory_prompt rewrite
app/agent/next_class.py    call #3: updated memory → next ClassPlan + rendered prompt + games-app recs
app/agent/search_agent.py  web-search sub-agent (SEARCH_MODEL + google_search, own system prompt, cached)
app/transcripts.py         deterministic turn/audio persistence
app/prompts.py, schemas.py, memory_store.py (Firestore + in-memory fake), word_bank.py
app/games.py               catalog discovery + Upstash read-only client (pattern from ../simon/src/simon/kv_store.py)
app/audio_store.py, github_issues.py
prompts/*.yaml
static/index.html, app.js, audio/{capture,playback}-worklet.js, caregiver.html, caregiver.js, manifest.json
tests/, Dockerfile, requirements*.txt, .env.example, deploy/setup_gcp.sh, deploy/deploy.sh, README.md
```

## GCP free tier
- **Cloud Run:** `--min-instances 0 --max-instances 1 --memory 512Mi` in us-central1.
- **Firestore:** the `(default)` database in native mode.
- **Cloud Storage:** one bucket in us-central1.
- **Firebase Auth:** the Spark (free) plan.
- **Secret Manager** (6 active versions free), with these 4 secrets:
  - `GEMINI_API_KEY`
  - `UPSTASH_REDIS_REST_URL`
  - `UPSTASH_REDIS_REST_TOKEN`, using Upstash's **read-only** token
  - `GITHUB_ISSUES_TOKEN`
- **Billing:** the account is required, with a **$1 budget alert**.
- **Gemini: free tier for the POC.** On the free tier, Google may use the content (his voice and health context) to improve its products. Once the POC works, switch to the paid tier, at roughly $0.20 per session. This is a later step, and the README will note it.

## Verification
1. **`pytest`**, with a fake LLM, fake stores and a fake Upstash:
   - YAML rendering of the prompts
   - the needs-refresh check (each trigger)
   - calls #2 → #3 run in order, with status transitions and resume after a failure
   - the search sub-agent's system prompt and JSON parsing, and cache hits
   - transcript turns are saved without any LLM
   - the agent loop runs tools and stops at the max-round limit
   - `update_memory` validation
   - word-bank spacing
   - consolidation keeps the previous memory in history and respects the size cap
   - games discovery with and without a catalog, and with an unknown progress key
   - recommendation dedup
   - auth allowlists
   - API routes
2. **Run locally** with `uvicorn app.main:app` and `.env`, in Chrome, and check:
   - "prepare" produces a sensible ClassPlan and returns immediately on the fast path
   - a Hebrew conversation has low latency and doesn't cut him off at the ~4–5 s wait
   - target words show pointed on screen
   - the emergency button works
   - on end, the transcript, audio, metrics, rewritten memory and next-plan draft are all in Firestore
3. **Second session:** the tutor recalls the previous one, reuses due words, and assigns homework naming real games from the discovered catalog. The caregiver page shows the recommendations, and a test issue can be created on the Simon repo.
4. **Deploy** with `deploy/deploy.sh` and test on the actual tablet. Also check:
   - Cloud Run logs
   - a Google account not on the allowlist is rejected
   - the budget alert exists
5. **Repo:** delete the nested `hebrew-speech-rehab-tutor/`. Commit to `main` and push only when Tomer asks.
