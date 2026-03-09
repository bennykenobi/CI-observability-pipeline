import hashlib
import hmac
import json
from concurrent.futures import Future

from fastapi.testclient import TestClient

from services.webhook_service.app import create_app
from shared.config import Settings
from shared.pubsub import GooglePubSubPublisher, resolve_topic_path


class RecordingPublisher:
    def __init__(self):
        self.messages = []

    async def publish(self, topic: str, message: dict) -> None:
        self.messages.append((topic, message))


class RecordingRepository:
    def __init__(self):
        self.events = []
        self.deliveries = set()

    async def register_webhook_delivery(
        self,
        *,
        delivery_id,
        event_type,
        repository_id,
        run_id,
    ) -> bool:
        key = (delivery_id, event_type, repository_id, run_id)
        if key in self.deliveries:
            return False
        self.deliveries.add(key)
        return True

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


def test_duplicate_delivery_is_ignored_before_publish():
    publisher = RecordingPublisher()
    repository = RecordingRepository()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher, repository=repository))
    payload = {
        "action": "completed",
        "repository": {"id": 1, "full_name": "org/repo"},
        "workflow_run": {"id": 99, "run_attempt": 1},
        "installation": {"id": 777},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": _signature("secret", body),
    }

    first = client.post("/github/webhook", content=body, headers=headers)
    second = client.post("/github/webhook", content=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert len(publisher.messages) == 1


def test_webhook_payload_limit_rejects_large_body():
    publisher = RecordingPublisher()
    repository = RecordingRepository()
    settings = Settings(webhook_secret="secret", max_webhook_body_bytes=8)
    client = TestClient(create_app(settings=settings, publisher=publisher, repository=repository))
    body = json.dumps({"action": "completed"}).encode("utf-8")

    response = client.post(
        "/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 413


def test_topic_path_resolution_supports_short_and_fully_qualified_names():
    settings = Settings(gcp_project_id="example-project")

    assert resolve_topic_path(settings, "ci-observability-ingestion") == (
        "projects/example-project/topics/ci-observability-ingestion"
    )
    assert (
        resolve_topic_path(settings, "projects/other/topics/custom")
        == "projects/other/topics/custom"
    )


class RecordingPubSubClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic_path, data, **attrs):
        self.calls.append((topic_path, data, attrs))
        future = Future()
        future.set_result("message-id")
        return future


def test_google_pubsub_publisher_publishes_expected_payload():
    settings = Settings(gcp_project_id="example-project")
    client = RecordingPubSubClient()
    publisher = GooglePubSubPublisher(settings, client=client)

    import asyncio

    asyncio.run(
        publisher.publish(
            "ci-observability-ingestion",
            {"event_type": "workflow_run_completed", "run_id": 42},
        )
    )

    assert client.calls[0][0] == "projects/example-project/topics/ci-observability-ingestion"
    assert json.loads(client.calls[0][1].decode("utf-8"))["run_id"] == 42
    assert client.calls[0][2]["event_type"] == "workflow_run_completed"
