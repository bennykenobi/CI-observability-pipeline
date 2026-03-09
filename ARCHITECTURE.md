# Architecture

## Purpose

This project is a workflow-agnostic GitHub Actions ingestion skeleton. It captures workflow run, job, and step execution telemetry across multiple repositories and persists both normalized records and raw payloads into the platform database.

The current phase ends at the platform Postgres boundary. It does not yet push data to New Relic, derive governance metrics, or populate a downstream reporting database.

## Flow

1. GitHub sends a `workflow_run` webhook when a monitored workflow completes.
2. The webhook service validates the GitHub signature, recognizes relevant completed `workflow_run` events, and publishes an immutable ingestion message to Pub/Sub.
3. The ingestion worker receives the Pub/Sub push message, waits for GitHub API consistency, fetches workflow and paginated jobs data from GitHub, normalizes the results, and stores both normalized rows and raw API payloads in Postgres.
4. If ingestion fails, the worker returns a non-2xx response so Pub/Sub retry and dead-letter policies can handle delivery.

## Services

### Webhook service

- Endpoint: `POST /github/webhook`
- Health: `GET /healthz`
- Responsibilities:
  - GitHub webhook signature validation
  - relevant event recognition
  - Pub/Sub message publication

### Worker service

- Endpoint: `POST /pubsub/ingest`
- Health: `GET /healthz`
- Responsibilities:
  - Pub/Sub push ingestion
  - GitHub App authentication
  - GitHub API retry and pagination handling
  - normalized persistence
  - raw API payload persistence

## Persistence model

The MVP persistence contract has two outputs in the same Postgres database:

- Normalized tables:
  - `repositories`
  - `workflow_runs`
  - `job_runs`
  - `step_runs`
- Raw payload table:
  - `raw_ingestion_events`

Raw payload storage is intentional. The monitored workflows are still evolving, and the raw records provide replay and schema-flexibility without blocking downstream analytics on the normalized model.

Schema changes are versioned with Alembic so database evolution has a single tracked migration path.

## Delivery semantics

- Delivery is at-least-once.
- Persistence must therefore be idempotent.
- Workflow runs are unique on `(repository_id, github_run_id, run_attempt)`.
- Jobs are unique on `github_job_id`.
- Steps are unique on `(job_run_id, step_number)`.
- Raw payload rows are deduplicated by source and payload hash.

## Current deployment target

- Cloud Run for both services
- Pub/Sub topic and push subscription between services
- Cloud SQL Postgres for persistence
- Secret Manager for runtime secrets
