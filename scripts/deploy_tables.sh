#!/usr/bin/env bash
# Deploy the multiplayer tables (pax host) to Cloud Run, with the tables kept in a Cloud Storage
# bucket mounted at /data. One instance only: the games live in its memory between saves.
#
#   GCP_PROJECT=my-project PAX_INVITE_CODE=... scripts/deploy_tables.sh
#
# Optional: REGION (europe-west1), SERVICE (pax-tables), BUCKET (<project>-pax-tables).
set -euo pipefail

: "${GCP_PROJECT:?set GCP_PROJECT to the Google Cloud project to deploy to}"
: "${PAX_INVITE_CODE:?set PAX_INVITE_CODE: the code friends need to open a table or take a seat}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-pax-tables}"
BUCKET="${BUCKET:-${GCP_PROJECT}-pax-tables}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit first: the deployed image is built from this working tree." >&2
  exit 1
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com --project "$GCP_PROJECT"

if ! gcloud storage buckets describe "gs://$BUCKET" --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" --project "$GCP_PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi

NUMBER="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')"
RUNNER="${NUMBER}-compute@developer.gserviceaccount.com"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$GCP_PROJECT" \
  --member "serviceAccount:$RUNNER" --role roles/storage.objectUser >/dev/null

gcloud run deploy "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --source . \
  --execution-environment gen2 \
  --add-volume "name=tables,type=cloud-storage,bucket=$BUCKET" \
  --add-volume-mount "volume=tables,mount-path=/data" \
  --max-instances 1 --min-instances 0 --concurrency 80 --cpu 1 --memory 512Mi \
  --allow-unauthenticated \
  --set-env-vars "PAX_INVITE_CODE=$PAX_INVITE_CODE" \
  --labels "app=pax-agentica,commit=$(git rev-parse --short HEAD)"

gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" \
  --format 'value(status.url)'
