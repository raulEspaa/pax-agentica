#!/usr/bin/env bash
# Make the BigQuery dataset and the external tables over the analytics events the tables server
# writes to its bucket (see docs/analytics.md). Idempotent: run it again after changing a schema
# in scripts/bigquery/*.json, and the tables are replaced (the files in the bucket are untouched).
#
#   scripts/bigquery_setup.sh       # GCP_PROJECT, LOCATION and BUCKET default to the live service
#
# Needs bq (part of the gcloud SDK), logged in as someone who may create datasets and tables in
# the project (roles/bigquery.admin, or dataEditor + jobUser) and read the bucket. The server
# itself needs nothing new: it only writes files to the bucket, as before.
set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-pax-agentica-261016}"
LOCATION="${LOCATION:-europe-west1}"  # the bucket's region: a dataset reads only colocated files
BUCKET="${BUCKET:-$GCP_PROJECT-tables}"
DATASET="${DATASET:-pax_analytics}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if ! bq --project_id="$GCP_PROJECT" show --dataset "$GCP_PROJECT:$DATASET" >/dev/null 2>&1; then
  bq --project_id="$GCP_PROJECT" --location="$LOCATION" mk --dataset \
    --description "Pax Agentica: games, AI decisions and audiences, read from gs://$BUCKET/analytics" \
    "$GCP_PROJECT:$DATASET"
fi

ddl="$(python3 "$HERE/bigquery_ddl.py" --project "$GCP_PROJECT" --dataset "$DATASET" --bucket "$BUCKET")"
bq --project_id="$GCP_PROJECT" --location="$LOCATION" query --nouse_legacy_sql "$ddl"

echo "Tables in $GCP_PROJECT:$DATASET:"
bq --project_id="$GCP_PROJECT" ls "$GCP_PROJECT:$DATASET"
