from __future__ import annotations

from typing import Any, Protocol

from .keys import run_event_key, run_manifest_key
from .models import RunEvent, RunManifest
from .r2_client import ObjectStore
from .refs import RunRef


class RunStore(Protocol):
    def save_run_manifest(self, manifest: RunManifest) -> RunManifest: ...
    def load_run_manifest(self, run_ref: RunRef) -> RunManifest: ...
    def list_run_manifests(self, user_id: str) -> list[RunManifest]: ...

    def append_run_event(
        self,
        *,
        run_ref: RunRef,
        event_type: str,
        timestamp: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> RunEvent: ...

    def list_run_events(self, run_ref: RunRef) -> list[RunEvent]: ...
    def list_latest_run_progress(self, run_ref: RunRef) -> dict[str, dict[str, Any]]: ...


class R2RunStore:
    def __init__(self, store: ObjectStore):
        self._store = store

    def save_run_manifest(self, manifest: RunManifest) -> RunManifest:
        self._store.put_json(
            run_manifest_key(user_id=manifest.owner_user_id, run_id=manifest.run_id),
            manifest.model_dump(mode="json"),
        )
        return manifest

    def load_run_manifest(self, run_ref: RunRef) -> RunManifest:
        return RunManifest.model_validate(self._store.get_json(run_ref.manifest_key))

    def list_run_manifests(self, user_id: str) -> list[RunManifest]:
        prefix = f"users/{user_id}/runs/"
        keys = [
            key
            for key in self._store.list_keys(prefix)
            if key.endswith("/manifest.json")
        ]
        runs = [
            RunManifest.model_validate(self._store.get_json(key))
            for key in keys
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
        key = run_event_key(
            user_id=run_ref.user_id,
            run_id=run_ref.run_id,
            timestamp=timestamp,
            event_id=event_id,
        )
        self._store.put_json(key, event.model_dump(mode="json"))
        return event

    def list_run_events(self, run_ref: RunRef) -> list[RunEvent]:
        prefix = f"users/{run_ref.user_id}/runs/{run_ref.run_id}/events/"
        keys = sorted(self._store.list_keys(prefix))
        return [RunEvent.model_validate(self._store.get_json(key)) for key in keys]

    def list_latest_run_progress(self, run_ref: RunRef) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self.list_run_events(run_ref):
            if event.event_type != "progress":
                continue
            stage = str(event.payload.get("stage", ""))
            if stage:
                latest[stage] = {
                    **event.payload,
                    "timestamp": event.timestamp,
                    "event_id": event.event_id,
                }
        return latest
