#!/usr/bin/env bash
# Build from source (Cloud Build) and deploy to Cloud Run.
# Scale-to-zero + a single max instance keeps this inside the free tier.
set -euo pipefail

# gcloud on Windows ends output lines with CRLF; captured values must not keep the
# carriage return (it silently breaks comparisons -- e.g. treating the live revision
# as an old one).
gcv() { gcloud "$@" | tr -d '\r'; }

REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-hebrew-tutor}"

cd "$(dirname "$0")/.."

# --allow-unauthenticated is temporary: Google sign-in + allowlist arrives in sub-plan 03.
PROJECT_ID="$(gcv config get-value project 2>/dev/null)"
# The app reads the private patient profile straight from its bucket (see setup_gcp.sh).
PROFILE_URI="gs://${PROJECT_ID}-private/patient_profile.md"

# Personal/deployment values come from the local .env -- never from the (public) repo.
dotenv() {
  [[ -f .env ]] || return 0
  grep -E "^[[:space:]]*$1[[:space:]]*=" .env | tail -n1 | cut -d= -f2- \
    | tr -d '\r' | sed -E "s/^[[:space:]]*[\"']?//; s/[\"']?[[:space:]]*\$//" || true
  # (|| true: a key missing from .env is just empty -- with pipefail, grep's "no match"
  #  would otherwise silently abort the whole script)
}
ALLOWED_EMAILS="$(dotenv ALLOWED_EMAILS)"
if [[ -z "$ALLOWED_EMAILS" ]]; then
  echo "!! ALLOWED_EMAILS is empty in .env -- nobody could sign in. Aborting."
  exit 1
fi
# '^|^' switches gcloud's list delimiter to '|', because the email lists contain commas.
ENV_VARS="^|^PATIENT_PROFILE_URI=${PROFILE_URI}"
ENV_VARS+="|GCP_PROJECT_ID=${PROJECT_ID}"
ENV_VARS+="|ALLOWED_EMAILS=${ALLOWED_EMAILS}"
ENV_VARS+="|CAREGIVER_EMAILS=$(dotenv CAREGIVER_EMAILS)"
ENV_VARS+="|PATIENT_ID=$(dotenv PATIENT_ID)"
ENV_VARS+="|FIREBASE_API_KEY=$(dotenv FIREBASE_API_KEY)"
ENV_VARS+="|FIREBASE_AUTH_DOMAIN=$(dotenv FIREBASE_AUTH_DOMAIN)"
ENV_VARS+="|FIREBASE_APP_ID=$(dotenv FIREBASE_APP_ID)"
ENV_VARS="${ENV_VARS//|PATIENT_ID=|/|}"  # empty PATIENT_ID -> the app's default

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars "$ENV_VARS" \
  --allow-unauthenticated

URL="$(gcv run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo ">> Deployed: $URL"
echo ">> Health:   $(curl -fsS "$URL/api/health" || echo 'health check failed')"

# ---------------------------------------------------------------------------
# Keep only what's live -- git is the history. Everything below is idempotent
# and best-effort: a cleanup failure never fails the deploy.
# ---------------------------------------------------------------------------
echo ">> Cleanup: deleting old Cloud Run revisions..."
LATEST="$(gcv run services describe "$SERVICE" --region "$REGION" \
  --format='value(status.latestReadyRevisionName)')"
for REV in $(gcv run revisions list --service "$SERVICE" --region "$REGION" \
    --format='value(metadata.name)'); do
  if [[ "$REV" != "$LATEST" ]]; then
    gcloud run revisions delete "$REV" --region "$REGION" --quiet || true
  fi
done

# Artifact Registry deletes per policy on its own schedule (about daily), not instantly.
echo ">> Cleanup: image repos keep only the newest image per app..."
for REPO in cloud-run-source-deploy gcf-artifacts; do
  if gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1; then
    gcloud artifacts repositories set-cleanup-policies "$REPO" \
      --location "$REGION" \
      --policy deploy/artifact-cleanup-policy.json \
      --no-dry-run >/dev/null || true
  fi
done

echo ">> Cleanup: uploaded source archives expire after 1 day..."
SOURCE_BUCKET="gs://run-sources-${PROJECT_ID}-${REGION}"
if gcloud storage buckets describe "$SOURCE_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets update "$SOURCE_BUCKET" \
    --lifecycle-file deploy/source-bucket-lifecycle.json >/dev/null || true
fi

echo ">> Done."
