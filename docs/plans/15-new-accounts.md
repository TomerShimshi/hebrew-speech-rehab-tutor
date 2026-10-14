# Sub-plan 15: New accounts, with a profile and vocabulary the app learns

Part of the [master design](00-master-design.md). After [14](14-sequencing-stories.md), before [16](16-names-goodbyes-and-excluded-sessions.md). Requested by Tomer (2026-10-13). **To build after 14 is finished.**

## Why
- **Someone new wants to try the app.** Adding an email to `ALLOWED_EMAILS` (and deploying) lets them sign in, and their sessions, memory and plans are already their own (`patient_id_for` keys everything by email).
- **But one thing is shared: the patient profile.** There is a single profile for every account (`PATIENT_PROFILE_URI`, one private file). A new account would get:
  - **the patient's vocabulary** (the `Vocabulary:` lines): his names and places, sent to Gemini's transcription as `custom_vocabulary`. This matters most: it biases what the new user's speech is heard as, toward someone else's names, and it puts those names into another person's sessions.
  - the patient's profile text in the tutor's prompt, the memory agent and the plan builder (who he is, what to practice, his history).
- **The prompts assume the patient** in a few places: the tutor's role ("a man of about 70 who recently had a stroke"), and the memory agent, plan builder and research agent ("a man recovering from a stroke").

## Goal
1. **Every account has its own profile, or none.** The patient profile goes only to the accounts it belongs to (the patient, and Tomer's test account).
2. **A new account starts with no profile and no vocabulary**, and the app fills both in by itself from his conversations.
3. **Nothing about the patient reaches another account**: not his names, not his profile.

## Design

### A. Which profile an account gets
- **A mapping in `.env`** (never the repo), like `SIMON_PROFILES`: `PATIENT_PROFILES="<email>=gs://.../patient_profile.md,<email>=gs://.../patient_profile.md"`. The deploy script passes it to Cloud Run.
- **An account not in the mapping has no written profile.** No fallback to the shared file: the old single `PATIENT_PROFILE_URI` is removed (or kept only as the default for the mapped accounts during the move).
- `PatientProfileLoader` becomes per account: `get(pid)`, a small cache per file (same 5-minute TTL).
- Every caller passes the account: session start (prompt + vocabulary), the memory update, the plan builder, the research agent, the caregiver page's prompt view.

### B. A profile the app learns (accounts without a written one)
- **The intro plan already gets to know him** (`intro_plan.yaml`: who he is, his family, places, interests). Its answers go into the memory sections today.
- **A learned profile, kept with the memory** (Firestore, per account), written by the memory agent:
  - **About him:** a few neutral lines (age range if he said, what he does or did, family, places, interests, how he speaks). Built from what he said, never guessed.
  - **His vocabulary:** names and places from his own talk (people, places, brands) -- the same kind of list as the profile's `Vocabulary:` lines. From `own_names` (12) and the memory's names, de-duplicated, capped (~40), most recent first.
- **One memory tool,** `update_profile` (about-him lines; vocabulary add/remove), so the agent changes it in small checked steps like the rest of the memory. Code caps the length and drops duplicates.
- **Session start:** `patient_profile` = the written profile if mapped, else the learned one; vocabulary = the written profile's list, else the learned list (plus today's plan names, as now).
- **The caregiver page shows it** (read-only at first, with the existing "remove" ✕ on vocabulary items), so the family can see what the app thinks it knows.

### C. Prompts that assume the patient
- The tutor's role: the stroke and the age move out of `role` into the profile. `role` keeps only what is true for anyone ("a speech-practice partner"); a mapped profile says the rest, as it does now. The patient's prompt must come out the same in substance -- check with the caregiver page's prompt view before and after.
- The memory agent, plan builder and research agent: "the person practicing" instead of "a man recovering from a stroke", with the profile (written or learned) giving the context.
- **Gender:** the prompts speak to him in the masculine. Out of scope for now (both current accounts are men); noted for later.

### D. Adding an account
- Still by `.env` + deploy (`ALLOWED_EMAILS`, and `PATIENT_PROFILES` only for a patient with a written profile). Moving the list to the caregiver page is out of scope.
- The new account's sessions show on the caregiver page to everyone in `CAREGIVER_EMAILS`, like the other accounts. Fine for a relative trying the app; noted in the README.
- No games link unless he is in `SIMON_PROFILES` (already so).

## Files
| File | Purpose |
|---|---|
| `app/config.py`, `deploy/deploy.sh` | `PATIENT_PROFILES` (email -> file), from `.env`. |
| `app/patient_profile.py`, `app/deps.py` | A loader per account; no shared fallback. |
| `app/main.py`, `app/session_prompt.py`, `app/caregiver_api.py` | Pass the account; the written or learned profile and vocabulary. |
| `app/agent/memory_tools.py`, `app/agent/memory_update.py`, `prompts/memory_update.yaml` | The learned profile and `update_profile`. |
| `app/agent/next_class.py`, `app/agent/research.py` | The account's profile. |
| `prompts/tutor.yaml`, `prompts/next_class.yaml`, `prompts/research_agent.yaml` | Neutral wording; the patient specifics come from his profile. |
| `static/caregiver.*` | The learned profile and vocabulary, with ✕ on vocabulary items. |
| `tests/` | An unmapped account gets no profile and none of the patient's vocabulary; a mapped one gets its file; the learned profile grows from a session and feeds the next one; the patient's prompt is unchanged in substance. |

## Done when
- [ ] A new account signs in and gets no written profile and none of the patient's names in its vocabulary or prompt.
- [ ] After his first sessions, his own names and a short profile appear (caregiver page) and are used in the next session.
- [ ] The patient's and Tomer's sessions are unchanged.
- [ ] `pytest` passes.

## Commit
`Sub-plan 15: new accounts, with a profile and vocabulary the app learns`
