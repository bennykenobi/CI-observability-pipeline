from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, status

from shared.config import Settings, get_settings
from shared.db.repository import IngestionRepository
from shared.github import GitHubClient
from shared.ingestion import IngestionService
from shared.logging import configure_logging
from shared.schemas import PubSubMessageEnvelope, WebhookIngestionMessage


logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    ingestion_service: IngestionService | None = None,
) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()
    app_ingestion_service = ingestion_service or IngestionService(
        settings=app_settings,
        github_client=GitHubClient(app_settings),
        repository=IngestionRepository(),
    )
    app = FastAPI(title="CI Observability Ingestion Worker")

    @app.get("/healthz", status_code=status.HTTP_200_OK)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/pubsub/ingest", status_code=status.HTTP_204_NO_CONTENT)
    async def pubsub_ingest(
        envelope: PubSubMessageEnvelope,
        x_cloud_trace_context: str | None = Header(default=None),
    ) -> None:
        try:
            message = WebhookIngestionMessage.model_validate(envelope.decode_data())
            await app_ingestion_service.ingest(message)
            logger.info(
                "workflow_run_ingested",
                extra={
                    "repository": message.repository_full_name,
                    "repository_id": message.repository_id,
                    "run_id": message.run_id,
                    "run_attempt": message.run_attempt,
                    "delivery_id": message.delivery_id,
                    "trace_context": x_cloud_trace_context,
                    "correlation_id": message.correlation_id,
                },
            )
        except Exception as exc:
            logger.exception(
                "workflow_ingestion_failed",
                extra={"failure_reason": str(exc), "trace_context": x_cloud_trace_context},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ingestion failed; allow Pub/Sub retry / DLQ policy to handle delivery",
            ) from exc

    return app


app = create_app()
