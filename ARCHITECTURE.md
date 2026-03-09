# Architecture

## Purpose

This project is a workflow-agnostic GitHub Actions ingestion skeleton. It captures workflow run, job, and step execution telemetry across multiple repositories and persists both normalized records and raw payloads into the platform database.

The current phase ends at the platform Postgres boundary for execution telemetry. Runtime traces are emitted through OpenTelemetry into GCP-controlled telemetry infrastructure first. The platform does not treat New Relic as the primary backend; vendor export remains a downstream concern.

## Flow

1. A reusable workflow sends a custom observability event when a monitored workflow completes.
2. The webhook service validates the shared signature and auth token, enforces a short freshness window on `sent_at`, rejects duplicate `delivery_id` values within the replay window, recognizes relevant completed custom events, and publishes an immutable ingestion message to Pub/Sub. It does not call the GitHub API or access Postgres. In production, replay detection should use a shared TTL-backed store such as Redis rather than in-memory state.
3. The ingestion worker receives the Pub/Sub push message, acknowledges obviously stale deliveries to avoid endless backlog churn, waits for GitHub API consistency, fetches workflow and paginated jobs data from GitHub, normalizes the results, and stores both normalized rows and raw API payloads in Postgres.
4. If ingestion fails, the worker returns a non-2xx response so Pub/Sub retry and dead-letter policies can handle delivery.

## Runtime Telemetry Flow

1. Webhook and worker services emit OpenTelemetry spans around request handling, Pub/Sub handoff, GitHub API fetches, and persistence.
2. Those spans are exported to an OTLP endpoint owned by the platform in GCP, typically an OpenTelemetry Collector running in GCP as a private internal platform component.
3. The collector exports to GCP backends such as Cloud Trace and Cloud Monitoring.
4. Platform analysis and correlation can then combine runtime traces with execution telemetry in Postgres before any optional downstream vendor export.

## Services

### Webhook service

- Endpoint: `POST /workflow/callback`
- Health: `GET /healthz`
- Responsibilities:
  - shared-signature validation
  - secondary auth-token validation
  - freshness-window enforcement
  - replay detection by delivery ID via shared TTL-backed store when configured
  - relevant custom event recognition
  - Pub/Sub message publication
  - no GitHub API access
  - no Postgres access

### Worker service

- Endpoint: `POST /pubsub/ingest`
- Health: `GET /healthz`
- Responsibilities:
  - Pub/Sub push ingestion
  - stale-message rejection based on message age
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
- Memorystore Redis or equivalent shared TTL store for production replay detection
- Cloud Armor or equivalent edge protection in front of the public webhook service
- OTEL exporter support for trace emission from webhook, worker, GitHub API fetches, and persistence
- GCP-controlled OTLP ingestion path, typically via an OpenTelemetry Collector, as the primary runtime telemetry boundary
