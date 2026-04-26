from dataclasses import dataclass
import json
from typing import Any

from .models import RunEvent, RunManifest
from .r2_client import ObjectHead
from .refs import RunRef


@dataclass
class _StoredObject:
    body: bytes
    content_type: str | None
    metadata: dict[str, str]


class InMemoryObjectStore:
    def __init__(self):
        self.objects: dict[str, _StoredObject] = {}

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.objects[key] = _StoredObject(
            body=data,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key].body

    def put_json(self, key: str, data: dict) -> None:
        self.put_bytes(
            key,
            json.dumps(data, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def get_json(self, key: str) -> dict:
        return json.loads(self.get_bytes(key).decode("utf-8"))

    def head(self, key: str) -> ObjectHead:
        obj = self.objects[key]
        return ObjectHead(
            key=key,
            size_bytes=len(obj.body),
            content_type=obj.content_type,
            metadata=obj.metadata,
            etag="memory-etag",
        )

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def presigned_put_url(
        self,
        key: str,
        *,
        content_type: str,
        expires_in: int,
    ) -> str:
        return f"memory://put/{key}?content_type={content_type}&expires_in={expires_in}"

    def presigned_get_url(self, key: str, *, expires_in: int) -> str:
        return f"memory://get/{key}?expires_in={expires_in}"


class InMemoryRunStore:
    def __init__(self):
        self.manifests: dict[tuple[str, str], RunManifest] = {}
        self.events: dict[tuple[str, str], dict[str, RunEvent]] = {}
        self.latest_progress: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def save_run_manifest(self, manifest: RunManifest) -> RunManifest:
        self.manifests[(manifest.owner_user_id, manifest.run_id)] = manifest
        return manifest

    def load_run_manifest(self, run_ref: RunRef) -> RunManifest:
        return self.manifests[(run_ref.user_id, run_ref.run_id)]

    def list_run_manifests(self, user_id: str) -> list[RunManifest]:
        runs = [
            manifest
            for (owner_user_id, _), manifest in self.manifests.items()
            if owner_user_id == user_id
        ]
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def append_run_event(
        self,
        *,
        run_ref: RunRef,
        event_type: str,
        timestamp: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> RunEvent:
        event = RunEvent(
            event_id=event_id,
            run_id=run_ref.run_id,
            owner_user_id=run_ref.user_id,
            event_type=event_type,
            timestamp=timestamp,
            payload=payload,
        )
        bucket = self.events.setdefault((run_ref.user_id, run_ref.run_id), {})
        bucket.setdefault(event_id, event)
        if event_type == "progress":
            stage = str(payload.get("stage") or "")
            if stage:
                latest = self.latest_progress.setdefault((run_ref.user_id, run_ref.run_id), {})
                current = latest.get(stage)
                if current is None or str(current.get("timestamp", "")) <= timestamp:
                    latest[stage] = {
                        **payload,
                        "timestamp": timestamp,
                        "event_id": event_id,
                    }
        return event

    def list_run_events(self, run_ref: RunRef) -> list[RunEvent]:
        events = list(self.events.get((run_ref.user_id, run_ref.run_id), {}).values())
        return sorted(events, key=lambda item: (item.timestamp, item.event_id))

    def list_latest_run_progress(self, run_ref: RunRef) -> dict[str, dict[str, Any]]:
        return dict(self.latest_progress.get((run_ref.user_id, run_ref.run_id), {}))
