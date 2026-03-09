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


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_completed_custom_event_is_published():
    publisher = RecordingPublisher()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher))
    payload = {
        "event_type": "workflow_run_completed",
        "action": "completed",
        "delivery_id": "delivery-1",
        "repository_id": 1,
        "repository_full_name": "org/repo",
        "run_id": 99,
        "run_attempt": 2,
        "installation_id": 777,
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/workflow/callback",
        content=body,
        headers={
            "X-Observability-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 202
    assert publisher.messages[0][0] == settings.pubsub_topic
    assert publisher.messages[0][1]["repository_full_name"] == "org/repo"
    assert publisher.messages[0][1]["run_attempt"] == 2
    assert publisher.messages[0][1]["run_id"] == 99


def test_non_completed_event_is_ignored():
    publisher = RecordingPublisher()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher))
    payload = {
        "event_type": "workflow_run_completed",
        "action": "queued",
        "delivery_id": "delivery-1",
        "repository_id": 1,
        "repository_full_name": "org/repo",
        "run_id": 99,
        "run_attempt": 1,
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/workflow/callback",
        content=body,
        headers={
            "X-Observability-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert publisher.messages == []

def test_unsupported_custom_event_is_ignored():
    publisher = RecordingPublisher()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher))
    payload = {
        "event_type": "not_supported",
        "action": "completed",
        "delivery_id": "delivery-1",
        "repository_id": 1,
        "repository_full_name": "org/repo",
        "run_id": 99,
        "run_attempt": 1,
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/workflow/callback",
        content=body,
        headers={
            "X-Observability-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert publisher.messages == []


def test_webhook_payload_limit_rejects_large_body():
    publisher = RecordingPublisher()
    settings = Settings(
        webhook_secret="secret",
        max_webhook_body_bytes=8,
    )
    client = TestClient(create_app(settings=settings, publisher=publisher))
    body = json.dumps({"action": "completed"}).encode("utf-8")

    response = client.post(
        "/workflow/callback",
        content=body,
        headers={
            "X-Observability-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 413


def test_custom_event_requires_expected_fields():
    publisher = RecordingPublisher()
    settings = Settings(webhook_secret="secret")
    client = TestClient(create_app(settings=settings, publisher=publisher))
    body = json.dumps({"action": "completed", "delivery_id": "delivery-1"}).encode("utf-8")

    response = client.post(
        "/workflow/callback",
        content=body,
        headers={
            "X-Observability-Signature-256": _signature("secret", body),
        },
    )

    assert response.status_code == 422


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
