#!/usr/bin/env bash
# The observability dashboard (sub-plan 19): log-based metrics from the app's structured log lines
# (one per model call: model, job, latency, tokens, cost; one per live session; one per response
# time), and a Cloud Monitoring dashboard over them. Idempotent: run again after changing them.
# The metrics count from their creation on (not backwards).
set -euo pipefail
cd "$(dirname "$0")/.."

gcv() { gcloud "$@" | tr -d '\r'; }
PROJECT_ID="$(gcv config get-value project 2>/dev/null)"

echo ">> Log-based metrics..."
for FILE in deploy/monitoring/metrics/*.yaml; do
  NAME="$(basename "$FILE" .yaml)"
  if gcloud logging metrics describe "$NAME" >/dev/null 2>&1; then
    gcloud logging metrics update "$NAME" --config-from-file "$FILE" >/dev/null
    echo "   updated $NAME"
  else
    gcloud logging metrics create "$NAME" --config-from-file "$FILE" >/dev/null
    echo "   created $NAME"
  fi
done

echo ">> Dashboard..."
TITLE="$(python -c "import json; print(json.load(open('deploy/monitoring/dashboard.json'))['displayName'])")"
gcv monitoring dashboards list --format='value(name,displayName)' | while IFS=$'\t' read -r OLD NAME; do
  [[ "$NAME" == "$TITLE" ]] && gcloud monitoring dashboards delete "$OLD" --quiet >/dev/null
done || true
gcloud monitoring dashboards create --config-from-file deploy/monitoring/dashboard.json >/dev/null
echo ">> Done: https://console.cloud.google.com/monitoring/dashboards?project=${PROJECT_ID}"
