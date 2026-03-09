from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

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

    @app.post("/github/webhook", status_code=status.HTTP_202_ACCEPTED)
    async def github_webhook(
        request: Request,
        response: Response,
        x_github_event: str = Header(default=""),
        x_github_delivery: str = Header(default=""),
        x_hub_signature_256: str = Header(default=""),
    ) -> dict[str, str]:
        body = await request.body()
        logger.info(
            "github_webhook_received",
            extra={
                "body_size_bytes": len(body),
                "github_event": x_github_event,
                "delivery_id": x_github_delivery,
            },
        )
        if len(body) > app_settings.max_webhook_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Payload too large",
            )
        if not hmac.compare_digest(
            _signature(app_settings.webhook_secret, body),
            x_hub_signature_256,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )

        payload = json.loads(body)
        if x_github_event != "workflow_run":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}
        if payload.get("action") != "completed":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}

        repository = payload.get("repository") or {}
        workflow_run = payload.get("workflow_run") or {}
        installation = payload.get("installation") or {}
        if (
            not repository.get("id")
            or not repository.get("full_name")
            or not workflow_run.get("id")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required workflow_run webhook fields",
            )

        message = WebhookIngestionMessage(
            event_type="workflow_run_completed",
            action="completed",
            delivery_id=x_github_delivery or workflow_run.get("id"),
            repository_id=repository["id"],
            repository_full_name=repository["full_name"],
            run_id=workflow_run["id"],
            run_attempt=workflow_run.get("run_attempt", 1),
            installation_id=installation.get("id"),
        )
        await _get_publisher(app).publish(
            app_settings.pubsub_topic,
            message.model_dump(mode="json"),
        )
        logger.info(
            "workflow_run_webhook_enqueued",
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
