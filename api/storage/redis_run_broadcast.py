from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
import json
import time
from typing import Any

from .models import RunEvent, RunManifest

DEFAULT_HEARTBEAT_SECONDS = 15
RUN_CHANNEL_PREFIX = "eclypte:runs:user"


class RedisRunUpdateBroadcaster:
    def __init__(
        self,
        *,
        sync_client,
        async_client=None,
        heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS,
    ):
        self._sync_client = sync_client
        self._async_client = async_client
        self._heartbeat_seconds = heartbeat_seconds

    @classmethod
    def from_url(cls, redis_url: str) -> "RedisRunUpdateBroadcaster":
        import redis
        import redis.asyncio as redis_async

        return cls(
            sync_client=redis.Redis.from_url(redis_url, decode_responses=True),
            async_client=redis_async.Redis.from_url(redis_url, decode_responses=True),
        )

    def publish_run_manifest(self, manifest: RunManifest) -> None:
        payload = {
            "type": "run_manifest",
            "run": manifest.model_dump(mode="json"),
        }
        self._publish(manifest.owner_user_id, manifest.run_id, payload)

    def publish_run_event(self, event: RunEvent) -> None:
        payload = {
            "type": "run_event",
            "event": event.model_dump(mode="json"),
        }
        self._publish(event.owner_user_id, event.run_id, payload)

    async def listen(
        self,
        *,
        user_id: str,
        run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._async_client is None:
            raise RuntimeError("async Redis client is not configured")
        channel = _run_channel(user_id, run_id) if run_id else _user_channel(user_id)
        pubsub = self._async_client.pubsub()
        await pubsub.subscribe(channel)
        last_heartbeat = 0.0
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message:
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    if isinstance(data, str):
                        yield json.loads(data)
                now = time.monotonic()
                if now - last_heartbeat >= self._heartbeat_seconds:
                    last_heartbeat = now
                    yield {
                        "type": "heartbeat",
                        "timestamp": _utc_now(),
                    }
        finally:
            await pubsub.unsubscribe(channel)
            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    def _publish(self, user_id: str, run_id: str, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, separators=(",", ":"))
        self._sync_client.publish(_user_channel(user_id), message)
        self._sync_client.publish(_run_channel(user_id, run_id), message)


def _user_channel(user_id: str) -> str:
    return f"{RUN_CHANNEL_PREFIX}:{user_id}"


def _run_channel(user_id: str, run_id: str) -> str:
    return f"{_user_channel(user_id)}:run:{run_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
