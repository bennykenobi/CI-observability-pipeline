import logging
from typing import Protocol

from shared.schemas import WebhookIngestionMessage


logger = logging.getLogger(__name__)


class Publisher(Protocol):
    async def publish(self, topic: str, message: dict) -> None: ...


class LoggingPublisher:
    async def publish(self, topic: str, message: dict) -> None:
        logger.info(
            "published_pubsub_message",
            extra={"topic": topic, "event_type": message.get("event_type"), "payload": message},
        )


async def publish_ingestion_message(
    publisher: Publisher,
    topic: str,
    payload: WebhookIngestionMessage,
) -> None:
    await publisher.publish(topic, payload.model_dump(mode="json"))
