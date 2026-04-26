import json
import asyncio

from api.storage.models import RunEvent, RunManifest
from api.storage.redis_run_broadcast import RedisRunUpdateBroadcaster


class FakeRedisClient:
    def __init__(self):
        self.published = []

    def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


def test_redis_broadcaster_publishes_manifest_to_user_and_run_channels():
    client = FakeRedisClient()
    broadcaster = RedisRunUpdateBroadcaster(sync_client=client)
    manifest = RunManifest(
        run_id="run_123",
        owner_user_id="user_123",
        workflow_type="edit_pipeline",
        status="running",
        inputs={"title": "Live"},
        outputs={},
        steps=[],
        current_step=None,
        last_error=None,
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:00:01Z",
    )

    broadcaster.publish_run_manifest(manifest)

    assert client.published == [
        (
            "eclypte:runs:user:user_123",
            {"type": "run_manifest", "run": manifest.model_dump(mode="json")},
        ),
        (
            "eclypte:runs:user:user_123:run:run_123",
            {"type": "run_manifest", "run": manifest.model_dump(mode="json")},
        ),
    ]


def test_redis_broadcaster_publishes_events_to_user_and_run_channels():
    client = FakeRedisClient()
    broadcaster = RedisRunUpdateBroadcaster(sync_client=client)
    event = RunEvent(
        event_id="evt_123",
        run_id="run_123",
        owner_user_id="user_123",
        event_type="progress",
        timestamp="2026-04-21T19:00:02Z",
        payload={"stage": "render", "percent": 80, "detail": "Encoding"},
    )

    broadcaster.publish_run_event(event)

    assert [channel for channel, _ in client.published] == [
        "eclypte:runs:user:user_123",
        "eclypte:runs:user:user_123:run:run_123",
    ]
    assert client.published[0][1] == {
        "type": "run_event",
        "event": event.model_dump(mode="json"),
    }


def test_redis_broadcaster_listen_yields_messages_and_heartbeats():
    asyncio.run(_assert_redis_broadcaster_listen_yields_messages_and_heartbeats())


async def _assert_redis_broadcaster_listen_yields_messages_and_heartbeats():
    broadcaster = RedisRunUpdateBroadcaster(
        sync_client=FakeRedisClient(),
        async_client=FakeAsyncRedisClient(
            [
                None,
                {
                    "type": "message",
                    "data": json.dumps({"type": "heartbeat", "timestamp": "from-redis"}),
                },
            ]
        ),
        heartbeat_seconds=0,
    )
    stream = broadcaster.listen(user_id="user_123", run_id="run_123")

    heartbeat = await anext(stream)
    message = await anext(stream)
    await stream.aclose()

    assert heartbeat["type"] == "heartbeat"
    assert message == {"type": "heartbeat", "timestamp": "from-redis"}


class FakeAsyncRedisClient:
    def __init__(self, messages):
        self.messages = messages
        self.pubsub_instance = FakePubSub(messages)

    def pubsub(self):
        return self.pubsub_instance


class FakePubSub:
    def __init__(self, messages):
        self.messages = list(messages)
        self.subscribed = []
        self.closed = False

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def get_message(self, *, ignore_subscribe_messages, timeout):
        if self.messages:
            return self.messages.pop(0)
        raise StopAsyncIteration

    async def unsubscribe(self, channel):
        pass

    async def close(self):
        self.closed = True
