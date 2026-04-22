from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any

from .keys import run_event_key, run_manifest_key
from .models import DerivedFrom, FileManifest, FileVersionMeta, RunEvent, RunManifest
from .r2_client import ObjectStore
from .refs import FileRef, FileVersionRef, RunRef


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StorageRepository:
    def __init__(self, store: ObjectStore):
        self._store = store

    def create_file_manifest(
        self,
        *,
        file_ref: FileRef,
        kind: str,
        display_name: str,
    ) -> FileManifest:
        now = _utc_now()
        manifest = FileManifest(
            file_id=file_ref.file_id,
            owner_user_id=file_ref.user_id,
            kind=kind,
            current_version_id=None,
            source_run_id=None,
            display_name=display_name,
            created_at=now,
            updated_at=now,
            tags=[],
        )
        self._store.put_json(file_ref.manifest_key, manifest.model_dump(mode="json"))
        return manifest

    def load_file_manifest(self, file_ref: FileRef) -> FileManifest:
        return FileManifest.model_validate(self._store.get_json(file_ref.manifest_key))

    def save_run_manifest(self, manifest: RunManifest) -> RunManifest:
        key = run_manifest_key(user_id=manifest.owner_user_id, run_id=manifest.run_id)
        self._store.put_json(key, manifest.model_dump(mode="json"))
        return manifest

    def load_run_manifest(self, run_ref: RunRef) -> RunManifest:
        return RunManifest.model_validate(self._store.get_json(run_ref.manifest_key))

    def publish_bytes(
        self,
        *,
        file_ref: FileRef,
        body: bytes,
        content_type: str,
        original_filename: str,
        created_by_step: str,
        derived_from_step: str,
        input_file_version_ids: list[str],
    ) -> FileVersionRef:
        version_id = f"ver_{uuid.uuid4().hex[:12]}"
        version_ref = FileVersionRef(
            user_id=file_ref.user_id,
            file_id=file_ref.file_id,
            version_id=version_id,
        )
        sha256 = hashlib.sha256(body).hexdigest()
        self._store.put_bytes(version_ref.blob_key, body, content_type=content_type)

        meta = FileVersionMeta(
            version_id=version_id,
            file_id=file_ref.file_id,
            owner_user_id=file_ref.user_id,
            content_type=content_type,
            size_bytes=len(body),
            sha256=sha256,
            original_filename=original_filename,
            created_at=_utc_now(),
            created_by_step=created_by_step,
            storage_key=version_ref.blob_key,
            derived_from=DerivedFrom(
                run_id=None,
                step_id=derived_from_step,
                input_file_version_ids=input_file_version_ids,
                params_hash=None,
            ),
        )
        self._store.put_json(version_ref.meta_key, meta.model_dump(mode="json"))

        manifest = self.load_file_manifest(file_ref)
        promoted = manifest.model_copy(
            update={
                "current_version_id": version_id,
                "updated_at": _utc_now(),
            }
        )
        self._store.put_json(file_ref.manifest_key, promoted.model_dump(mode="json"))
        return version_ref

    def publish_json(
        self,
        *,
        file_ref: FileRef,
        data: dict[str, Any],
        original_filename: str,
        created_by_step: str,
        derived_from_step: str,
        input_file_version_ids: list[str],
    ) -> FileVersionRef:
        body = json.dumps(data, indent=2).encode("utf-8")
        return self.publish_bytes(
            file_ref=file_ref,
            body=body,
            content_type="application/json",
            original_filename=original_filename,
            created_by_step=created_by_step,
            derived_from_step=derived_from_step,
            input_file_version_ids=input_file_version_ids,
        )

    def load_file_version_meta(self, version_ref: FileVersionRef) -> FileVersionMeta:
        return FileVersionMeta.model_validate(self._store.get_json(version_ref.meta_key))

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
        keys = self._store.list_keys(prefix)
        return [RunEvent.model_validate(self._store.get_json(key)) for key in keys]
