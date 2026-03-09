"""Normalization and orchestration logic for worker-side ingestion."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from opentelemetry.trace import SpanKind
from sqlalchemy.exc import SQLAlchemyError

from shared.config import Settings
from shared.github import GitHubApiPermanentError, GitHubApiUnavailableError, GitHubClient
from shared.otel import get_tracer, set_span_attributes
from shared.schemas import (
    IngestionBundle,
    JobRunRecord,
    RawIngestionEventRecord,
    RepositoryRecord,
    StepRunRecord,
    WebhookIngestionMessage,
    WorkflowRunRecord,
)

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class IngestionRetryableError(RuntimeError):
    """Raised when an ingestion attempt should be retried later."""

    pass


class IngestionPermanentError(RuntimeError):
    """Raised when an ingestion attempt should be acknowledged and dropped."""

    pass


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse GitHub timestamp strings into timezone-aware datetimes."""

    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration_ms(started_at: datetime | None, completed_at: datetime | None) -> int | None:
    """Return execution duration in milliseconds when both timestamps exist."""

    if not started_at or not completed_at:
        return None
    return int((completed_at - started_at).total_seconds() * 1000)


def _parse_referenced_workflow(
    reference: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    """Split a referenced reusable workflow into repo, path, and ref parts."""

    if not reference:
        return None, None, None
    path = reference.get("path")
    ref = reference.get("ref")
    repo = None
    if path and path.count("/") >= 2:
        parts = path.split("/")
        repo = "/".join(parts[:2])
        path = "/".join(parts[2:]) if len(parts) > 2 else path
    return repo, path, ref


def build_ingestion_bundle(
    message: WebhookIngestionMessage,
    workflow_payload: dict[str, Any],
    jobs_pages: list[dict[str, Any]],
) -> IngestionBundle:
    """Normalize GitHub workflow and jobs payloads into persistence-ready records."""

    started_at = _parse_datetime(
        workflow_payload.get("run_started_at") or workflow_payload.get("created_at")
    )
    completed_at = _parse_datetime(workflow_payload.get("updated_at"))
    referenced = (workflow_payload.get("referenced_workflows") or [None])[0]
    referenced_repo, referenced_path, referenced_ref = _parse_referenced_workflow(referenced)

    raw_events = [
        RawIngestionEventRecord(
            source_type="workflow_run_api",
            repository_id=message.repository_id,
            run_id=message.run_id,
            run_attempt=message.run_attempt,
            correlation_id=message.correlation_id,
            payload=workflow_payload,
        )
    ]
    jobs: list[JobRunRecord] = []
    for page_number, page in enumerate(jobs_pages, start=1):
        raw_events.append(
            RawIngestionEventRecord(
                source_type="jobs_api",
                repository_id=message.repository_id,
                run_id=message.run_id,
                run_attempt=message.run_attempt,
                page_number=page_number,
                correlation_id=message.correlation_id,
                payload=page,
            )
        )
        for job_payload in page.get("jobs", []):
            job_started = _parse_datetime(job_payload.get("started_at"))
            job_completed = _parse_datetime(job_payload.get("completed_at"))
            steps: list[StepRunRecord] = []
            for step in job_payload.get("steps", []):
                step_started = _parse_datetime(step.get("started_at"))
                step_completed = _parse_datetime(step.get("completed_at"))
                steps.append(
                    StepRunRecord(
                        step_number=step.get("number"),
                        step_name=step.get("name", ""),
                        status=step.get("status"),
                        conclusion=step.get("conclusion"),
                        started_at=step_started,
                        completed_at=step_completed,
                        duration_ms=_duration_ms(step_started, step_completed),
                    )
                )
            jobs.append(
                JobRunRecord(
                    github_job_id=job_payload["id"],
                    job_name=job_payload.get("name", ""),
                    runner_name=job_payload.get("runner_name"),
                    status=job_payload.get("status"),
                    conclusion=job_payload.get("conclusion"),
                    started_at=job_started,
                    completed_at=job_completed,
                    duration_ms=_duration_ms(job_started, job_completed),
                    steps=steps,
                )
            )

    return IngestionBundle(
        repository=RepositoryRecord(
            github_repository_id=message.repository_id,
            full_name=message.repository_full_name,
            name=message.repository_full_name.split("/")[-1],
        ),
        workflow_run=WorkflowRunRecord(
            github_run_id=message.run_id,
            run_attempt=message.run_attempt,
            workflow_id=workflow_payload.get("workflow_id"),
            workflow_name=workflow_payload.get("name"),
            workflow_path=workflow_payload.get("path"),
            caller_workflow_path=workflow_payload.get("path"),
            referenced_workflow_repo=referenced_repo,
            referenced_workflow_path=referenced_path,
            referenced_workflow_ref=referenced_ref,
            head_branch=workflow_payload.get("head_branch"),
            head_sha=workflow_payload.get("head_sha"),
            actor_login=(workflow_payload.get("actor") or {}).get("login"),
            trigger_event=workflow_payload.get("event"),
            status=workflow_payload.get("status"),
            conclusion=workflow_payload.get("conclusion"),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=_duration_ms(started_at, completed_at),
        ),
        jobs=jobs,
        raw_events=raw_events,
    )


class IngestionService:
    """Own the worker ingestion flow from event message to database persistence."""

    def __init__(self, settings: Settings, github_client: GitHubClient, repository):
        self.settings = settings
        self.github_client = github_client
        self.repository = repository

    async def ingest(self, message: WebhookIngestionMessage) -> IngestionBundle:
        """Fetch, normalize, and persist one workflow execution from GitHub."""

        with tracer.start_as_current_span(
            "ingestion_service.ingest",
            kind=SpanKind.INTERNAL,
        ) as span:
            set_span_attributes(
                span,
                repository=message.repository_full_name,
                repository_id=message.repository_id,
                github_run_id=message.run_id,
                run_attempt=message.run_attempt,
                delivery_id=message.delivery_id,
                correlation_id=message.correlation_id,
            )
            await asyncio.sleep(self.settings.initial_fetch_delay_seconds)
            last_error: Exception | None = None
            try:
                installation_id = await self.github_client.installation_id_for_repo(
                    message.repository_full_name
                )
            except GitHubApiUnavailableError as exc:
                raise IngestionRetryableError("installation_lookup_unavailable") from exc
            except GitHubApiPermanentError as exc:
                raise IngestionPermanentError("installation_lookup_failed") from exc
            span.set_attribute("github_installation_id", installation_id)
            for attempt in range(1, self.settings.github_fetch_retry_attempts + 1):
                try:
                    with tracer.start_as_current_span(
                        "ingestion_attempt",
                        kind=SpanKind.INTERNAL,
                    ) as attempt_span:
                        set_span_attributes(attempt_span, retry_attempt=attempt)
                        workflow_payload = await self.github_client.get_workflow_run(
                            message.repository_full_name,
                            message.run_id,
                            installation_id,
                        )
                        jobs_pages = await self.github_client.list_jobs(
                            message.repository_full_name,
                            message.run_id,
                            installation_id,
                        )
                        bundle = build_ingestion_bundle(message, workflow_payload, jobs_pages)
                        with tracer.start_as_current_span(
                            "persist_bundle",
                            kind=SpanKind.INTERNAL,
                        ):
                            await self.repository.persist_bundle(bundle)
                        return bundle
                except GitHubApiUnavailableError as exc:
                    last_error = exc
                    logger.warning(
                        "github_api_unavailable",
                        extra={
                            "repository": message.repository_full_name,
                            "run_id": message.run_id,
                            "run_attempt": message.run_attempt,
                            "retry_attempt": attempt,
                        },
                    )
                    if attempt < self.settings.github_fetch_retry_attempts:
                        await asyncio.sleep(self.settings.github_fetch_retry_interval_seconds)
                except (GitHubApiPermanentError, SQLAlchemyError) as exc:
                    raise IngestionPermanentError("ingestion_failed_permanently") from exc
                except Exception as exc:
                    last_error = exc
                    break
            raise IngestionRetryableError("ingestion_failed_after_retries") from last_error
