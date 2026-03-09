from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from shared.config import Settings, get_settings
from shared.db.repository import IngestionRepository
from shared.logging import configure_logging
from shared.pubsub import GooglePubSubPublisher, Publisher
from shared.schemas import WebhookIngestionMessage

logger = logging.getLogger(__name__)


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def create_app(
    settings: Settings | None = None,
    publisher: Publisher | None = None,
    repository: IngestionRepository | None = None,
) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()
    app_repository = repository or IngestionRepository()
    app = FastAPI(title="CI Observability Webhook Service")
    app.state.publisher = publisher
    app.state.settings = app_settings

    @app.get("/healthz", status_code=status.HTTP_200_OK)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/workflow/callback", status_code=status.HTTP_202_ACCEPTED)
    async def workflow_callback(
        request: Request,
        response: Response,
        x_observability_signature_256: str = Header(default=""),
    ) -> dict[str, str]:
        body = await request.body()
        logger.info(
            "workflow_callback_received",
            extra={"body_size_bytes": len(body)},
        )
        if len(body) > app_settings.max_webhook_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Payload too large",
            )
        if not hmac.compare_digest(
            _signature(app_settings.webhook_secret, body),
            x_observability_signature_256,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )

        payload = WebhookIngestionMessage.model_validate(json.loads(body))

        if payload.event_type != "workflow_run_completed":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}

        if (
            app_settings.repository_allowlist
            and payload.repository_full_name not in app_settings.repository_allowlist
        ):
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}

        accepted = await app_repository.register_webhook_delivery(
            delivery_id=payload.delivery_id,
            event_type=payload.event_type,
            repository_id=payload.repository_id,
            run_id=payload.run_id,
        )
        if not accepted:
            response.status_code = status.HTTP_200_OK
            logger.info(
                "duplicate_workflow_callback_ignored",
                extra={
                    "delivery_id": payload.delivery_id,
                    "repository_id": payload.repository_id,
                    "run_id": payload.run_id,
                },
            )
            return {"status": "duplicate"}

        await app_repository.persist_webhook_event(payload, payload.model_dump(mode="json"))
        await _get_publisher(app).publish(
            app_settings.pubsub_topic,
            payload.model_dump(mode="json"),
        )
        logger.info(
            "workflow_callback_enqueued",
            extra={
                "repository": payload.repository_full_name,
                "repository_id": payload.repository_id,
                "run_id": payload.run_id,
                "run_attempt": payload.run_attempt,
                "event_type": payload.event_type,
                "delivery_id": payload.delivery_id,
                "correlation_id": payload.correlation_id,
                "body_size_bytes": len(body),
            },
        )
        return {"status": "accepted"}

    return app


def _get_publisher(app: FastAPI) -> Publisher:
    publisher = app.state.publisher
    if publisher is not None:
        return publisher
    settings: Settings = app.state.settings
    publisher = GooglePubSubPublisher(settings)
    app.state.publisher = publisher
    return publisher


app = create_app()
