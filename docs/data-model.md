# Data Model

This document describes the normalized execution-telemetry schema and the raw-ingestion support tables used by the platform database.

## Relationship map

```text
repositories
  └── workflow_runs
        └── job_runs
              └── step_runs

raw_ingestion_events
webhook_deliveries
```

## repositories

Purpose:
- Canonical repository identity for all ingested runs.

Primary key:
- `id`

Important columns:
- `github_repository_id`
- `full_name`
- `created_at`
- `updated_at`

Key constraints:
- unique: `github_repository_id`
- unique: `full_name`

Notes:
- This is the parent table for `workflow_runs`.
- Repository identity comes from the event payload and is later corroborated during GitHub API enrichment.

## workflow_runs

Purpose:
- One row per GitHub workflow run attempt.

Primary key:
- `id`

Foreign keys:
- `repository_id -> repositories.id`

Important columns:
- `github_run_id`
- `run_attempt`
- `workflow_name`
- `workflow_path`
- `status`
- `conclusion`
- `event`
- `head_branch`
- `head_sha`
- `actor_login`
- `run_started_at`
- `updated_at_source`
- `completed_at`
- `duration_seconds`
- `caller_repository_full_name`
- `caller_workflow_path`
- `reusable_workflow_ref`

Key constraints:
- unique: `(repository_id, github_run_id, run_attempt)`

Notes:
- This is the durable normalized record for workflow execution telemetry.
- Re-runs are modeled through `run_attempt`.

## job_runs

Purpose:
- One row per GitHub job within a workflow run.

Primary key:
- `id`

Foreign keys:
- `workflow_run_id -> workflow_runs.id`

Important columns:
- `github_job_id`
- `job_name`
- `status`
- `conclusion`
- `runner_name`
- `runner_group_name`
- `started_at`
- `completed_at`
- `duration_seconds`

Key constraints:
- unique: `github_job_id`

Notes:
- Jobs are fetched from the GitHub Actions jobs API.
- Pagination is handled in the worker and may produce multiple raw API payload rows for one workflow run.

## step_runs

Purpose:
- One row per job step for granular step-level telemetry.

Primary key:
- `id`

Foreign keys:
- `job_run_id -> job_runs.id`

Important columns:
- `step_number`
- `step_name`
- `status`
- `conclusion`
- `started_at`
- `completed_at`
- `duration_seconds`

Key constraints:
- unique: `(job_run_id, step_number)`

Notes:
- This table is what makes the platform step-aware rather than workflow-level only.

## raw_ingestion_events

Purpose:
- Preserve raw payloads for replay, debugging, and schema evolution.

Primary key:
- `id`

Important columns:
- `source_type`
- `repository_id`
- `run_id`
- `run_attempt`
- `page_number`
- `payload_json`
- `payload_hash`
- `fetched_at`
- `correlation_id`

Key constraints:
- unique: `(source_type, payload_hash)`

Notes:
- Expected `source_type` values include:
  - `workflow_callback`
  - `workflow_run_api`
  - `jobs_api`
- This table is intentionally separate from the normalized execution tables.

## webhook_deliveries

Purpose:
- Track accepted callback delivery IDs for replay protection and auditability.

Primary key:
- `id`

Important columns:
- `delivery_id`
- `event_type`
- `repository_id`
- `run_id`
- `received_at`

Key constraints:
- unique: `delivery_id`

Notes:
- The listener uses this table for durable duplicate-delivery rejection where applicable.
- Redis-backed replay protection is the preferred runtime path for multi-instance deployments; this table remains useful for auditability.

## Idempotency rules

- `workflow_runs` upsert on `(repository_id, github_run_id, run_attempt)`
- `job_runs` upsert on `github_job_id`
- `step_runs` upsert on `(job_run_id, step_number)`
- `raw_ingestion_events` deduplicate on `(source_type, payload_hash)`
- `webhook_deliveries` deduplicate on `delivery_id`

## Operational notes

- Execution telemetry is stored in Postgres and owned by the worker pipeline.
- Runtime telemetry is separate and flows through OpenTelemetry into GCP observability backends.
- Schema changes are versioned with Alembic.
