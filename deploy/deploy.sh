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

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars "PATIENT_PROFILE_URI=${PROFILE_URI}" \
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
