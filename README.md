# CI Observability Ingestion

Workflow-agnostic GitHub Actions ingestion skeleton for collecting workflow run, job, and step telemetry across multiple repositories.

## Services

- `services/webhook_service/app.py`
  - Receives `workflow_run` completion webhooks
  - Validates the GitHub signature
  - Filters to allowlisted repositories
  - Persists the raw webhook payload
  - Publishes an immutable ingestion message

- `services/ingestion_worker/app.py`
  - Receives Pub/Sub push messages
  - Fetches workflow run and paginated jobs data from GitHub
  - Persists normalized workflow/job/step records
  - Persists raw GitHub API payloads
  - Returns `500` on failure so Pub/Sub retry / DLQ policy can handle the message

## Database

Apply `migrations/001_initial_schema.sql` to a Postgres database before starting the services.

## Configuration

Copy `.env.example` to `.env` and set:

- GitHub webhook secret
- GitHub App credentials
- repository allowlist
- Postgres connection string

## Run

```bash
uvicorn services.webhook_service.app:app --reload
uvicorn services.ingestion_worker.app:app --reload
```

## Tests

Install dev dependencies and run:

```bash
python -m pytest -q
```
