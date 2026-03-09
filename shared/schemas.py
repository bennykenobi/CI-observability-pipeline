from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WebhookIngestionMessage(BaseModel):
    event_type: str = "workflow_run_completed"
    action: str
    delivery_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    repository_id: int
    repository_full_name: str
    run_id: int
    run_attempt: int
    installation_id: int | None = None
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PubSubMessageEnvelope(BaseModel):
    message: dict[str, Any]
    subscription: str | None = None

    def decode_data(self) -> dict[str, Any]:
        raw = self.message.get("data", "")
        return json.loads(base64.b64decode(raw).decode("utf-8"))


class RepositoryRecord(BaseModel):
    github_repository_id: int
    full_name: str
    name: str


class WorkflowRunRecord(BaseModel):
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
    step_number: int
    step_name: str
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


class JobRunRecord(BaseModel):
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
    source_type: str
    repository_id: int
    run_id: int
    run_attempt: int
    page_number: int | None = None
    correlation_id: str
    payload: dict[str, Any]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestionBundle(BaseModel):
    repository: RepositoryRecord
    workflow_run: WorkflowRunRecord
    jobs: list[JobRunRecord]
    raw_events: list[RawIngestionEventRecord]
