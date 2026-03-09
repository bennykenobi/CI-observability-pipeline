CREATE TABLE IF NOT EXISTS repositories (
    id BIGSERIAL PRIMARY KEY,
    github_repository_id BIGINT NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id),
    github_run_id BIGINT NOT NULL,
    run_attempt INTEGER NOT NULL,
    workflow_id BIGINT NULL,
    workflow_name VARCHAR(255) NULL,
    workflow_path VARCHAR(512) NULL,
    caller_workflow_path VARCHAR(512) NULL,
    referenced_workflow_repo VARCHAR(255) NULL,
    referenced_workflow_path VARCHAR(512) NULL,
    referenced_workflow_ref VARCHAR(255) NULL,
    head_branch VARCHAR(255) NULL,
    head_sha VARCHAR(64) NULL,
    actor_login VARCHAR(255) NULL,
    trigger_event VARCHAR(128) NULL,
    status VARCHAR(64) NULL,
    conclusion VARCHAR(64) NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_workflow_runs_repo_run_attempt UNIQUE (repository_id, github_run_id, run_attempt)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id BIGSERIAL PRIMARY KEY,
    workflow_run_id BIGINT NOT NULL REFERENCES workflow_runs(id),
    github_job_id BIGINT NOT NULL UNIQUE,
    job_name VARCHAR(255) NOT NULL,
    runner_name VARCHAR(255) NULL,
    status VARCHAR(64) NULL,
    conclusion VARCHAR(64) NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL
);

CREATE TABLE IF NOT EXISTS step_runs (
    id BIGSERIAL PRIMARY KEY,
    job_run_id BIGINT NOT NULL REFERENCES job_runs(id),
    step_number INTEGER NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    status VARCHAR(64) NULL,
    conclusion VARCHAR(64) NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    CONSTRAINT uq_step_runs_job_step UNIQUE (job_run_id, step_number)
);

CREATE TABLE IF NOT EXISTS raw_ingestion_events (
    id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(64) NOT NULL,
    repository_id BIGINT NOT NULL,
    run_id BIGINT NOT NULL,
    run_attempt INTEGER NOT NULL,
    page_number INTEGER NULL,
    correlation_id VARCHAR(64) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_raw_ingestion_events_dedupe UNIQUE (
        source_type,
        repository_id,
        run_id,
        run_attempt,
        page_number,
        payload_hash
    )
);
