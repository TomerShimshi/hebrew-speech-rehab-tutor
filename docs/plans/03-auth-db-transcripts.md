# Sub-plan 03: Login, Firestore and saved transcripts

Part of the [master design](00-master-design.md). Depends on [02](02-voice-agent-v0.md) (done: the Live voice tutor on Cloud Run).

## Goal
- Only allowlisted Google accounts can use the app. The public URL stops being an open door to the Gemini quota.
- Every session and its **full transcript are saved deterministically** to Firestore by our Python code. No LLM is involved in saving. This is the raw material the memory update in sub-plan 04 works from.

## Out of scope
- memory and any LLM post-processing (04)
- the caregiver UI (08); for now, transcripts are viewed in the Firestore console
- audio recording (09)
- the patient profile, which stays in the private bucket (decided in 02) rather than moving to Firestore

## Design decisions (updated after 02, 2026-09-30)
- **Auth: Firebase Authentication with Google sign-in** (free), on the same GCP project `heb-practice`.
  - **Browser:** the Firebase JS SDK 12.x, loaded as ESM from `www.gstatic.com`. It signs in with `signInWithPopup`, and falls back to a redirect where popups are blocked (iPad Safari). Login persists on the device, so Dad signs in **once per device**.
  - **Backend:** verifies the Firebase ID token with `google-auth`'s `id_token.verify_firebase_token` (audience = project ID). That avoids the heavier `firebase-admin` package. It checks `email_verified` and that the email is in `ALLOWED_EMAILS`.
  - Every `/api/*` route except `/api/health` and `/api/config` requires a signed-in, allowlisted user. The 30/hour token rate limit stays as a second guard.
  - `GET /api/config` serves the **public** Firebase web config (apiKey, authDomain, projectId, appId). These values are designed to be public; access is controlled by the auth check.
  - **The emails stay out of the public repo.** `ALLOWED_EMAILS` and `CAREGIVER_EMAILS` go in the local `.env`, and `deploy.sh` passes them to Cloud Run as environment variables. `CAREGIVER_EMAILS` is only used from 08 on.
  - Cloud Run stays `--allow-unauthenticated`: the page and assets are public, and the **API** is what's protected. IAM-level auth would block the browser itself.
- **Firestore:** the native-mode `(default)` database in `us-central1`. The free quota only applies to `(default)`: 1 GiB, 50k reads/day, 20k writes/day. A session is about 1 session doc plus about 100 turn docs, so daily use is well under 1% of the quota.
  - Security rules are **deny all** for clients. Only the backend's service account (IAM `roles/datastore.user`) reads and writes.
  - Data model:
    - `patients/{PATIENT_ID}`: minimal. It holds `created_at` and makes the tree navigable. `PATIENT_ID` is config, default `patient-1`.
    - `patients/{pid}/sessions/{sid}`: `started_at`, `ended_at`, `status` (`active`/`ended`), `end_reason` (`tutor_goodbye` / `end_button` / `error` / `abandoned`), `prompt_version`, `model`, `user_email`, `turn_count`.
    - `patients/{pid}/sessions/{sid}/turns/{seq:05d}`: `seq`, `speaker` (`patient` / `tutor`), `text` (Gemini's transcript, which is what the model heard or said), `live_text` (the browser recognizer's version for his lines, useful to compare), `t_start_s` (seconds from session start), `interrupted` (for tutor lines cut off by barge-in), `updated_at`.
- **Deterministic transcript saving:**
  - Each caption line gets a **sequence number** in the browser. A line can keep growing (her text streams in, and his line gets Gemini's text later), so saving is an **upsert by `seq`**: sending the same line again overwrites it, and retries never duplicate.
  - The browser keeps a set of lines that changed and flushes them every **~10 s**, at session end, and on `pagehide` (`fetch` with `keepalive`, which, unlike `sendBeacon`, can carry the `Authorization` header).
  - `/api/session/start` creates the session doc and returns `session_id`. A resumed connection (after `goAway`) reuses the same session.
  - `POST /api/session/{id}/turns` accepts up to 50 turns per call, validated with Pydantic (text ≤ 5,000 chars). Turns for a session that isn't `active` or belongs to another user are rejected.
  - `POST /api/session/{id}/end {reason}` does a final flush and then marks the session `ended`.
  - Sessions left `active` (the tab was killed) are marked `abandoned` the next time a session starts. Their transcript up to the last flush is kept.
- **Local development** uses the real Firestore through Application Default Credentials (`gcloud auth application-default login`). Tests use an **in-memory store**, so no emulator is needed.

## Files
| File | Purpose |
|---|---|
| `app/auth.py` | `verify_user` dependency: Bearer token → `verify_firebase_token` → `email_verified` + allowlist. Returns `User(email, uid)`. Also `require_caregiver`, used from 08. The verifier is injectable for tests. |
| `app/store.py` | A `SessionStore` Protocol with two implementations: `FirestoreSessionStore` and `InMemorySessionStore`. Methods: `create_session`, `upsert_turns`, `end_session`, `get_session`, `list_turns`, `mark_abandoned`. |
| `app/transcripts.py` | Pydantic `TurnIn` (`seq ≥ 0`, speaker enum, text length caps) and `TurnsBatch` (≤ 50). Idempotent doc ids (`{seq:05d}`). |
| `app/config.py` | Adds `ALLOWED_EMAILS` and `CAREGIVER_EMAILS` (comma-separated lists), `PATIENT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_APP_ID`, `GCP_PROJECT_ID`. |
| `app/main.py` | `GET /api/config`. Auth on `/api/session/*`. `start` creates the session doc and marks stale ones `abandoned`. New `POST /api/session/{id}/turns` and `POST /api/session/{id}/end`. |
| `static/auth.js` | Firebase init from `/api/config`. `signIn()`, `signOut()`, `getIdToken()` (auto-refreshed), and an auth-state listener. |
| `static/app.js` | A sign-in screen ("התחברות עם Google", "Sign in with Google") before the start screen. A clear Hebrew message for accounts that aren't allowed. `Authorization: Bearer <idToken>` on API calls. Line `seq`s, the dirty set, the 10 s flush, flushes on end and `pagehide`, and `end_reason`. |
| `static/index.html`, `static/style.css` | The sign-in screen, plus a small "התנתקות" ("sign out") link for Tomer. |
| `firestore.rules` | `allow read, write: if false;` (kept in the repo as documentation, and deployed by the setup script). |
| `deploy/setup_gcp.sh` | Adds the `firestore`, `firebase`, `identitytoolkit` and `firebaserules` APIs. Creates the `(default)` Firestore database (native, `us-central1`) if missing. Gives the runtime service account `roles/datastore.user`. Deploys `firestore.rules` through the Firebase Rules REST API. |
| `deploy/deploy.sh` | Passes `ALLOWED_EMAILS`, `CAREGIVER_EMAILS`, `PATIENT_ID` and the Firebase web config from the local `.env` as env vars. |
| `.env.example` | Documents the new variables (no real values). |
| `tests/test_auth.py`, `tests/test_transcripts.py`, `tests/test_session_flow.py` | Allowlist accept/reject, unverified email, missing or bad token; turn validation and idempotent upsert; the full start → turns → end flow on the in-memory store; a stranger's token can't write to someone else's session; stale session → `abandoned`. |
| `requirements.txt` | Adds `google-cloud-firestore` (plus `google-auth`, already a dependency of `google-genai`). |

## Tasks
1. [x] Tomer: the manual Firebase steps below.
2. [x] Backend: `auth.py`, `store.py`, `transcripts.py`, endpoints and tests.
3. [x] Frontend: `auth.js`, the sign-in screen, token on API calls, transcript flushing.
4. [x] `setup_gcp.sh`: Firestore database, IAM and rules. `deploy.sh`: the new env vars.
5. [x] Local test (ADC), then deploy and test on the remote and the tablet.
6. [x] Commit and push.

## Manual steps for Tomer
1. **Add Firebase to the existing GCP project:** https://console.firebase.google.com → "Add project" → choose **heb-practice** (the existing project). Google Analytics isn't needed. The project already has billing, so Firebase shows the "Blaze" plan. Our usage stays inside the free quotas, and the 4 ILS kill switch still covers everything.
2. **Enable Google sign-in:** Firebase console → Authentication → Get started → Sign-in method → **Google** → Enable (choose a support email).
3. **Authorized domains:** Authentication → Settings → Authorized domains → add `hebrew-tutor-279739778074.us-central1.run.app` and `hebrew-tutor-dcw6y2qamq-uc.a.run.app`. `localhost` is there by default.
4. **Register a web app:** Project settings → "Your apps" → Web (`</>`) → a nickname such as `tutor-web`, with no Hosting. Copy `apiKey`, `authDomain` and `appId` into `.env` as `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` and `FIREBASE_APP_ID`.
5. **Allowlist:** in `.env`, set `ALLOWED_EMAILS=<Dad's Google account>,<your Gmail>` and `CAREGIVER_EMAILS=<your Gmail>`.
6. **Local Firestore access:** run `gcloud auth application-default login` once.

## Done when
- [x] `pytest` passes (47 tests).
- [x] Opening the app shows the sign-in screen. An allowlisted account gets in and **stays signed in** after a reload. Another Google account gets a friendly Hebrew "no access" message, and `/api/session/start` returns **403** for it.
- [x] Calling `/api/session/start` without a token returns **401**, so the Gemini quota is no longer reachable by strangers.
- [x] After a real session, `patients/patient-1/sessions/{id}/turns` in Firestore holds the **full transcript in order**, with nothing missing or duplicated, and the session doc shows `ended` with the right `end_reason`.
- [ ] Closing the tab mid-session keeps everything except the last few seconds, and the next start marks that session `abandoned`.
- [ ] Direct client access to Firestore is denied (checked in the Rules Playground).
- [ ] Firestore usage in the console stays far below the free quota.

## Commit
`Sub-plan 03: Google sign-in allowlist, Firestore sessions and deterministic transcripts`

## Notes from doing it
- **Firebase setup gotchas:** adding Firebase to an existing GCP project starts from the same "create a project" flow; pick the existing project instead of typing a new name. **Authentication → Get started** is a separate step. Without it, sign-in fails with `auth/configuration-not-found`. Authorized domains are under **Authentication → Settings**, not Project settings.
- **Firestore and rules** were created by `setup_gcp.sh`: native `(default)` in `us-central1`, and the deny-all ruleset released through the Firebase Rules REST API. The real `FirestoreSessionStore` was verified against the live database (create, upsert/regrow, abandon, end + count) with a throwaway patient that was then deleted. `turn_count` is cast to `int`, because the count aggregation returns a float.
- **First real session (27 lines)** showed why both transcripts are kept: Gemini's caption read *"אני **לא יכול** לסיים את השיחה"* ("I **can't** end the conversation") while the browser recognizer had *"נראה לי **אפשר** לסיים"* ("I think we **can** end"), which is the opposite meaning. The tutor still answered correctly, because she hears the audio and not the caption. Memory analysis (04) should weigh both versions.
- **Deploy bug:** `deploy.sh` silently exited when an optional `.env` key (`PATIENT_ID`) was absent. `grep` returns no match → with `pipefail` + `set -e` the script aborts, without printing anything. The `dotenv` helper now ends with `|| true`.
- **Remote verified** (revision 00009): no token → 401, forged token → 401, the Firebase config is served, and the env vars come from `.env`.
- **Not yet checked by hand:** the Rules Playground check, Dad's own account on his tablet, and a tab-close → `abandoned` run in a real browser. That last one is unit-tested and verified against Firestore directly.
- **Transcript viewer:** deferred to the caregiver page (08). For now, use the Firestore console.
