from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from typing import Any

from .keys import run_event_key, run_manifest_key, upload_reservation_key
from .models import (
    ArtifactKind,
    DerivedFrom,
    FileManifest,
    FileVersionMeta,
    RunEvent,
    RunManifest,
    RunStatus,
    RunStep,
    UploadReservation,
)
from .r2_client import ObjectStore
from .refs import FileRef, FileVersionRef, RunRef


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class StorageRepository:
    def __init__(self, store: ObjectStore):
        self._store = store

    def create_file_manifest(
        self,
        *,
        file_ref: FileRef,
        kind: str,
        display_name: str,
        source_run_id: str | None = None,
    ) -> FileManifest:
        now = _utc_now()
        manifest = FileManifest(
            file_id=file_ref.file_id,
            owner_user_id=file_ref.user_id,
            kind=kind,
            current_version_id=None,
            source_run_id=source_run_id,
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
        derived_from_run_id: str | None = None,
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
                run_id=derived_from_run_id,
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
        derived_from_run_id: str | None = None,
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
            derived_from_run_id=derived_from_run_id,
        )

    def load_file_version_meta(self, version_ref: FileVersionRef) -> FileVersionMeta:
        return FileVersionMeta.model_validate(self._store.get_json(version_ref.meta_key))

    def read_version_bytes(self, version_ref: FileVersionRef) -> bytes:
        return self._store.get_bytes(version_ref.blob_key)

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

    def create_upload_reservation(
        self,
        *,
        user_id: str,
        kind: ArtifactKind,
        filename: str,
        content_type: str,
        size_bytes: int | None = None,
        expires_in: int = 900,
    ) -> UploadReservation:
        upload_id = f"upl_{uuid.uuid4().hex[:12]}"
        file_id = f"file_{uuid.uuid4().hex[:12]}"
        version_id = f"ver_{uuid.uuid4().hex[:12]}"
        file_ref = FileRef(user_id=user_id, file_id=file_id)
        version_ref = FileVersionRef(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )
        self.create_file_manifest(
            file_ref=file_ref,
            kind=kind,
            display_name=filename,
        )
        now = _utc_now()
        reservation = UploadReservation(
            upload_id=upload_id,
            owner_user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            kind=kind,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            blob_key=version_ref.blob_key,
            status="created",
            created_at=now,
            expires_at=_utc_after(expires_in),
        )
        self._store.put_json(
            upload_reservation_key(upload_id=upload_id),
            reservation.model_dump(mode="json"),
        )
        return reservation

    def load_upload_reservation(
        self,
        user_id: str,
        upload_id: str,
    ) -> UploadReservation:
        reservation = UploadReservation.model_validate(
            self._store.get_json(upload_reservation_key(upload_id=upload_id))
        )
        if reservation.owner_user_id != user_id:
            raise PermissionError("upload reservation does not belong to user")
        return reservation

    def complete_upload_reservation(
        self,
        *,
        upload_id: str,
        sha256: str,
        user_id: str | None = None,
    ) -> FileVersionRef:
        reservation = UploadReservation.model_validate(
            self._store.get_json(upload_reservation_key(upload_id=upload_id))
        )
        if user_id is not None and reservation.owner_user_id != user_id:
            raise PermissionError("upload reservation does not belong to user")
        try:
            head = self._store.head(reservation.blob_key)
        except KeyError as exc:
            raise ValueError("uploaded object has not been uploaded") from exc
        if reservation.size_bytes is not None and head.size_bytes != reservation.size_bytes:
            raise ValueError(
                f"uploaded object size {head.size_bytes} did not match "
                f"expected size {reservation.size_bytes}"
            )

        version_ref = FileVersionRef(
            user_id=reservation.owner_user_id,
            file_id=reservation.file_id,
            version_id=reservation.version_id,
        )
        meta = FileVersionMeta(
            version_id=reservation.version_id,
            file_id=reservation.file_id,
            owner_user_id=reservation.owner_user_id,
            content_type=head.content_type or reservation.content_type,
            size_bytes=head.size_bytes,
            sha256=sha256,
            original_filename=reservation.filename,
            created_at=_utc_now(),
            created_by_step="direct_upload",
            storage_key=reservation.blob_key,
            derived_from=DerivedFrom(
                run_id=None,
                step_id="direct_upload",
                input_file_version_ids=[],
                params_hash=None,
            ),
        )
        self._store.put_json(version_ref.meta_key, meta.model_dump(mode="json"))

        file_ref = FileRef(
            user_id=reservation.owner_user_id,
            file_id=reservation.file_id,
        )
        manifest = self.load_file_manifest(file_ref)
        promoted = manifest.model_copy(
            update={
                "current_version_id": reservation.version_id,
                "updated_at": _utc_now(),
            }
        )
        self._store.put_json(file_ref.manifest_key, promoted.model_dump(mode="json"))

        completed = reservation.model_copy(
            update={"status": "completed", "completed_at": _utc_now()}
        )
        self._store.put_json(
            upload_reservation_key(upload_id=upload_id),
            completed.model_dump(mode="json"),
        )
        return version_ref

    def reserve_file_version(self, file_ref: FileRef) -> FileVersionRef:
        return FileVersionRef(
            user_id=file_ref.user_id,
            file_id=file_ref.file_id,
            version_id=f"ver_{uuid.uuid4().hex[:12]}",
        )

    def record_existing_version(
        self,
        *,
        file_ref: FileRef,
        version_ref: FileVersionRef,
        content_type: str,
        size_bytes: int,
        sha256: str,
        original_filename: str,
        created_by_step: str,
        derived_from_step: str,
        input_file_version_ids: list[str],
        derived_from_run_id: str | None = None,
    ) -> FileVersionRef:
        meta = FileVersionMeta(
            version_id=version_ref.version_id,
            file_id=file_ref.file_id,
            owner_user_id=file_ref.user_id,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            original_filename=original_filename,
            created_at=_utc_now(),
            created_by_step=created_by_step,
            storage_key=version_ref.blob_key,
            derived_from=DerivedFrom(
                run_id=derived_from_run_id,
                step_id=derived_from_step,
                input_file_version_ids=input_file_version_ids,
                params_hash=None,
            ),
        )
        self._store.put_json(version_ref.meta_key, meta.model_dump(mode="json"))
        manifest = self.load_file_manifest(file_ref)
        promoted = manifest.model_copy(
            update={
                "current_version_id": version_ref.version_id,
                "updated_at": _utc_now(),
            }
        )
        self._store.put_json(file_ref.manifest_key, promoted.model_dump(mode="json"))
        return version_ref

    def create_run(
        self,
        *,
        user_id: str,
        workflow_type: str,
        inputs: dict[str, str],
        steps: list[str],
    ) -> RunManifest:
        now = _utc_now()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        manifest = RunManifest(
            run_id=run_id,
            owner_user_id=user_id,
            workflow_type=workflow_type,
            status="running",
            inputs=inputs,
            outputs={},
            steps=[
                RunStep(
                    name=step,
                    status="running" if index == 0 else "pending",
                )
                for index, step in enumerate(steps)
            ],
            current_step=steps[0] if steps else None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        return self.save_run_manifest(manifest)

    def update_run_status(
        self,
        run_ref: RunRef,
        *,
        status: RunStatus,
        current_step: str | None = None,
        outputs: dict[str, str] | None = None,
        last_error: str | None = None,
    ) -> RunManifest:
        manifest = self.load_run_manifest(run_ref)
        step_updates = manifest.steps
        if status == "completed":
            step_updates = [
                step.model_copy(update={"status": "completed"})
                for step in manifest.steps
            ]
        elif status == "failed":
            failed_step = current_step or manifest.current_step
            step_updates = [
                step.model_copy(
                    update={
                        "status": "failed"
                        if step.name == failed_step
                        else step.status
                    }
                )
                for step in manifest.steps
            ]

        updated = manifest.model_copy(
            update={
                "status": status,
                "current_step": current_step,
                "outputs": {**manifest.outputs, **(outputs or {})},
                "last_error": last_error,
                "steps": step_updates,
                "updated_at": _utc_now(),
            }
        )
        return self.save_run_manifest(updated)
