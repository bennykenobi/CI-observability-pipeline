"""Pub/Sub publishing utilities used by the webhook listener."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Protocol

from shared.config import Settings

logger = logging.getLogger(__name__)


class Publisher(Protocol):
    """Minimal async publishing contract used for dependency injection in tests."""

    async def publish(self, topic: str, message: dict) -> None: ...


def resolve_topic_path(settings: Settings, topic: str) -> str:
    """Return a fully-qualified Pub/Sub topic path for a short or full topic name."""

    if topic.startswith("projects/"):
        return topic
    project_id = (
        settings.gcp_project_id
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
    )
    if not project_id:
        raise RuntimeError("GCP project ID is required to publish to Pub/Sub")
    return f"projects/{project_id}/topics/{topic}"


class GooglePubSubPublisher:
    """Publish compact ingestion messages to Google Cloud Pub/Sub."""

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client or self._create_client()

    @staticmethod
    def _create_client() -> Any:
        """Create the default Pub/Sub publisher client lazily at runtime."""

        from google.cloud import pubsub_v1

        return pubsub_v1.PublisherClient()

    async def publish(self, topic: str, message: dict) -> None:
        """Serialize and publish one ingestion message to the configured topic."""

        topic_path = resolve_topic_path(self.settings, topic)
        data = json.dumps(message).encode("utf-8")
        future = self.client.publish(
            topic_path,
            data,
            event_type=str(message.get("event_type", "")),
        )
        await asyncio.wrap_future(future)
        logger.info(
            "published_pubsub_message",
            extra={"topic": topic_path, "event_type": message.get("event_type")},
        )
