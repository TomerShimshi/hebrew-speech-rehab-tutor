#!/usr/bin/env bash
# One-time GCP setup. Safe to re-run.
#
# Usage:
#   PROJECT_ID=my-project [REGION=us-central1] [BUDGET_AMOUNT=<n>] [KILLSWITCH_DRY_RUN=false] \
#     ./deploy/setup_gcp.sh
#
# Prerequisite: billing is linked to the project (the script checks).
# The budget is set in the billing account's currency (GCP requires that):
# defaults are 1 USD or 4 ILS (~1 USD); other currencies need BUDGET_AMOUNT.
# The Gemini API key is taken from GEMINI_API_KEY in the local .env file; if
# it's not there you're prompted for it (hidden input, never in shell history).
set -euo pipefail

# gcloud on Windows ends output lines with CRLF; captured values must not keep the
# carriage return (it silently breaks comparisons -- e.g. treating the live revision
# as an old one).
gcv() { gcloud "$@" | tr -d '\r'; }

: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
KILLSWITCH_DRY_RUN="${KILLSWITCH_DRY_RUN:-false}"
SECRET_NAME="gemini-api-key"
BUDGET_NAME="hebrew-tutor-budget"
TOPIC="budget-alerts"
KILLSWITCH_FN="budget-killswitch"
KILLSWITCH_SA_NAME="budget-killswitch"
KILLSWITCH_SA="${KILLSWITCH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."

gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

echo ">> Checking billing..."
BILLING_ACCOUNT="$(gcv billing projects describe "$PROJECT_ID" --format='value(billingAccountName)')"
BILLING_ACCOUNT="${BILLING_ACCOUNT#billingAccounts/}"
if [[ -z "$BILLING_ACCOUNT" ]]; then
  echo "!! Billing is not linked to $PROJECT_ID."
  echo "   Link it: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
  exit 1
fi
CURRENCY="$(gcv billing accounts describe "$BILLING_ACCOUNT" --format='value(currencyCode)')"
if [[ -z "${BUDGET_AMOUNT:-}" ]]; then
  case "$CURRENCY" in
    USD) BUDGET_AMOUNT=1 ;;
    ILS) BUDGET_AMOUNT=4 ;;
    *) echo "!! Billing currency is $CURRENCY -- set BUDGET_AMOUNT (about 1 USD) and re-run"; exit 1 ;;
  esac
fi
echo "   billing account: $BILLING_ACCOUNT (budget: ${BUDGET_AMOUNT} ${CURRENCY})"

echo ">> Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  billingbudgets.googleapis.com \
  cloudbilling.googleapis.com \
  cloudresourcemanager.googleapis.com \
  pubsub.googleapis.com \
  cloudfunctions.googleapis.com \
  eventarc.googleapis.com \
  storage.googleapis.com \
  firestore.googleapis.com \
  firebaserules.googleapis.com \
  identitytoolkit.googleapis.com \
  firebase.googleapis.com \
  cloudscheduler.googleapis.com

echo ">> Gemini API key secret..."
if ! gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET_NAME" --replication-policy=automatic
fi
GEMINI_KEY=""
if [[ -f .env ]]; then
  # Last GEMINI_API_KEY= line; strip Windows CR and surrounding quotes.
  GEMINI_KEY="$(grep -E '^[[:space:]]*GEMINI_API_KEY[[:space:]]*=' .env | tail -n1 | cut -d= -f2- \
    | tr -d '\r' | sed -E "s/^[[:space:]]*[\"']?//; s/[\"']?[[:space:]]*\$//")" || true
fi
if [[ -n "$GEMINI_KEY" ]]; then
  echo "   using GEMINI_API_KEY from .env"
else
  read -r -s -p "Paste the Gemini API key from AI Studio (leave empty to keep the current version): " GEMINI_KEY
  echo
fi
if [[ -n "$GEMINI_KEY" ]]; then
  CURRENT_KEY="$(gcv secrets versions access latest --secret="$SECRET_NAME" 2>/dev/null || true)"
  if [[ "$GEMINI_KEY" == "$CURRENT_KEY" ]]; then
    echo "   secret already up to date"
  else
    printf '%s' "$GEMINI_KEY" | gcloud secrets versions add "$SECRET_NAME" --data-file=-
  fi
  unset CURRENT_KEY
fi
unset GEMINI_KEY

echo ">> Granting Cloud Run's runtime service account access to the secret..."
PROJECT_NUMBER="$(gcv projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

# ---------------------------------------------------------------------------
# The Simon games app (sub-plan 06): Upstash URL + READ-ONLY token, from .env.
# The read-only token means this app physically cannot change Simon's data.
# ---------------------------------------------------------------------------
dotenv_value() {
  [[ -f .env ]] || return 0
  grep -E "^[[:space:]]*$1[[:space:]]*=" .env | tail -n1 | cut -d= -f2- \
    | tr -d '\r' | sed -E "s/^[[:space:]]*[\"']?//; s/[\"']?[[:space:]]*\$//" || true
}
put_secret() {  # put_secret <secret-name> <value>: create if missing, add a version only if changed
  local name="$1" value="$2"
  [[ -n "$value" ]] || { echo "   $name: no value in .env -- skipped"; return 0; }
  gcloud secrets describe "$name" >/dev/null 2>&1 || gcloud secrets create "$name" --replication-policy=automatic >/dev/null
  if [[ "$value" == "$(gcv secrets versions access latest --secret="$name" 2>/dev/null || true)" ]]; then
    echo "   $name: up to date"
  else
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null && echo "   $name: updated"
  fi
  gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" >/dev/null
}
echo ">> Simon games app secrets (Upstash, read-only)..."
put_secret upstash-url "$(dotenv_value UPSTASH_REDIS_REST_URL)"
put_secret upstash-readonly-token "$(dotenv_value UPSTASH_REDIS_READONLY_TOKEN)"

# ---------------------------------------------------------------------------
# Firestore: sessions + transcripts. Only the backend's service account touches it
# (IAM); client access is denied by firestore.rules.
# ---------------------------------------------------------------------------
echo ">> Firestore database..."
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native
fi
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/datastore.user" --condition=None >/dev/null

echo ">> Firestore security rules (deny all client access)..."
TOKEN="$(gcv auth print-access-token)"
RULES_JSON="$(python -c 'import json,sys; print(json.dumps({"source": {"files": [{"name": "firestore.rules", "content": open("firestore.rules", encoding="utf-8").read()}]}}))')"
RULESET="$(curl -fsS -X POST "https://firebaserules.googleapis.com/v1/projects/${PROJECT_ID}/rulesets" \
  -H "Authorization: Bearer ${TOKEN}" -H "x-goog-user-project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" -d "$RULES_JSON" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
RELEASE="projects/${PROJECT_ID}/releases/cloud.firestore"
RELEASE_BODY="{\"release\": {\"name\": \"${RELEASE}\", \"rulesetName\": \"${RULESET}\"}}"
if ! curl -fsS -X PATCH "https://firebaserules.googleapis.com/v1/${RELEASE}" \
    -H "Authorization: Bearer ${TOKEN}" -H "x-goog-user-project: ${PROJECT_ID}" \
    -H "Content-Type: application/json" -d "$RELEASE_BODY" >/dev/null 2>&1; then
  # First time: the release doesn't exist yet.
  curl -fsS -X POST "https://firebaserules.googleapis.com/v1/projects/${PROJECT_ID}/releases" \
    -H "Authorization: Bearer ${TOKEN}" -H "x-goog-user-project: ${PROJECT_ID}" \
    -H "Content-Type: application/json" -d "{\"name\": \"${RELEASE}\", \"rulesetName\": \"${RULESET}\"}" >/dev/null
fi
echo "   released $RULESET"
unset TOKEN

# Private, de-identified patient profile: kept out of git and the image (the repo is
# public). Its home is a private bucket only the app's service account can read; the
# app reads it directly (PATIENT_PROFILE_URI, see deploy.sh). Re-run to upload edits.
PRIVATE_BUCKET="gs://${PROJECT_ID}-private"
PROFILE_FILE="prompts/patient_profile.local.md"
PROFILE_OBJECT="${PRIVATE_BUCKET}/patient_profile.md"
echo ">> Private bucket for the patient profile..."
if ! gcloud storage buckets describe "$PRIVATE_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "$PRIVATE_BUCKET" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
gcloud storage buckets add-iam-policy-binding "$PRIVATE_BUCKET" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectViewer" >/dev/null
# The app also archives each session's tutor prompt under debug/ (for debugging).
# objectCreator can CREATE objects only -- it can't overwrite or delete (e.g. the profile).
gcloud storage buckets add-iam-policy-binding "$PRIVATE_BUCKET" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectCreator" >/dev/null
# Debug files expire after 30 days.
gcloud storage buckets update "$PRIVATE_BUCKET" --lifecycle-file=deploy/private-bucket-lifecycle.json >/dev/null
if [[ -f "$PROFILE_FILE" ]]; then
  tr -d '\r' < "$PROFILE_FILE" | gcloud storage cp - "$PROFILE_OBJECT" --content-type="text/markdown; charset=utf-8"
  echo "   uploaded $PROFILE_FILE -> $PROFILE_OBJECT"
  echo "   (you may now delete the local copy; local dev can read the bucket instead)"
elif gcloud storage objects describe "$PROFILE_OBJECT" >/dev/null 2>&1; then
  echo "   $PROFILE_OBJECT already in place (no local copy to upload)"
else
  echo "   no profile yet -- create $PROFILE_FILE and re-run to upload it"
fi

# ---------------------------------------------------------------------------
# Hourly memory sweep: Cloud Scheduler calls /internal/memory/sweep with a Google-signed
# OIDC token for a dedicated service account; the app accepts only that account. It
# updates memory for sessions still waiting (tab closed, or models were overloaded).
# Free: Cloud Scheduler includes 3 jobs; when nothing is pending, no Gemini call is made.
# ---------------------------------------------------------------------------
SWEEPER_SA="memory-sweeper@${PROJECT_ID}.iam.gserviceaccount.com"
echo ">> Memory sweep: service account + hourly job..."
if ! gcloud iam service-accounts describe "$SWEEPER_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create memory-sweeper --display-name="Hourly memory sweep (Cloud Scheduler)"
fi
SERVICE_URL="$(gcv run services describe hebrew-tutor --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
if [[ -z "$SERVICE_URL" ]]; then
  echo "   app not deployed yet -- run deploy.sh, then re-run this script to create the job"
else
  JOB_ARGS=(
    --location="$REGION"
    --schedule="0 * * * *"
    --time-zone="Asia/Jerusalem"
    --uri="${SERVICE_URL}/internal/memory/sweep"
    --http-method=POST
    --oidc-service-account-email="$SWEEPER_SA"
    --oidc-token-audience="$SERVICE_URL"
    --attempt-deadline=600s
  )
  if gcloud scheduler jobs describe memory-sweep --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http memory-sweep "${JOB_ARGS[@]}" >/dev/null
  else
    gcloud scheduler jobs create http memory-sweep "${JOB_ARGS[@]}" >/dev/null
  fi
  echo "   hourly job memory-sweep -> ${SERVICE_URL}/internal/memory/sweep"
fi

# ---------------------------------------------------------------------------
# Budget kill switch: budget -> Pub/Sub topic -> function that disables
# billing on this project once cost reaches the budget.
# ---------------------------------------------------------------------------
echo ">> Kill switch: Pub/Sub topic..."
gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"

echo ">> Kill switch: service account (may only read project/billing info, unlink billing, receive events)..."
if ! gcloud iam service-accounts describe "$KILLSWITCH_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$KILLSWITCH_SA_NAME" --display-name="Budget kill switch"
fi
# roles/browser: resourcemanager.projects.get, needed to read the project's billing info.
for ROLE in roles/browser roles/billing.projectManager roles/run.invoker roles/eventarc.eventReceiver; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${KILLSWITCH_SA}" --role="$ROLE" --condition=None >/dev/null
done

echo ">> Kill switch: deploying function (DRY_RUN=$KILLSWITCH_DRY_RUN)..."
gcloud functions deploy "$KILLSWITCH_FN" \
  --gen2 \
  --region "$REGION" \
  --runtime python312 \
  --source deploy/budget_killswitch \
  --entry-point stop_billing \
  --trigger-topic "$TOPIC" \
  --service-account "$KILLSWITCH_SA" \
  --trigger-service-account "$KILLSWITCH_SA" \
  --set-env-vars "PROJECT_ID=${PROJECT_ID},DRY_RUN=${KILLSWITCH_DRY_RUN}" \
  --memory 256Mi \
  --max-instances 1

echo ">> Budget (${BUDGET_AMOUNT} ${CURRENCY}) wired to the kill switch..."
# Match by display name in awk (gcloud's --filter warns on budgets and can't be trusted here).
BUDGET_ID="$(gcv billing budgets list --billing-account="$BILLING_ACCOUNT" \
  --format='value(name,displayName)' | awk -F'\t' -v n="$BUDGET_NAME" '$2 == n {print $1; exit}')"
TOPIC_PATH="projects/${PROJECT_ID}/topics/${TOPIC}"
if [[ -z "$BUDGET_ID" ]]; then
  gcloud billing budgets create \
    --billing-account="$BILLING_ACCOUNT" \
    --display-name="$BUDGET_NAME" \
    --budget-amount="${BUDGET_AMOUNT}${CURRENCY}" \
    --filter-projects="projects/${PROJECT_ID}" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 \
    --notifications-rule-pubsub-topic="$TOPIC_PATH"
else
  gcloud billing budgets update "$BUDGET_ID" \
    --billing-account="$BILLING_ACCOUNT" \
    --budget-amount="${BUDGET_AMOUNT}${CURRENCY}" \
    --notifications-rule-pubsub-topic="$TOPIC_PATH"
fi

echo ">> Done. Next: ./deploy/deploy.sh"
