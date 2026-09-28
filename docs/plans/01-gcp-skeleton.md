# Sub-plan 01: GCP skeleton web app

Part of the [master design](00-master-design.md).

## Goal
A minimal FastAPI web app deployed to **Cloud Run on the free tier**, with the Gemini API key stored in **Secret Manager** and mounted into the service. It has no voice, no database and no login yet. This sub-plan only proves the path from code to container to a live URL.

## Out of scope
Gemini calls, the Live API and audio (02), Firestore and auth (03), and everything from 04 onward.

## Files
| File | Purpose |
|---|---|
| `app/__init__.py` | package marker |
| `app/config.py` | `Settings` via `pydantic-settings`. For now only `GEMINI_API_KEY` (optional). It is loaded from env or `.env`. |
| `app/main.py` | FastAPI app. `GET /api/health` returns `{"status": "ok", "gemini_key_configured": bool}` and **never returns the key's value**. `static/` is served at `/`. |
| `static/index.html` | A right-to-left Hebrew page (`lang="he" dir="rtl"`) in large font for older eyes. It has a title and one big **"שנתחיל?"** button that isn't wired up yet (it shows "בקרוב…", "coming soon…"). |
| `tests/test_health.py` | Tests `/api/health` with and without the key, checks the key value never appears in the response, and checks that `/` serves the page. |
| `requirements.txt` | fastapi, uvicorn[standard], pydantic-settings |
| `requirements-dev.txt` | `-r requirements.txt`, pytest, httpx |
| `pytest.ini` | test paths |
| `Dockerfile` | `python:3.12-slim`, installs requirements, runs `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}` |
| `.dockerignore`, `.gitignore` | Exclude `.env`, venv, caches, `.git`. |
| `.env.example` | `GEMINI_API_KEY=` |
| `deploy/setup_gcp.sh` | One-time setup that is safe to re-run (see below). |
| `deploy/deploy.sh` | Build and deploy to Cloud Run. |
| `deploy/budget_killswitch/` | A Cloud Run function (Pub/Sub trigger) that **disables billing on the project** when budget cost ≥ budget amount. It supports `DRY_RUN`. |
| `tests/test_budget_killswitch.py` | Tests the disable decision against cost and budget. |
| `README.md` | What the app is, local run, tests, GCP setup and deploy, and a link to `docs/plans/`. |

### `deploy/setup_gcp.sh`
Inputs are environment variables: `PROJECT_ID` (required), `REGION` (default `us-central1`), `BUDGET_AMOUNT` (in the billing account's currency; defaults to 1 for USD or 4 for ILS, anything else must be set), `KILLSWITCH_DRY_RUN` (default false). The billing account is detected from the project, and the script stops if billing isn't linked. The script:
1. Runs `gcloud config set project $PROJECT_ID`.
2. Enables the APIs: `run`, `artifactregistry`, `cloudbuild`, `secretmanager`, `billingbudgets`, `cloudbilling`, `pubsub`, `cloudfunctions`, `eventarc`.
3. Creates the secret `gemini-api-key` if it's missing, then adds a version with the value read from stdin (`--data-file=-`), so the key never ends up in shell history.
4. Grants `roles/secretmanager.secretAccessor` on that secret to the default compute service account, which Cloud Run uses as its runtime identity.
5. **$1 kill switch** (added at Tomer's request: the POC must never cost more than about $1):
   - creates the `budget-alerts` Pub/Sub topic
   - creates the `budget-killswitch` service account with only `billing.projectManager`, `run.invoker` and `eventarc.eventReceiver`
   - deploys the function
   - creates or updates the **$1 budget** (email alerts at 50%, 90% and 100%) so that it publishes to the topic

   Budget data lags real usage by a few hours, so spend may end up slightly above $1.

### `deploy/deploy.sh`
```
gcloud run deploy hebrew-tutor --source . --region us-central1 \
  --min-instances 0 --max-instances 1 --memory 512Mi \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --allow-unauthenticated
```
`--allow-unauthenticated` is temporary. Google sign-in with an allowlist is added in sub-plan 03.

After each deploy the script **keeps only what's live** (Tomer's decision: git is the version history):
- deletes every Cloud Run revision except the one now serving
- sets an Artifact Registry cleanup policy on `cloud-run-source-deploy` and `gcf-artifacts` (`deploy/artifact-cleanup-policy.json`) that keeps only the newest image per app; GCP applies it about once a day
- sets a 1-day lifecycle on the `run-sources-*` bucket of uploaded source archives (`deploy/source-bucket-lifecycle.json`)

This also keeps storage well within the 0.5 GB Artifact Registry free tier.

## Tasks
1. [x] Delete the empty nested `hebrew-speech-rehab-tutor/` folder. The repo root is the single repo.
2. [x] Write the app, tests, Docker and deploy files above.
3. [x] `pip install -r requirements-dev.txt` → `pytest` → `uvicorn app.main:app --reload` → open http://localhost:8000.
4. [x] Check the gcloud CLI with `gcloud --version`. It was not installed on 2026-09-28, so install the Google Cloud SDK.
5. [x] Tomer does the manual steps below.
6. [x] Run `deploy/setup_gcp.sh`, then `deploy/deploy.sh`.
7. [x] Check the Cloud Run URL and `/api/health`.
8. [x] Commit and push.

## Manual steps for Tomer
1. Create a GCP project, e.g. `hebrew-tutor-<suffix>`, at https://console.cloud.google.com, and **link a billing account**. Cloud Run needs billing even when usage stays inside the free tier.
2. In **Google AI Studio** (https://aistudio.google.com/apikey), create an API key **in that project**.
3. Run `gcloud auth login` and `gcloud config set project <PROJECT_ID>`.
4. Link billing: Console → Billing → **Link a billing account** for the project (or create one; a new account starts as a Free Trial with $300 credit and is never charged unless you upgrade it).

## Done when
- [x] `pytest` passes locally (8 tests).
- [x] The page loads at `http://localhost:8000` and shows the button in Hebrew, laid out right to left.
- [x] The page loads at the Cloud Run URL (https://hebrew-tutor-279739778074.us-central1.run.app).
- [x] `GET <url>/api/health` returns `{"status":"ok","gemini_key_configured":true}`.
- [x] A $1 budget exists under Billing → Budgets & alerts and is connected to `budget-alerts`.
- [x] Dry-run test: publishing `{"costAmount": 2, "budgetAmount": 1}` logs "DRY_RUN: would disable billing". Then re-run setup without dry-run to arm it.

## Commit
`Sub-plan 01: FastAPI skeleton deployed to Cloud Run with Secret Manager`, then `git push origin main`.

## Notes from doing it
- Project: `heb-practice` (us-central1). Billing is in ILS, so the budget is 4 ILS (about $1).
- **Kill switch:** the first dry run found a missing permission. Reading billing info needs `resourcemanager.projects.get`, so the service account got `roles/browser`. The dry run now also checks the unlink permission through `testIamPermissions`. It is armed (`DRY_RUN=false`).
- **`/healthz` → `/api/health`:** Cloud Run reserves paths ending in `z` and returns its own 404 for them.
- **Windows gcloud output ends in CRLF.** The scripts capture values through `gcv()`, which strips the ``. Without it, the cleanup loop tried to delete the live revision (the attempt failed harmlessly).
- **The Gemini key** lives in a separate project with no billing (free tier). The Cloud Run project reads it from Secret Manager, and locally it comes from `.env`.
- **Deploy cleanup** keeps only what's live (see `deploy.sh`).
