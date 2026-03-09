import base64
import json

from fastapi.testclient import TestClient

from services.ingestion_worker.app import create_app
from shared.config import Settings
from shared.schemas import WebhookIngestionMessage


class RecordingIngestionService:
    def __init__(self):
        self.messages = []

    async def ingest(self, message: WebhookIngestionMessage):
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
        installation_id=99,
    ).model_dump(mode="json")

    response = client.post(
        "/pubsub/ingest",
        json={"message": {"data": base64.b64encode(json.dumps(message).encode("utf-8")).decode("utf-8")}},
    )

    assert response.status_code == 204
    assert ingestion_service.messages[0].run_id == 11
