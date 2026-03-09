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
- a plan to create a GitHub App for multi-repo access

Recommended order:

1. complete `docs/local-smoke-test.md`
2. create baseline GCP infrastructure
3. create and install the GitHub App using `docs/github-app-setup.md`
4. populate all required secrets
5. build and push images
6. create or update the migration job and run it
7. deploy services
8. configure reusable workflow callback delivery

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
  --edition=ENTERPRISE \
  --tier=db-f1-micro \
  --region=YOUR_REGION
```

If `db-f1-micro` is rejected in your project or region, use a small custom tier such as:

```bash
gcloud sql instances create ci-observability-pg \
  --database-version=POSTGRES_16 \
  --edition=ENTERPRISE \
  --tier=db-custom-1-3840 \
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
  --password="DB_PASSWORD"
```

If you lose the password, reset it with:

```bash
gcloud sql users set-password ci_observability_app \
  --instance=ci-observability-pg \
  --password="NEW_DB_PASSWORD"
```

## 6. Store secrets in Secret Manager

Create secret containers:

```bash
gcloud secrets create ci-obs-webhook-secret --replication-policy=automatic
gcloud secrets create ci-obs-webhook-auth-token --replication-policy=automatic
gcloud secrets create ci-obs-database-url --replication-policy=automatic
```

Note:

- `ci-obs-webhook-secret` is the shared callback signing secret used between reusable workflows and the webhook service.
- `ci-obs-webhook-auth-token` is a second shared token used to authenticate callback requests before they are accepted.
- `ci-obs-database-url` is the full SQLAlchemy connection string, not a randomly generated secret.

Add values in the GCP GUI or from local files. Do not place secret values in repo files.

Values needed at this point:

- `ci-obs-webhook-secret`
  - random shared secret generated outside the repo, for example in 1Password
- `ci-obs-webhook-auth-token`
  - second random shared secret or bearer token value generated outside the repo
- `ci-obs-database-url`
  - format:
  - `postgresql+psycopg://ci_observability_app:DB_PASSWORD@/ci_observability?host=/cloudsql/PROJECT:REGION:INSTANCE`

Optional hardening:

- If you want shared replay protection across multiple webhook instances, also provision a Redis-compatible TTL store such as Memorystore and plan to set `CI_OBS_REPLAY_STORE_URL` on the webhook service.
- Decide on your GCP-side OTLP ingestion path and plan to set `CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT` on both services. The intended model is OTEL -> GCP collector / GCP observability backend first, with any vendor export handled downstream. Do not leave this set to a local `localhost` endpoint in deployed environments.

Get the Cloud SQL connection name with:

```bash
gcloud sql instances describe ci-observability-pg --format="value(connectionName)"
```

Do not create `ci-obs-github-app-private-key` until after the GitHub App exists and you have downloaded the PEM key.

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

## 8. Create and run the migration job

Use the same container image as the services. This keeps the artifact footprint small while still giving migrations an explicit execution path.

Create or update the Cloud Run Job:

```bash
gcloud run jobs deploy ci-observability-migrate \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/webhook:latest \
  --command alembic \
  --args upgrade \
  --args head \
  --set-secrets CI_OBS_DATABASE_URL=ci-obs-database-url:latest \
  --set-cloudsql-instances PROJECT:REGION:INSTANCE
```

Run the job before deploying service revisions that depend on schema changes:

```bash
gcloud run jobs execute ci-observability-migrate \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --wait
```

The job should complete successfully before webhook or worker deployments are rolled out.

## 9. Deploy Cloud Run services

There are two valid deployment modes:

- current working baseline:
  - webhook and worker can continue using the existing service-account model already proven in the environment
- recommended hardened target state:
  - move webhook and worker to dedicated least-privilege service accounts

Before deployment, ensure:

- the worker is private
- the relevant runtime identity can read the required secrets
- the worker and migration runtime identity have `roles/cloudsql.client`
- you have the GitHub App ID available
- `ci-obs-github-app-private-key` exists in Secret Manager
- the Cloud SQL connection name is available as `PROJECT:REGION:INSTANCE`

Recommended hardened target state:

Create dedicated service accounts:

```bash
gcloud iam service-accounts create ci-obs-webhook-sa \
  --display-name "CI Observability Webhook"
gcloud iam service-accounts create ci-obs-worker-sa \
  --display-name "CI Observability Worker"
```

Grant minimum access:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member=serviceAccount:ci-obs-webhook-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member=serviceAccount:ci-obs-worker-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/cloudsql.client
```

Optional hardening:

- Create a Memorystore Redis instance for shared replay protection.
- Attach the webhook service to the VPC path that can reach that Redis instance, using a Serverless VPC Access connector or Direct VPC egress according to your network standard.
- Set `CI_OBS_REPLAY_STORE_URL=redis://REDIS_HOST:6379/0` on the webhook service once connectivity is in place.

Grant secret access only to the service that needs each secret:

```bash
gcloud secrets add-iam-policy-binding ci-obs-webhook-secret \
  --member=serviceAccount:ci-obs-webhook-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding ci-obs-webhook-auth-token \
  --member=serviceAccount:ci-obs-webhook-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding ci-obs-database-url \
  --member=serviceAccount:ci-obs-worker-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding ci-obs-github-app-private-key \
  --member=serviceAccount:ci-obs-worker-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

Current working baseline:

- if you have not yet migrated to dedicated service accounts, keep using the existing service identity and grant it only the minimum roles required for the current deployment

Recommended hardened target state:

Deploy the webhook service:

```bash
gcloud run deploy ci-observability-webhook \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/webhook:latest \
  --platform managed \
  --allow-unauthenticated \
  --service-account ci-obs-webhook-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars CI_OBS_PUBSUB_TOPIC=ci-observability-ingestion \
  --set-secrets CI_OBS_WEBHOOK_SECRET=ci-obs-webhook-secret:latest,CI_OBS_WEBHOOK_AUTH_TOKEN=ci-obs-webhook-auth-token:latest
```

If Redis-backed replay protection is enabled, add:

```bash
--set-env-vars CI_OBS_PUBSUB_TOPIC=ci-observability-ingestion,CI_OBS_REPLAY_STORE_URL=redis://REDIS_HOST:6379/0
```

Add the OTLP exporter configuration to the webhook deployment. Point it at the deployed GCP collector service URL or another GCP-controlled OTLP boundary, not a local endpoint:

```bash
--set-env-vars CI_OBS_PUBSUB_TOPIC=ci-observability-ingestion,CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_COLLECTOR_SERVICE_URL/v1/traces
```

Deploy the worker service:

```bash
gcloud run deploy ci-observability-worker \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/worker:latest \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account ci-obs-worker-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --add-cloudsql-instances PROJECT:REGION:INSTANCE \
  --set-env-vars CI_OBS_GITHUB_APP_ID=YOUR_GITHUB_APP_ID,CI_OBS_MAX_INGESTION_MESSAGE_AGE_SECONDS=3600 \
  --set-secrets CI_OBS_GITHUB_APP_PRIVATE_KEY=ci-obs-github-app-private-key:latest,CI_OBS_DATABASE_URL=ci-obs-database-url:latest
```

Add the same GCP-first OTLP settings to the worker deployment. Use the deployed collector service URL:

```bash
--set-env-vars CI_OBS_GITHUB_APP_ID=YOUR_GITHUB_APP_ID,CI_OBS_MAX_INGESTION_MESSAGE_AGE_SECONDS=3600,CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_COLLECTOR_SERVICE_URL/v1/traces
```

The execution telemetry pipeline remains separate:

- reusable workflow callback -> webhook -> Pub/Sub -> worker -> GitHub API -> Postgres

OTEL is for runtime/service telemetry, not a replacement for the normalized GitHub execution telemetry stored by the worker.

Optional:

- the repo also includes PowerShell helper scripts in `deploy/cloud-run/` for users who prefer them
- the OTEL collector setup is documented separately in `docs/bootstrap-otel-gcp.md`

## 10. GitHub App setup

Follow:

- `docs/github-app-setup.md`

After the app exists:

- create `ci-obs-github-app-private-key`
- add the private key value in Secret Manager
- record the GitHub App ID for worker deployment

## 11. Create the Pub/Sub push subscription

After the worker URL exists:

```bash
gcloud pubsub subscriptions create ci-observability-worker-push \
  --topic=ci-observability-ingestion \
  --push-endpoint=https://WORKER_URL/pubsub/ingest \
  --dead-letter-topic=ci-observability-ingestion-dlq \
  --max-delivery-attempts=5
```

Also configure authenticated push and Cloud Run invoker permissions so only Pub/Sub can call the worker.

At minimum, configure:

```bash
gcloud pubsub subscriptions update ci-observability-worker-push \
  --project YOUR_PROJECT_ID \
  --push-endpoint=https://WORKER_URL/pubsub/ingest \
  --push-auth-service-account=WORKLOAD_SERVICE_ACCOUNT \
  --push-auth-token-audience=https://WORKER_URL
```

Grant the push auth service account `roles/run.invoker` on the worker service:

```bash
gcloud run services add-iam-policy-binding ci-observability-worker \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --member=serviceAccount:WORKLOAD_SERVICE_ACCOUNT \
  --role=roles/run.invoker
```

Grant the Pub/Sub service agent permission to mint the OIDC token:

```bash
gcloud iam service-accounts add-iam-policy-binding WORKLOAD_SERVICE_ACCOUNT \
  --project YOUR_PROJECT_ID \
  --member=serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/iam.serviceAccountTokenCreator
```

## 12. Webhook setup

Configure the reusable workflow callback target to point at:

```text
https://WEBHOOK_URL/workflow/callback
```

Use the same secret value stored in `ci-obs-webhook-secret` when signing the callback payload from the reusable workflow.
Also send the same value stored in `ci-obs-webhook-auth-token` in the authentication header required by the webhook service.

The callback payload should match the application contract implemented by `WebhookIngestionMessage`. The listener should accept the signed custom event and trigger fetch on receipt.

The webhook service is only the ingress and queue handoff layer:

- it validates the custom event and signature
- it validates a second shared auth token
- it rejects stale and replayed deliveries
- it publishes a compact Pub/Sub message
- it does not call the GitHub API
- it does not access Postgres

Protect the public webhook edge with Cloud Armor or an equivalent perimeter control:

- rate limiting
- basic WAF protections
- abuse monitoring on unexpected traffic spikes

## 13. First end-to-end test

Use the repo workflow:

- `.github/workflows/manual-test.yml`

That workflow now needs three GitHub Actions secrets if you use it to test the hardened listener:

- `CI_OBS_CALLBACK_URL`
- `CI_OBS_CALLBACK_SECRET`
- `CI_OBS_CALLBACK_AUTH_TOKEN`

Then verify:

- webhook service receives and accepts the delivery
- Pub/Sub message is published
- worker receives the push request
- rows appear in Postgres
- workflow/job/step rows are persisted as expected

## 14. Backlog cleanup

After fixing broken deployments, inspect and clear stale retry backlog so old failures do not keep polluting logs.

Inspect the worker push subscription and DLQ subscription:

```bash
gcloud pubsub subscriptions describe ci-observability-worker-push --project YOUR_PROJECT_ID
gcloud pubsub subscriptions describe ci-observability-ingestion-dlq-sub --project YOUR_PROJECT_ID
```

Drain stale DLQ messages if they only represent obsolete test failures:

```bash
gcloud pubsub subscriptions pull ci-observability-ingestion-dlq-sub \
  --project YOUR_PROJECT_ID \
  --limit 100 \
  --auto-ack
```

The worker-side stale message cutoff reduces the need for future manual cleanup by acknowledging messages older than `CI_OBS_MAX_INGESTION_MESSAGE_AGE_SECONDS` instead of retrying them forever.

## Security notes

- Never commit `.env` or secret-bearing local files.
- Do not put DB passwords or private keys on command lines where shell history may retain them if you can avoid it.
- Prefer Secret Manager and local secure files outside the repo.
- Keep the worker private and invoked only by Pub/Sub.
- Apply DB access controls and retention policy to `raw_ingestion_events`.
