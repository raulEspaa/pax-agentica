# Deployment

The multiplayer tables (`pax host`) run on **Cloud Run** in the Google Cloud project
`pax-agentica-261016` (region `europe-west1`), and every push to `main` that passes CI goes live
by itself.

## Continuous deployment

The `deploy` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs after the
lint, type, test and secret-scan jobs pass on a push to `main`:

1. GitHub gives the job an OIDC token; **Workload Identity Federation** exchanges it for a
   short-lived credential of the `pax-deployer` service account. No key is stored in GitHub or
   anywhere else, and the pool only trusts `raulEspaa/pax-agentica` on `refs/heads/main`.
2. The [`Dockerfile`](../Dockerfile) is built and pushed to Artifact Registry
   (`europe-west1-docker.pkg.dev/pax-agentica-261016/pax/pax-tables:<commit>`).
3. `gcloud run deploy` rolls the new image out to the `pax-tables` service.
4. A smoke test calls `/api/health` (Cloud Run keeps `/healthz` for itself) and `/api/lobby`; the job summary prints the URL.

The job reads four repository **variables** (not secrets): `GCP_PROJECT`, `GCP_REGION`,
`GCP_WIF_PROVIDER` and `GCP_DEPLOYER`.

## What runs

| Piece | Setting |
|---|---|
| Service | `pax-tables`, public, at most **one instance** (games live in its memory), scale to zero |
| Runtime account | `pax-runtime`: may read the invitation code and write the tables bucket, nothing else |
| Tables | bucket `pax-agentica-261016-tables`, mounted at `/data`; one JSON file per table, written after every year |
| Invitation code | Secret Manager `pax-invite-code`, given to the service as `PAX_INVITE_CODE` |
| Budget | an alert at 50%, 90% and 100% of 10 EUR a month |

Tables close by themselves when their last player leaves, after three days without anyone
playing, or once the game is over; a closed table keeps its replay for a week, then its files
are deleted. The server keeps only a summary of each table in memory and reads a game when
someone opens it (lets it go again after fifteen minutes unvisited), so a cold start is quick
and memory stays small; one 50-year game takes about 24 MB, its save about 2 MB.

During a roll-out the old and the new revision run side by side for a few seconds; a table is
read again from its save whenever another revision has written it since, so no year is lost.

## Common tasks

```bash
# the public address
gcloud run services describe pax-tables --project pax-agentica-261016 --region europe-west1 --format 'value(status.url)'

# the invitation code to give your friends
gcloud secrets versions access latest --secret pax-invite-code --project pax-agentica-261016

# a new invitation code (takes effect on the next deploy, or force one by re-running the job)
python3 -c "import secrets; print(secrets.token_urlsafe(9), end='')" | gcloud secrets versions add pax-invite-code --project pax-agentica-261016 --data-file=-

# the server's logs
gcloud run services logs read pax-tables --project pax-agentica-261016 --region europe-west1 --limit 50

# the saved tables (and their small summaries)
gcloud storage ls gs://pax-agentica-261016-tables

# the testers' notes, newest last
gcloud storage cat "gs://pax-agentica-261016-tables/feedback/*.json"
```

## Setting it up again from nothing

The one-time setup, as it was done on 2026-10-16: create the project and link billing; enable
`run`, `artifactregistry`, `storage`, `secretmanager`, `iam`, `iamcredentials`, `sts` and
`billingbudgets`; create the Artifact Registry repository `pax`, the bucket, the secret and the
two service accounts; grant `pax-runtime` `storage.objectUser` on the bucket and
`secretmanager.secretAccessor` on the secret, and `pax-deployer` `run.admin` on the project,
`artifactregistry.writer` on the repository and `iam.serviceAccountUser` on `pax-runtime`;
create the workload identity pool `github` with an OIDC provider for
`https://token.actions.githubusercontent.com` restricted to this repository's `main`, and let
that principal set impersonate `pax-deployer` (`iam.workloadIdentityUser`); set the four
repository variables. [`scripts/deploy_tables.sh`](../scripts/deploy_tables.sh) deploys the same
service by hand, from this machine, if GitHub Actions is ever unavailable.
