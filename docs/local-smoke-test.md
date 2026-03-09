# Local Smoke Test

This runbook validates the application locally with Docker Compose, Postgres, and Alembic before cloud deployment.

## Goal

Confirm the local stack can:

- start Postgres
- apply Alembic migrations
- start both services
- pass the existing automated tests

This is not a full end-to-end GitHub webhook simulation. It is a local readiness check.

## Prerequisites

- Docker Desktop or Docker Engine
- Python with project dependencies installed
- a local `.env` file based on `.env.example`

## 1. Create `.env`

Use `.env.example` as the template.

For local smoke testing, set:

```text
CI_OBS_ENVIRONMENT=development
CI_OBS_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ci_observability
CI_OBS_WEBHOOK_SECRET=local-test-secret
CI_OBS_GCP_PROJECT_ID=local-dev-project
CI_OBS_PUBSUB_TOPIC=ci-observability-ingestion
CI_OBS_REPOSITORY_ALLOWLIST=["your-org/your-repo"]
```

Do not use production credentials locally.

## 2. Start Postgres

```bash
docker compose up -d postgres
```

Confirm it is healthy enough to accept connections:

```bash
docker ps
```

## 3. Apply Alembic migrations

Run from the repo root:

```bash
alembic upgrade head
```

## 4. Run automated verification

```bash
python -m ruff check .
python -m pytest -q
```

## 5. Start the services

Start with Docker Compose:

```bash
docker compose up --build webhook worker
```

Or run them directly:

```bash
uvicorn services.webhook_service.app:app --reload
uvicorn services.ingestion_worker.app:app --reload
```

## 6. Validate health endpoints

Webhook service:

```bash
curl http://localhost:8080/healthz
```

Worker service:

```bash
curl http://localhost:8081/healthz
```

## 7. What this proves

This smoke test proves:

- app startup works with current config
- migrations apply
- local Postgres is reachable
- Docker images can start
- the repo passes lint and tests

It does not prove:

- real GitHub webhook delivery
- real Pub/Sub publication
- real GitHub App authentication
- Cloud Run / Pub/Sub IAM setup

Those need the GCP bootstrap and first cloud integration test.
