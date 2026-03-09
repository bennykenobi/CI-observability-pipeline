import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from services.webhook_service.app import create_app
from shared.config import Settings


class RecordingPublisher:
    def __init__(self):
        self.messages = []

    async def publish(self, topic: str, message: dict) -> None:
        self.messages.append((topic, message))


class RecordingRepository:
    def __init__(self):
        self.events = []

    async def persist_webhook_event(self, message, payload) -> None:
        self.events.append((message, payload))


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_completed_workflow_run_is_published():
    publisher = RecordingPublisher()
    repository = RecordingRepository()
    settings = Settings(webhook_secret="secret", repository_allowlist=["org/repo"])
    client = TestClient(create_app(settings=settings, publisher=publisher, repository=repository))
    payload = {
        "action": "completed",
        "repository": {"id": 1, "full_name": "org/repo"},
        "workflow_run": {"id": 99, "run_attempt": 2},
        "installation": {"id": 777},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 202
    assert publisher.messages[0][0] == settings.pubsub_topic
    assert publisher.messages[0][1]["repository_full_name"] == "org/repo"
    assert publisher.messages[0][1]["run_attempt"] == 2
    assert repository.events[0][0].run_id == 99


def test_non_completed_event_is_ignored():
    publisher = RecordingPublisher()
    repository = RecordingRepository()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher, repository=repository))
    payload = {
        "action": "requested",
        "repository": {"id": 1, "full_name": "org/repo"},
        "workflow_run": {"id": 99, "run_attempt": 1},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert publisher.messages == []
    assert repository.events == []
