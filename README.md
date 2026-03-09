# CI Observability Ingestion

Workflow-agnostic GitHub Actions ingestion skeleton for collecting workflow run, job, and step telemetry across multiple repositories.

This MVP intentionally persists both normalized execution telemetry and raw webhook/API payloads into the platform database. The raw payload tables are part of the contract for this phase so the schema can evolve while workflows are still changing.

## Services

- `services/webhook_service/app.py`
  - Receives custom observability events from reusable workflows
  - Validates the shared signature and auth token
  - Enforces a short timestamp freshness window
  - Rejects duplicate delivery IDs within the replay window
  - Filters to relevant completed custom events
  - Publishes an immutable ingestion message to Pub/Sub
  - Does not call the GitHub API
  - Does not access Postgres

- `services/ingestion_worker/app.py`
  - Receives Pub/Sub push messages
  - Acknowledges stale messages instead of endlessly retrying old backlog
  - Waits for GitHub API consistency and retries transient failures
  - Fetches workflow run and paginated jobs data from GitHub
  - Persists normalized workflow/job/step records
  - Persists raw GitHub API payloads
  - Returns `500` on failure so Pub/Sub retry / DLQ policy can handle the message

## Database

Run Alembic migrations before starting the services:

```bash
alembic upgrade head
```

Or use:

```bash
make db-upgrade
```

For a table-by-table schema reference, see [docs/data-model.md](docs/data-model.md).

For deployed environments, run migrations from the same container image in GCP rather than from a laptop. The recommended pattern is a Cloud Run Job that executes `alembic upgrade head` against the production database before rolling out service revisions.

Normalized tables:

- `repositories`
- `workflow_runs`
- `job_runs`
- `step_runs`

Raw payload storage:

- `raw_ingestion_events`

## Configuration

Copy `.env.example` to `.env` and set:

- callback shared secret
- callback auth token
- GitHub App credentials
- Postgres connection string

Security-sensitive notes:

- Do not rely on default development credentials in deployed environments.
- Persisted raw payloads should be protected by database access controls and a retention policy.
- Callback deliveries should be monitored for replay and delivery anomalies.
- Public webhook ingress should be protected with an edge control such as Cloud Armor in addition to app-layer authentication.
- Request body sizes are logged and enforced by configurable ingress limits.
- The webhook uses `CI_OBS_REPLAY_STORE_URL` when provided to enforce replay protection through a shared TTL-backed store such as Redis. Without it, replay protection falls back to in-memory state and is only reliable per service instance.
- The worker uses `CI_OBS_MAX_INGESTION_MESSAGE_AGE_SECONDS` to discard stale Pub/Sub messages instead of retrying old backlog forever.
- OTEL tracing is a first-class runtime concern. In deployed environments, `CI_OBS_OTEL_EXPORTER_OTLP_ENDPOINT` must point at the deployed GCP collector or GCP-controlled OTLP boundary, not a local endpoint. `localhost` values in `.env.example` are for local development only. Vendor systems like New Relic should remain downstream export targets, not the primary backend.
- The OTEL collector should be deployed as a private platform component. Webhook and worker should reach it through authenticated GCP service-to-service calls, not through a public unauthenticated endpoint.

## Run

```bash
uvicorn services.webhook_service.app:app --reload
uvicorn services.ingestion_worker.app:app --reload
```

Convenience commands:

```bash
make install
make test
make run-webhook
make run-worker
make db-upgrade
```

## Docker

Build the webhook image:

```bash
docker build -f Dockerfile.webhook -t ci-observability-webhook .
```

Build the worker image:

```bash
docker build -f Dockerfile.worker -t ci-observability-worker .
```

Run locally:

```bash
docker run --rm -p 8080:8080 --env-file .env ci-observability-webhook
docker run --rm -p 8081:8080 --env-file .env ci-observability-worker
```

Or start Postgres plus both services locally:

```bash
docker compose up --build
```

## Tests

Install dev dependencies and run:

```bash
python -m pytest -q
python -m ruff check .
```

## GitHub Workflows

- `.github/workflows/ci.yml` runs tests on pushes and pull requests.
- `.github/workflows/manual-test.yml` is a small manually triggered workflow that sends a signed custom observability event to the webhook service so the Pub/Sub -> worker path can be exercised.

## Deployment

Starter Cloud Run deployment scripts and notes are in `deploy/cloud-run/`.

Note:

- the runbooks distinguish between the current working deployment path and the recommended hardened target state
- dedicated service accounts remain a follow-on hardening step if you have not adopted them yet

Additional runbooks:

- `docs/bootstrap-gcp.md`
- `docs/bootstrap-otel-gcp.md`
- `docs/github-app-setup.md`
- `docs/local-smoke-test.md`

## Schema Versioning

Database schema changes are versioned with Alembic in `alembic/versions/`.

Create a new migration:

```bash
alembic revision --autogenerate -m "describe change"
```

Or use:

```bash
make db-revision m="describe change"
```
