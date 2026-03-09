# GCP Bootstrap Runbook

This runbook is for first-time manual setup of the GCP project for the CI observability ingestion platform.

It is intentionally documentation only:

- no bootstrap scripts
- no inline secret values
- no instructions that require committing local operator files into the repo

## Prerequisites

- `gcloud` installed locally
- billing enabled on the target GCP project
- Docker installed locally
- a GitHub repository already created for this project
- a GitHub App plan for multi-repo access

## 1. Set project context

Run these locally from any folder:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region YOUR_REGION
```

Recommended region:

- use the same region for Cloud Run, Artifact Registry, and Cloud SQL where practical

## 2. Enable required APIs

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  iam.googleapis.com
```

## 3. Create Artifact Registry

```bash
gcloud artifacts repositories create ci-observability \
  --repository-format=docker \
  --location=YOUR_REGION \
  --description="CI observability service images"
```

## 4. Create Pub/Sub resources

```bash
gcloud pubsub topics create ci-observability-ingestion
gcloud pubsub topics create ci-observability-ingestion-dlq
gcloud pubsub subscriptions create ci-observability-ingestion-dlq-sub \
  --topic=ci-observability-ingestion-dlq
```

Do not create the worker push subscription yet. Wait until the worker Cloud Run URL exists.

## 5. Create Cloud SQL Postgres

```bash
gcloud sql instances create ci-observability-pg \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=YOUR_REGION
```

Create the database:

```bash
gcloud sql databases create ci_observability \
  --instance=ci-observability-pg
```

Create the DB user:

```bash
gcloud sql users create ci_observability_app \
  --instance=ci-observability-pg \
  --prompt-for-password
```

## 6. Store secrets in Secret Manager

Create secret containers:

```bash
gcloud secrets create ci-obs-webhook-secret --replication-policy=automatic
gcloud secrets create ci-obs-database-url --replication-policy=automatic
gcloud secrets create ci-obs-github-app-private-key --replication-policy=automatic
```

Add values interactively or from local files. Do not place secret values in repo files.

Examples:

```bash
printf "YOUR_WEBHOOK_SECRET" | gcloud secrets versions add ci-obs-webhook-secret --data-file=-
```

For the GitHub App private key, use a local file outside the repo:

```bash
gcloud secrets versions add ci-obs-github-app-private-key --data-file=/secure/path/github-app-private-key.pem
```

For the database URL, use the Cloud SQL connection name and store the final runtime DSN in Secret Manager:

```text
postgresql+psycopg://ci_observability_app:DB_PASSWORD@/ci_observability?host=/cloudsql/PROJECT:REGION:INSTANCE
```

## 7. Build and push images

Authenticate Docker:

```bash
gcloud auth configure-docker YOUR_REGION-docker.pkg.dev
```

Build and push:

```bash
docker build -f Dockerfile.webhook -t YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/webhook:latest .
docker build -f Dockerfile.worker -t YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/worker:latest .

docker push YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/webhook:latest
docker push YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/worker:latest
```

## 8. Apply database migrations

Run this locally with `CI_OBS_DATABASE_URL` pointed at the Cloud SQL DSN:

```bash
alembic upgrade head
```

## 9. Deploy Cloud Run services

Use the existing repo deploy scripts as a starting point:

- `deploy/cloud-run/deploy-webhook.ps1`
- `deploy/cloud-run/deploy-worker.ps1`

Before deployment, ensure:

- the webhook service is public only if you are ready to receive GitHub webhooks
- the worker service is private
- both services use service accounts with least privilege
- secret access is granted only to the relevant service account

## 10. Create the Pub/Sub push subscription

After the worker URL exists:

```bash
gcloud pubsub subscriptions create ci-observability-worker-push \
  --topic=ci-observability-ingestion \
  --push-endpoint=https://WORKER_URL/pubsub/ingest \
  --dead-letter-topic=ci-observability-ingestion-dlq \
  --max-delivery-attempts=5
```

Also configure authenticated push and Cloud Run invoker permissions so only Pub/Sub can call the worker.

## 11. GitHub App setup

Create a GitHub App with permissions at minimum for:

- Actions: read
- Metadata: read
- Contents: read

Install it on the repositories you want to monitor.

Store the private key in Secret Manager and the App ID as a Cloud Run env var.

## 12. Webhook setup

Configure the GitHub webhook to point at:

```text
https://WEBHOOK_URL/github/webhook
```

Use:

- content type: `application/json`
- secret: the same value stored in `ci-obs-webhook-secret`
- event: `workflow_run`

## 13. First end-to-end test

Use the repo workflow:

- `.github/workflows/manual-test.yml`

Then verify:

- webhook service receives and accepts the delivery
- Pub/Sub message is published
- worker receives the push request
- rows appear in Postgres
- duplicate delivery handling behaves correctly

## Security notes

- Never commit `.env` or secret-bearing local files.
- Do not put DB passwords or private keys on command lines where shell history may retain them if you can avoid it.
- Prefer Secret Manager and local secure files outside the repo.
- Keep the worker private and invoked only by Pub/Sub.
- Apply DB access controls and retention policy to `raw_ingestion_events`.
