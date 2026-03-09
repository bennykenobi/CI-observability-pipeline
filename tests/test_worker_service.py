import base64
import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from services.ingestion_worker.app import create_app
from shared.config import Settings
from shared.schemas import WebhookIngestionMessage


class RecordingIngestionService:
    def __init__(self):
        self.messages = []
        self.raise_error = False

    async def ingest(self, message: WebhookIngestionMessage):
        if self.raise_error:
            raise RuntimeError("boom")
        self.messages.append(message)


def test_worker_decodes_pubsub_message_and_invokes_ingestion():
    ingestion_service = RecordingIngestionService()
    client = TestClient(create_app(settings=Settings(), ingestion_service=ingestion_service))
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-1",
        repository_id=1,
        repository_full_name="org/repo",
        run_id=11,
        run_attempt=1,
        sent_at=datetime.now(UTC),
    ).model_dump(mode="json")

    response = client.post(
        "/pubsub/ingest",
        json={
            "message": {
                "data": base64.b64encode(json.dumps(message).encode("utf-8")).decode("utf-8")
            }
        },
    )

    assert response.status_code == 204
    assert ingestion_service.messages[0].run_id == 11


def test_worker_rejects_oversized_pubsub_message():
    ingestion_service = RecordingIngestionService()
    client = TestClient(
        create_app(
            settings=Settings(max_pubsub_body_bytes=4),
            ingestion_service=ingestion_service,
        )
    )

    response = client.post(
        "/pubsub/ingest",
        json={
            "message": {
                "data": base64.b64encode(
                    json.dumps({"run_id": 11}).encode("utf-8")
                ).decode("utf-8")
            }
        },
    )

    assert response.status_code == 500
    assert ingestion_service.messages == []


def test_worker_returns_500_when_ingestion_fails():
    ingestion_service = RecordingIngestionService()
    ingestion_service.raise_error = True
    client = TestClient(create_app(settings=Settings(), ingestion_service=ingestion_service))
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-1",
        repository_id=1,
        repository_full_name="org/repo",
        run_id=11,
        run_attempt=1,
        sent_at=datetime.now(UTC),
    ).model_dump(mode="json")

    response = client.post(
        "/pubsub/ingest",
        json={
            "message": {
                "data": base64.b64encode(json.dumps(message).encode("utf-8")).decode("utf-8")
            }
        },
    )

    assert response.status_code == 500


def test_worker_acknowledges_stale_pubsub_message_without_ingesting():
    ingestion_service = RecordingIngestionService()
    client = TestClient(
        create_app(
            settings=Settings(max_ingestion_message_age_seconds=60),
            ingestion_service=ingestion_service,
        )
    )
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-old",
        repository_id=1,
        repository_full_name="org/repo",
        run_id=11,
        run_attempt=1,
        sent_at=datetime.now(UTC) - timedelta(hours=1),
    ).model_dump(mode="json")

    response = client.post(
        "/pubsub/ingest",
        json={
            "message": {
                "data": base64.b64encode(json.dumps(message).encode("utf-8")).decode("utf-8")
            }
        },
    )

    assert response.status_code == 204
    assert ingestion_service.messages == []
