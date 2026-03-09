from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import ValidationError

from shared.config import Settings, get_settings
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
) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()
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

        try:
            message = WebhookIngestionMessage.model_validate(json.loads(body))
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid observability event payload",
            ) from exc
        if message.event_type != "workflow_run_completed":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}
        if message.action != "completed":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}
        await _get_publisher(app).publish(
            app_settings.pubsub_topic,
            message.model_dump(mode="json"),
        )
        logger.info(
            "workflow_callback_enqueued",
            extra={
                "repository": message.repository_full_name,
                "repository_id": message.repository_id,
                "run_id": message.run_id,
                "run_attempt": message.run_attempt,
                "event_type": message.event_type,
                "delivery_id": message.delivery_id,
                "correlation_id": message.correlation_id,
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
