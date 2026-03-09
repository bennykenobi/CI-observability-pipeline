from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, status

from shared.config import Settings, get_settings
from shared.db.repository import IngestionRepository
from shared.github import GitHubClient
from shared.ingestion import IngestionService
from shared.logging import configure_logging
from shared.otel import configure_tracing, get_tracer, set_span_attributes, span_kind_server
from shared.schemas import PubSubMessageEnvelope, WebhookIngestionMessage

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


def create_app(
    settings: Settings | None = None,
    ingestion_service: IngestionService | None = None,
) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()
    configure_tracing(app_settings, "ci-observability-worker")
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
        with tracer.start_as_current_span("pubsub_ingest", kind=span_kind_server()) as span:
            try:
                encoded = envelope.message.get("data", "")
                set_span_attributes(
                    span,
                    http_route="/pubsub/ingest",
                    encoded_body_size_bytes=len(encoded),
                    trace_context=x_cloud_trace_context,
                )
                logger.info(
                    "pubsub_message_received",
                    extra={
                        "encoded_body_size_bytes": len(encoded),
                        "trace_context": x_cloud_trace_context,
                    },
                )
                message = WebhookIngestionMessage.model_validate(
                    envelope.decode_data(max_bytes=app_settings.max_pubsub_body_bytes)
                )
                set_span_attributes(
                    span,
                    repository=message.repository_full_name,
                    repository_id=message.repository_id,
                    run_id=message.run_id,
                    run_attempt=message.run_attempt,
                    delivery_id=message.delivery_id,
                    correlation_id=message.correlation_id,
                )
                now = datetime.now(UTC)
                if now - message.sent_at > timedelta(
                    seconds=app_settings.max_ingestion_message_age_seconds
                ):
                    logger.warning(
                        "workflow_ingestion_skipped_stale_message",
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
                    span.set_attribute("ingestion.skipped_stale", True)
                    return
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
                        "pubsub_topic": app_settings.pubsub_topic,
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
