# Sub-plan 15: New accounts, each with its own profile

Part of the [master design](00-master-design.md). After [14](14-sequencing-stories.md), before [15.5](15.5-first-sessions-needs-check.md). Requested by Tomer (2026-10-13); reworked 2026-10-15 (a stored profile per account instead of a mapping in `.env`). **Built 2026-10-15.**

## Why
- **Someone new wants to try the app.** Adding an email to `ALLOWED_EMAILS` (and deploying) lets them sign in, and their sessions, memory and plans are already their own (`patient_id_for` keys everything by email).
- **But one thing was shared: the patient profile.** There was a single profile for every account (`PATIENT_PROFILE_URI`, one private file). A new account would have got the patient's profile text in the tutor's prompt, the memory agent and the plan builder, and any names on its `Vocabulary:` lines in the transcription vocabulary.
- **The prompts assumed the patient** in a few places: the tutor's role ("a man of about 70 who recently had a stroke"), and the memory agent, plan builder and research agent ("a man recovering from a stroke").

## Goal
1. **Every account has its own profile, or none.** Nothing of one account's profile reaches another.
2. **The family uploads it** on the caregiver page. For accounts without one, the app infers it in [15.5](15.5-first-sessions-needs-check.md).
3. **The patient's sessions are unchanged.**

## Design

### A. A stored profile per account
- **Kept with the account's data** (Firestore `patients/{pid}/caregiver/profile`, private, next to the planner notes): `{text, source, updated_by, updated_at}`.
- **`source`:** `uploaded` (the family, on the caregiver page) or `inferred` (the app, 15.5). The app never overwrites an uploaded profile; a family edit of an inferred one makes it uploaded.
- **`account_profile(store, pid)`** is the only way to read it. Every caller passes the account: session start (prompt + vocabulary), `/end`, the sweep, the caregiver page (overview, prompt view, process, rebuild).
- **No profile -> none.** The tutor is told she is still getting to know him.
- No configuration: the old `PATIENT_PROFILE_URI` is gone. Adding an account is `ALLOWED_EMAILS` only.

### B. The caregiver page
- **A "his profile" card:** the text, where it came from and when; edit it, paste it, or load a text file; save. Up to 8,000 characters (it goes into every prompt). The previous version is backed up to the private bucket on every save.
- A `Vocabulary:` line (names separated by commas) still feeds the transcription vocabulary.
- The new account's sessions show on the caregiver page to everyone in `CAREGIVER_EMAILS`, like the other accounts (noted in the README). No games link unless he is in `SIMON_PROFILES` (already so).

### C. Prompts that assumed the patient
- The tutor's role keeps only what is true for anyone; who he is and what affects his speech come from his profile. **The patient's prompt was compared before and after: only the role sentence changed** (his profile states his age and the stroke).
- The memory agent, plan builder and research agent: "a man practicing his spoken Hebrew", with the profile giving the rest.
- **Gender:** the prompts speak to him in the masculine. Out of scope for now; noted for later.

### D. Moving the existing profile
- The private file was copied once into the patient's account and Tomer's test account (`uploaded`, "migration from the private bucket"). The file stays in the bucket as a backup.

## What was built (2026-10-15)
- `app/patient_profile.py`: `account_profile`, `PROFILE_MAX_CHARS`; the shared loader and its setting are gone. `app/store.py`: `get_profile` / `save_profile`.
- `app/caregiver_api.py`: the profile in the overview; `PUT /{email}/profile` (caregivers only, with a backup). `static/caregiver.*`: the card.
- Prompts: tutor 3.3, memory update 0.8, plan builder 0.19, research 0.4.
- `deploy/deploy.sh` no longer passes a profile setting.
- Found while building: the profile had no `Vocabulary:` lines, so what was shared was the profile text (his names reach the transcription through his own plans, which never left his account).
- First built with a mapping in `.env` and a "learned profile" kept in the memory; reworked the same day: the mapping became the stored profile, and the learned profile moved to 15.5 (the inferred profile).
- Tests: `test_patient_profile.py`. `pytest`: 278 passed.

## Done when
- [x] A new account gets no profile and none of the patient's names in its vocabulary or prompt (tested).
- [x] The family can upload and edit a profile on the caregiver page.
- [x] The patient's and Tomer's sessions are unchanged (the prompt diff above; the profile migrated).
- [x] `pytest` passes.

## Commit
`Sub-plan 15: new accounts, each with its own profile`
