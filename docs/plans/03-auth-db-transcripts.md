# Sub-plan 03: Login, Firestore and saved transcripts

Part of the [master design](00-master-design.md). Depends on [02](02-voice-agent-v0.md).

## Goal
Only allowlisted Google accounts can use the app. Every session and its **full transcript are written deterministically**, by our Python code with no LLM involved, to Firestore.

## Out of scope
Memory and LLM post-processing (04), the caregiver UI (08), audio recording (09).

## Files
| File | Purpose |
|---|---|
| `app/auth.py` | Verifies Firebase ID tokens with `firebase-admin`. A `require_user` dependency checks `ALLOWED_EMAILS`, and `require_caregiver` checks `CAREGIVER_EMAILS` (the second is used in 08). |
| `app/memory_store.py` | A `Store` Protocol with `FirestoreStore` and `InMemoryStore` (for tests). For now: `ensure_patient`, `create_session`, `append_turns`, `end_session`, `list_turns`. |
| `app/transcripts.py` | Validates turns (`seq`, `speaker: patient\|tutor`, `text`, `ts`) and makes writes idempotent: the doc id is `seq`, so a retried flush never duplicates a turn. |
| `app/main.py` | Every `/api/*` route requires a signed-in user. `POST /api/session/start` now creates `patients/abba/sessions/{id}` (status `active`, `prompt_version`). Adds `POST /api/session/{id}/turns` and `POST /api/session/{id}/end` (status `ended`). |
| `static/app.js` | Firebase Auth Google sign-in (Firebase JS SDK from gstatic, login persists on the device). It collects input and output transcription turns, flushes them every ~10 s, on end, and on `pagehide` (`fetch` with `keepalive`). |
| `firestore.rules` | `allow read, write: if false;`. Only the backend service account can access the data. |
| `deploy/setup_gcp.sh` | Adds: enable Firestore (native, `(default)`, us-central1), Firebase on the project with the Google provider, and IAM `datastore.user` for the runtime service account. |
| `deploy/deploy.sh` | Adds env vars `ALLOWED_EMAILS`, `CAREGIVER_EMAILS` and the Firebase web config (public values). |
| `tests/test_auth.py`, `tests/test_transcripts.py`, `tests/test_api_sessions.py` | Allowlist accept/reject, idempotent and ordered turns, and the full start → turns → end flow on `InMemoryStore`. |

## Manual steps for Tomer
- In the Firebase console, add Firebase to the GCP project, enable Authentication → Google, and add the Cloud Run domain to the authorized domains.
- Decide the allowlist emails: Dad's Google account and Tomer's.

## Done when
- [ ] `pytest` passes.
- [ ] Signing in with a non-allowlisted account gets a 403 and a friendly Hebrew message.
- [ ] After a real session, `sessions/{id}/turns` in Firestore holds the full transcript in order, with nothing missing or duplicated.
- [ ] Closing the tab mid-session still saves everything except the last few seconds.
- [ ] Firestore rules deny direct client access (tested in the rules playground).

## Commit
`Sub-plan 03: Google sign-in allowlist, Firestore sessions and deterministic transcripts`
