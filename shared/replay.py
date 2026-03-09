"""Replay-protection stores for duplicate delivery detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol


class ReplayStore(Protocol):
    """Register a delivery identifier and report whether it is new."""

    def register(self, delivery_id: str, expires_at: datetime) -> bool: ...


class InMemoryReplayStore:
    """Single-process replay store for local development and tests."""

    def __init__(self) -> None:
        self._entries: dict[str, datetime] = {}
        self._lock = Lock()

    def register(self, delivery_id: str, expires_at: datetime) -> bool:
        """Store a delivery ID until expiry and reject duplicates in the same process."""

        now = datetime.now(UTC)
        with self._lock:
            expired = [key for key, value in self._entries.items() if value <= now]
            for key in expired:
                del self._entries[key]
            if delivery_id in self._entries:
                return False
            self._entries[delivery_id] = expires_at
            return True


@dataclass(slots=True)
class RedisReplayStore:
    """Redis-backed replay store for multi-instance deployments."""

    client: object
    key_prefix: str = "ci-obs:replay"

    def register(self, delivery_id: str, expires_at: datetime) -> bool:
        """Atomically claim a delivery ID in Redis using a TTL-backed key."""

        ttl_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
        if ttl_seconds <= 0:
            return False
        result = self.client.set(
            self._key(delivery_id),
            "1",
            ex=ttl_seconds,
            nx=True,
        )
        return bool(result)

    def _key(self, delivery_id: str) -> str:
        """Build the namespaced Redis key for one delivery identifier."""

        return f"{self.key_prefix}:{delivery_id}"


def create_replay_store(settings) -> ReplayStore:
    """Create the configured replay store, defaulting to in-memory behavior."""

    if not settings.replay_store_url:
        return InMemoryReplayStore()

    try:
        from redis import Redis
    except ImportError as exc:
        raise RuntimeError(
            "CI_OBS_REPLAY_STORE_URL is set but the redis dependency is not installed"
        ) from exc

    client = Redis.from_url(settings.replay_store_url, decode_responses=True)
    return RedisReplayStore(
        client=client,
        key_prefix=settings.replay_store_key_prefix,
    )
