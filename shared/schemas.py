"""Pydantic models for event contracts and normalized ingestion records."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WebhookIngestionMessage(BaseModel):
    """Compact custom event published by the reusable workflow and Pub/Sub."""

    event_type: str = "workflow_run_completed"
    action: str
    delivery_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    repository_id: int
    repository_full_name: str
    run_id: int
    run_attempt: int
    sent_at: datetime


class PubSubMessageEnvelope(BaseModel):
    """Pub/Sub push envelope received by the worker service."""

    message: dict[str, Any]
    subscription: str | None = None

    def decode_data(self, *, max_bytes: int | None = None) -> dict[str, Any]:
        """Decode and size-check the JSON payload inside a Pub/Sub push envelope."""

        raw = self.message.get("data", "")
        decoded = base64.b64decode(raw)
        if max_bytes is not None and len(decoded) > max_bytes:
            raise ValueError("Pub/Sub message exceeds configured size limit")
        return json.loads(decoded.decode("utf-8"))


class RepositoryRecord(BaseModel):
    """Normalized repository identity used during persistence."""

    github_repository_id: int
    full_name: str
    name: str


class WorkflowRunRecord(BaseModel):
    """Normalized workflow-run record ready for database upsert."""

    github_run_id: int
    run_attempt: int
    workflow_id: int | None = None
    workflow_name: str | None = None
    workflow_path: str | None = None
    caller_workflow_path: str | None = None
    referenced_workflow_repo: str | None = None
    referenced_workflow_path: str | None = None
    referenced_workflow_ref: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    actor_login: str | None = None
    trigger_event: str | None = None
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


class StepRunRecord(BaseModel):
    """Normalized step-level execution record."""

    step_number: int
    step_name: str
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


class JobRunRecord(BaseModel):
    """Normalized job-level execution record with nested step records."""

    github_job_id: int
    job_name: str
    runner_name: str | None = None
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    steps: list[StepRunRecord] = Field(default_factory=list)


class RawIngestionEventRecord(BaseModel):
    """Raw payload persisted for replay, debugging, and schema evolution."""

    source_type: str
    repository_id: int
    run_id: int
    run_attempt: int
    page_number: int | None = None
    correlation_id: str
    payload: dict[str, Any]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestionBundle(BaseModel):
    """Normalized and raw records produced from one ingestion attempt."""

    repository: RepositoryRecord
    workflow_run: WorkflowRunRecord
    jobs: list[JobRunRecord]
    raw_events: list[RawIngestionEventRecord]
