#!/usr/bin/env bash
# Deploy the multiplayer tables (pax host) to Cloud Run by hand, from this working tree. The
# usual path is automatic: every push to main that passes CI deploys (see docs/deploy.md).
# This does the same with Cloud Build, for when GitHub Actions is unavailable.
#
#   scripts/deploy_tables.sh            # GCP_PROJECT and REGION default to the live service
set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-pax-agentica-261016}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-pax-tables}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit first: the deployed image is built from this working tree." >&2
  exit 1
fi

gcloud run deploy "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --source . \
  --service-account "pax-runtime@$GCP_PROJECT.iam.gserviceaccount.com" \
  --execution-environment gen2 \
  --add-volume "name=tables,type=cloud-storage,bucket=$GCP_PROJECT-tables" \
  --add-volume-mount "volume=tables,mount-path=/data" \
  --set-secrets "PAX_INVITE_CODE=pax-invite-code:latest" \
  --max-instances 1 --min-instances 0 --concurrency 80 --cpu 1 --memory 512Mi \
  --allow-unauthenticated \
  --labels "app=pax-agentica,commit=$(git rev-parse --short HEAD)"

gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" \
  --format 'value(status.url)'
