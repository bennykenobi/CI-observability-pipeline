"""FastAPI webhook listener for authenticated custom observability events."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from shared.config import Settings, get_settings
from shared.logging import configure_logging
from shared.otel import configure_tracing, get_tracer, set_span_attributes
from shared.pubsub import GooglePubSubPublisher, Publisher
from shared.replay import ReplayStore, create_replay_store
from shared.schemas import WebhookIngestionMessage

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


def _signature(secret: str, body: bytes) -> str:
    """Return the expected HMAC signature header value for a request body."""

    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _validate_request_size(body: bytes, settings: Settings) -> None:
    """Reject callback bodies that exceed the configured maximum size."""

    if len(body) > settings.max_webhook_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Payload too large",
        )


def _validate_request_auth(
    *,
    body: bytes,
    settings: Settings,
    signature: str,
    auth_token: str,
) -> None:
    """Validate the callback signature and secondary auth token headers."""

    if not hmac.compare_digest(
        _signature(settings.webhook_secret, body),
        signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )
    if not hmac.compare_digest(
        settings.webhook_auth_token,
        auth_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


def _parse_message(body: bytes) -> WebhookIngestionMessage:
    """Parse and validate the webhook payload into the event contract model."""

    try:
        return WebhookIngestionMessage.model_validate(json.loads(body))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid observability event payload",
        ) from exc


def _validate_message_freshness(message: WebhookIngestionMessage, settings: Settings) -> None:
    """Reject callbacks that fall outside the accepted replay window."""

    now = datetime.now(UTC)
    if message.sent_at > now + timedelta(seconds=settings.webhook_future_skew_seconds):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Event timestamp is too far in the future",
        )
    if now - message.sent_at > timedelta(seconds=settings.webhook_max_age_seconds):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Event timestamp is outside the allowed window",
        )


def _register_delivery(
    message: WebhookIngestionMessage,
    replay_store: ReplayStore,
    settings: Settings,
) -> None:
    """Register the delivery ID and reject duplicates within the replay window."""

    if not replay_store.register(
        message.delivery_id,
        message.sent_at + timedelta(seconds=settings.webhook_max_age_seconds),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate delivery",
        )


def _should_ignore_message(message: WebhookIngestionMessage) -> bool:
    """Return true when the event should be acknowledged but not queued."""

    return (
        message.event_type != "workflow_run_completed"
        or message.action != "completed"
    )


def create_app(
    settings: Settings | None = None,
    publisher: Publisher | None = None,
    replay_store: ReplayStore | None = None,
) -> FastAPI:
    """Create the webhook FastAPI application with injected test doubles when provided."""

    configure_logging()
    app_settings = settings or get_settings()
    configure_tracing(app_settings, "ci-observability-webhook")
    app = FastAPI(title="CI Observability Webhook Service")
    app.state.publisher = publisher
    app.state.settings = app_settings
    app.state.replay_store = replay_store or create_replay_store(app_settings)

    @app.get("/healthz", status_code=status.HTTP_200_OK)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/workflow/callback", status_code=status.HTTP_202_ACCEPTED)
    async def workflow_callback(
        request: Request,
        response: Response,
        x_observability_signature_256: str = Header(default=""),
        x_observability_token: str = Header(default=""),
    ) -> dict[str, str]:
        with tracer.start_as_current_span(
            "workflow_callback",
            kind=SpanKind.SERVER,
        ) as span:
            body = await request.body()
            set_span_attributes(
                span,
                http_method=request.method,
                http_route="/workflow/callback",
                body_size_bytes=len(body),
            )
            logger.info(
                "workflow_callback_received",
                extra={"body_size_bytes": len(body)},
            )
            _validate_request_size(body, app_settings)
            _validate_request_auth(
                body=body,
                settings=app_settings,
                signature=x_observability_signature_256,
                auth_token=x_observability_token,
            )
            message = _parse_message(body)
            set_span_attributes(
                span,
                repository=message.repository_full_name,
                repository_id=message.repository_id,
                run_id=message.run_id,
                run_attempt=message.run_attempt,
                delivery_id=message.delivery_id,
                correlation_id=message.correlation_id,
                event_type=message.event_type,
            )
            _validate_message_freshness(message, app_settings)
            _register_delivery(message, app.state.replay_store, app_settings)
            if _should_ignore_message(message):
                response.status_code = status.HTTP_200_OK
                return {"status": "ignored"}
            with tracer.start_as_current_span(
                "pubsub_publish",
                kind=SpanKind.CLIENT,
            ) as publish_span:
                set_span_attributes(
                    publish_span,
                    pubsub_topic=app_settings.pubsub_topic,
                    delivery_id=message.delivery_id,
                    correlation_id=message.correlation_id,
                )
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
    """Return the cached Pub/Sub publisher, creating the default instance on demand."""

    publisher = app.state.publisher
    if publisher is not None:
        return publisher
    settings: Settings = app.state.settings
    publisher = GooglePubSubPublisher(settings)
    app.state.publisher = publisher
    return publisher


app = create_app()
