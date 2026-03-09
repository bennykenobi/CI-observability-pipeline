import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from shared.db.models import JobRun, RawIngestionEvent, Repository, StepRun, WorkflowRun
from shared.db.session import SessionLocal
from shared.schemas import IngestionBundle, WebhookIngestionMessage


class IngestionRepository:
    async def persist_webhook_event(self, message: WebhookIngestionMessage, payload: dict) -> None:
        with SessionLocal.begin() as session:
            self._upsert_raw_event(
                session,
                source_type="webhook",
                repository_id=message.repository_id,
                run_id=message.run_id,
                run_attempt=message.run_attempt,
                page_number=None,
                correlation_id=message.correlation_id,
                payload=payload,
                fetched_at=datetime.now(UTC),
            )

    async def persist_bundle(self, bundle: IngestionBundle) -> None:
        with SessionLocal.begin() as session:
            repository_id = self._upsert_repository(session, bundle)
            workflow_run_id = self._upsert_workflow_run(session, bundle, repository_id)
            for job in bundle.jobs:
                job_run_id = self._upsert_job_run(session, workflow_run_id, job)
                for step in job.steps:
                    self._upsert_step_run(session, job_run_id, step)
            for raw_event in bundle.raw_events:
                self._upsert_raw_event(
                    session,
                    source_type=raw_event.source_type,
                    repository_id=raw_event.repository_id,
                    run_id=raw_event.run_id,
                    run_attempt=raw_event.run_attempt,
                    page_number=raw_event.page_number,
                    correlation_id=raw_event.correlation_id,
                    payload=raw_event.payload,
                    fetched_at=raw_event.fetched_at,
                )

    def _upsert_repository(self, session, bundle: IngestionBundle) -> int:
        stmt = (
            insert(Repository)
            .values(
                github_repository_id=bundle.repository.github_repository_id,
                full_name=bundle.repository.full_name,
                name=bundle.repository.name,
            )
            .on_conflict_do_update(
                index_elements=[Repository.github_repository_id],
                set_={
                    "full_name": bundle.repository.full_name,
                    "name": bundle.repository.name,
                },
            )
            .returning(Repository.id)
        )
        return session.execute(stmt).scalar_one()

    def _upsert_workflow_run(self, session, bundle: IngestionBundle, repository_id: int) -> int:
        values = bundle.workflow_run.model_dump()
        stmt = (
            insert(WorkflowRun)
            .values(repository_id=repository_id, **values)
            .on_conflict_do_update(
                index_elements=[WorkflowRun.repository_id, WorkflowRun.github_run_id, WorkflowRun.run_attempt],
                set_=values,
            )
            .returning(WorkflowRun.id)
        )
        return session.execute(stmt).scalar_one()

    def _upsert_job_run(self, session, workflow_run_id: int, job) -> int:
        values = job.model_dump(exclude={"steps"})
        stmt = (
            insert(JobRun)
            .values(workflow_run_id=workflow_run_id, **values)
            .on_conflict_do_update(
                index_elements=[JobRun.github_job_id],
                set_={**values, "workflow_run_id": workflow_run_id},
            )
            .returning(JobRun.id)
        )
        return session.execute(stmt).scalar_one()

    def _upsert_step_run(self, session, job_run_id: int, step) -> None:
        values = step.model_dump()
        stmt = insert(StepRun).values(job_run_id=job_run_id, **values).on_conflict_do_update(
            index_elements=[StepRun.job_run_id, StepRun.step_number],
            set_=values,
        )
        session.execute(stmt)

    def _upsert_raw_event(
        self,
        session,
        *,
        source_type: str,
        repository_id: int,
        run_id: int,
        run_attempt: int,
        page_number: int | None,
        correlation_id: str,
        payload: dict,
        fetched_at: datetime,
    ) -> None:
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        stmt = insert(RawIngestionEvent).values(
            source_type=source_type,
            repository_id=repository_id,
            run_id=run_id,
            run_attempt=run_attempt,
            page_number=page_number,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            payload=payload,
            fetched_at=fetched_at,
        ).on_conflict_do_nothing()
        session.execute(stmt)
