# GCP OTEL Collector Runbook

This runbook sets up the GCP-controlled runtime telemetry boundary for the platform.

Use it after the core execution pipeline is already working:

- reusable workflow callback -> webhook -> Pub/Sub -> worker -> GitHub API -> Postgres

The collector is for service runtime telemetry only:

- webhook spans/logs/metrics
- worker spans/logs/metrics
- GitHub API and persistence traces emitted by those services

It is not used to transport GitHub execution telemetry such as:

- `workflow_runs`
- `job_runs`
- `step_runs`

## Goal

The intended telemetry path is:

- instrumentation -> OTEL -> GCP collector -> Cloud Trace / Cloud Monitoring -> optional downstream export

This keeps GCP as the primary telemetry ingestion boundary and leaves vendor export as a later concern.

## 1. Enable required APIs

```bash
gcloud services enable \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com
```

## 2. Create a collector service account

```bash
gcloud iam service-accounts create ci-obs-otel-collector-sa \
  --display-name "CI Observability OTEL Collector"
```

Grant it permission to write telemetry into GCP backends:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member=serviceAccount:ci-obs-otel-collector-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/cloudtrace.agent

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member=serviceAccount:ci-obs-otel-collector-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/monitoring.metricWriter
```

## 3. Build and publish a collector image

The repo provides:

- `deploy/otel/collector-config.yaml`
- `deploy/otel/Dockerfile`

Build and push the collector image to Artifact Registry:

```bash
docker build -f deploy/otel/Dockerfile -t YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/otel-collector:latest .
docker push YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/otel-collector:latest
```

## 4. Deploy the collector to Cloud Run

Deploy the collector as a private Cloud Run service:

```bash
gcloud run deploy ci-observability-otel-collector \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/ci-observability/otel-collector:latest \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account ci-obs-otel-collector-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

After deployment, get the collector service URL:

```bash
gcloud run services describe ci-observability-otel-collector \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --format='value(status.url)'
```

The returned Cloud Run URL becomes the OTLP endpoint base. For OTLP/HTTP, use:

```text
https://YOUR_COLLECTOR_SERVICE_URL/v1/traces
```

and, when metrics are emitted later:

```text
https://YOUR_COLLECTOR_SERVICE_URL/v1/metrics
```

## 5. Authorize webhook and worker to call the collector

Grant `roles/run.invoker` on the collector to the runtime service identity used by webhook and worker:

```bash
gcloud run services add-iam-policy-binding ci-observability-otel-collector \
  --project YOUR_PROJECT_ID \
  --region YOUR_REGION \
  --member=serviceAccount:YOUR_RUNTIME_SERVICE_ACCOUNT \
  --role=roles/run.invoker
```

## 6. Point the services at the collector

Redeploy the webhook with:

```bash
--set-env-vars CI_OBS_PUBSUB_TOPIC=ci-observability-ingestion,CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_COLLECTOR_SERVICE_URL/v1/traces
```

Redeploy the worker with:

```bash
--set-env-vars CI_OBS_GITHUB_APP_ID=YOUR_GITHUB_APP_ID,CI_OBS_MAX_INGESTION_MESSAGE_AGE_SECONDS=3600,CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_COLLECTOR_SERVICE_URL/v1/traces
```

The application OTLP exporter should authenticate to the private collector using a GCP-native service-to-service identity mechanism. Do not expose the collector publicly.

## 7. Verify traces land in GCP

Trigger a fresh workflow run and verify:

- webhook spans appear
- worker spans appear
- GitHub API spans appear
- persistence spans appear

Use Cloud Trace / Cloud Monitoring in GCP as the first verification point.

## 8. Downstream export

If New Relic or another vendor is needed later, add that as a downstream collector export step.

Do not change the application services to export directly to vendor backends as the primary path.
