from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from shared.config import Settings, get_settings
from shared.db.repository import IngestionRepository
from shared.logging import configure_logging
from shared.pubsub import LoggingPublisher, Publisher, publish_ingestion_message
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
    app_publisher = publisher or LoggingPublisher()
    app_repository = repository or IngestionRepository()
    app = FastAPI(title="CI Observability Webhook Service")

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
        if not hmac.compare_digest(_signature(app_settings.webhook_secret, body), x_hub_signature_256):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

        payload = json.loads(body)
        repository = payload.get("repository", {})
        repository_full_name = repository.get("full_name", "")
        action = payload.get("action")
        workflow_run = payload.get("workflow_run", {})

        if x_github_event != "workflow_run" or action != "completed":
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}

        if app_settings.repository_allowlist and repository_full_name not in app_settings.repository_allowlist:
            response.status_code = status.HTTP_200_OK
            return {"status": "ignored"}

        message = WebhookIngestionMessage(
            action=action,
            delivery_id=x_github_delivery,
            repository_id=repository["id"],
            repository_full_name=repository_full_name,
            run_id=workflow_run["id"],
            run_attempt=workflow_run.get("run_attempt", 1),
            installation_id=(payload.get("installation") or {}).get("id"),
        )
        await app_repository.persist_webhook_event(message, payload)
        await publish_ingestion_message(app_publisher, app_settings.pubsub_topic, message)
        logger.info(
            "workflow_run_enqueued",
            extra={
                "repository": repository_full_name,
                "repository_id": repository["id"],
                "run_id": workflow_run["id"],
                "run_attempt": workflow_run.get("run_attempt", 1),
                "event_type": x_github_event,
                "delivery_id": x_github_delivery,
                "correlation_id": message.correlation_id,
            },
        )
        return {"status": "accepted"}

    return app


app = create_app()
