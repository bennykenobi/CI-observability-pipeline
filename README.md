# CI Observability Ingestion

Workflow-agnostic GitHub Actions ingestion skeleton for collecting workflow run, job, and step telemetry across multiple repositories.

This MVP intentionally persists both normalized execution telemetry and raw webhook/API payloads into the platform database. The raw payload tables are part of the contract for this phase so the schema can evolve while workflows are still changing.

## Services

- `services/webhook_service/app.py`
  - Receives custom workflow callback events from the central reusable workflow
  - Validates the shared HMAC signature
  - Filters to allowlisted repositories
  - Persists the raw callback payload
  - Publishes an immutable ingestion message

- `services/ingestion_worker/app.py`
  - Receives Pub/Sub push messages
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
- GitHub App credentials
- repository allowlist
- Postgres connection string

Security-sensitive notes:

- Do not rely on default development credentials in deployed environments.
- Persisted raw payloads should be protected by database access controls and a retention policy.
- Callback deliveries are deduplicated by delivery ID to reduce replay risk.
- Request body sizes are logged and enforced by configurable ingress limits.

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
- `.github/workflows/manual-test.yml` is a small manually triggered workflow that can send a signed callback to the webhook service when `CI_OBS_CALLBACK_URL` and `CI_OBS_CALLBACK_SECRET` are configured as GitHub Actions secrets.

## Deployment

Starter Cloud Run deployment scripts and notes are in `deploy/cloud-run/`.

Additional runbooks:

- `docs/bootstrap-gcp.md`
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
