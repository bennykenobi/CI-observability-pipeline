# Cloud Run Deployment

These commands assume:

- a GCP project already exists
- Artifact Registry, Cloud Run, Pub/Sub, Secret Manager, and Cloud SQL APIs are enabled
- container images are built and pushed to Artifact Registry
- secrets are stored in Secret Manager

## Environment variables

Both services need:

- `CI_OBS_DATABASE_URL`
- `CI_OBS_GITHUB_API_URL`
- `CI_OBS_REPOSITORY_ALLOWLIST`
- `CI_OBS_INITIAL_FETCH_DELAY_SECONDS`
- `CI_OBS_GITHUB_FETCH_RETRY_ATTEMPTS`
- `CI_OBS_GITHUB_FETCH_RETRY_INTERVAL_SECONDS`

Webhook service also needs:

- `CI_OBS_WEBHOOK_SECRET`
- `CI_OBS_PUBSUB_TOPIC`

Worker service also needs:

- `CI_OBS_GITHUB_APP_ID`
- `CI_OBS_GITHUB_APP_PRIVATE_KEY`

All runtime workloads that touch Postgres also need the Cloud SQL instance attached with:

- `--add-cloudsql-instances PROJECT:REGION:INSTANCE`

The same application image can also be used for schema migrations via a Cloud Run Job that runs:

- `alembic upgrade head`

## Deploy

Use the helper scripts in this folder or adapt them to your environment.

Recommended deployment order:

1. build and push the image
2. create or update the migration job
3. execute the migration job successfully
4. deploy webhook
5. deploy worker
