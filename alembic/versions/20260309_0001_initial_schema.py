from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260309_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("github_repository_id"),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id"),
            nullable=False,
        ),
        sa.Column("github_run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), nullable=True),
        sa.Column("workflow_name", sa.String(length=255), nullable=True),
        sa.Column("workflow_path", sa.String(length=512), nullable=True),
        sa.Column("caller_workflow_path", sa.String(length=512), nullable=True),
        sa.Column("referenced_workflow_repo", sa.String(length=255), nullable=True),
        sa.Column("referenced_workflow_path", sa.String(length=512), nullable=True),
        sa.Column("referenced_workflow_ref", sa.String(length=255), nullable=True),
        sa.Column("head_branch", sa.String(length=255), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column("actor_login", sa.String(length=255), nullable=True),
        sa.Column("trigger_event", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("conclusion", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "repository_id",
            "github_run_id",
            "run_attempt",
            name="uq_workflow_runs_repo_run_attempt",
        ),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_run_id",
            sa.BigInteger(),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("github_job_id", sa.BigInteger(), nullable=False),
        sa.Column("job_name", sa.String(length=255), nullable=False),
        sa.Column("runner_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("conclusion", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("github_job_id"),
    )

    op.create_table(
        "step_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_run_id", sa.BigInteger(), sa.ForeignKey("job_runs.id"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("conclusion", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("job_run_id", "step_number", name="uq_step_runs_job_step"),
    )

    op.create_table(
        "raw_ingestion_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_type",
            "repository_id",
            "run_id",
            "run_attempt",
            "page_number",
            "payload_hash",
            name="uq_raw_ingestion_events_dedupe",
        ),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("delivery_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "received_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("delivery_id"),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("raw_ingestion_events")
    op.drop_table("step_runs")
    op.drop_table("job_runs")
    op.drop_table("workflow_runs")
    op.drop_table("repositories")
