from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from typing import Any

from .keys import (
    content_candidate_key,
    content_candidate_prefix,
    synthesis_prompt_state_key,
    synthesis_prompt_version_key,
    synthesis_prompt_version_prefix,
    synthesis_reference_key,
    synthesis_reference_prefix,
    upload_reservation_key,
)
from .models import (
    ArtifactKind,
    ContentCandidateRecord,
    ContentCandidateStatus,
    DerivedFrom,
    FileManifest,
    FileVersionMeta,
    RunEvent,
    RunManifest,
    RunStatus,
    RunStep,
    StoredSynthesisPromptState,
    SynthesisPromptState,
    SynthesisPromptVersion,
    SynthesisReferenceRecord,
    SynthesisReferenceStatus,
    UploadReservation,
)
from .r2_client import ObjectStore
from .refs import FileRef, FileVersionRef, RunRef
from .run_broadcast import RunUpdateBroadcaster
from .run_store import R2RunStore, RunStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_event_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class StorageRepository:
    def __init__(
        self,
        store: ObjectStore,
        *,
        run_store: RunStore | None = None,
        run_broadcaster: RunUpdateBroadcaster | None = None,
    ):
        self._store = store
        self._run_store = run_store or R2RunStore(store)
        self._run_broadcaster = run_broadcaster

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

    def save_file_manifest(self, manifest: FileManifest) -> FileManifest:
        self._store.put_json(
            FileRef(
                user_id=manifest.owner_user_id,
                file_id=manifest.file_id,
            ).manifest_key,
            manifest.model_dump(mode="json"),
        )
        return manifest

    def load_file_manifest(self, file_ref: FileRef) -> FileManifest:
        return FileManifest.model_validate(self._store.get_json(file_ref.manifest_key))

    def list_file_manifests(self, user_id: str) -> list[FileManifest]:
        prefix = f"users/{user_id}/files/"
        keys = [
            key
            for key in self._store.list_keys(prefix)
            if key.endswith("/manifest.json")
        ]
        manifests = [
            FileManifest.model_validate(self._store.get_json(key))
            for key in keys
        ]
        return sorted(manifests, key=lambda item: item.updated_at, reverse=True)

    def archive_file_manifest(
        self,
        file_ref: FileRef,
        *,
        reason: str = "user_deleted",
    ) -> FileManifest:
        manifest = self.load_file_manifest(file_ref)
        archived = manifest.model_copy(
            update={
                "archived_at": manifest.archived_at or _utc_now(),
                "archived_reason": reason,
                "updated_at": _utc_now(),
            }
        )
        return self.save_file_manifest(archived)

    def restore_file_manifest(self, file_ref: FileRef) -> FileManifest:
        manifest = self.load_file_manifest(file_ref)
        restored = manifest.model_copy(
            update={
                "archived_at": None,
                "archived_reason": None,
                "updated_at": _utc_now(),
            }
        )
        return self.save_file_manifest(restored)

    def delete_file_tree(self, file_ref: FileRef) -> None:
        prefix = f"users/{file_ref.user_id}/files/{file_ref.file_id}/"
        for key in self._store.list_keys(prefix):
            self._store.delete(key)

    def save_run_manifest(self, manifest: RunManifest) -> RunManifest:
        saved = self._run_store.save_run_manifest(manifest)
        self._broadcast_run_manifest(saved)
        return saved

    def load_run_manifest(self, run_ref: RunRef) -> RunManifest:
        return self._run_store.load_run_manifest(run_ref)

    def list_run_manifests(self, user_id: str) -> list[RunManifest]:
        return self._run_store.list_run_manifests(user_id)

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
        event = self._run_store.append_run_event(
            run_ref=run_ref,
            event_type=event_type,
            timestamp=timestamp,
            event_id=event_id,
            payload=payload,
        )
        self._broadcast_run_event(event)
        return event

    def append_run_progress(
        self,
        *,
        run_ref: RunRef,
        stage: str,
        percent: int,
        detail: str,
    ) -> RunEvent:
        try:
            manifest = self.load_run_manifest(run_ref)
            if manifest.status == "canceled":
                return RunEvent(
                    run_id=run_ref.run_id,
                    owner_user_id=run_ref.user_id,
                    event_type="progress",
                    timestamp=_utc_event_now(),
                    event_id=f"evt_progress_{uuid.uuid4().hex[:12]}",
                    payload={
                        "stage": stage,
                        "percent": max(0, min(100, int(percent))),
                        "detail": detail,
                    },
                )
        except KeyError:
            pass
        return self.append_run_event(
            run_ref=run_ref,
            event_type="progress",
            timestamp=_utc_event_now(),
            event_id=f"evt_progress_{uuid.uuid4().hex[:12]}",
            payload={
                "stage": stage,
                "percent": max(0, min(100, int(percent))),
                "detail": detail,
            },
        )

    def list_run_events(self, run_ref: RunRef) -> list[RunEvent]:
        return self._run_store.list_run_events(run_ref)

    def list_latest_run_progress(self, run_ref: RunRef) -> dict[str, dict[str, Any]]:
        return self._run_store.list_latest_run_progress(run_ref)

    def _broadcast_run_manifest(self, manifest: RunManifest) -> None:
        if self._run_broadcaster is None:
            return
        try:
            self._run_broadcaster.publish_run_manifest(manifest)
        except Exception:
            return

    def _broadcast_run_event(self, event: RunEvent) -> None:
        if self._run_broadcaster is None:
            return
        try:
            self._run_broadcaster.publish_run_event(event)
        except Exception:
            return

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
        version_ref = FileVersionRef(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
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

    def delete_upload_reservation(
        self,
        *,
        upload_id: str,
        user_id: str | None = None,
    ) -> None:
        try:
            reservation = UploadReservation.model_validate(
                self._store.get_json(upload_reservation_key(upload_id=upload_id))
            )
        except KeyError:
            return
        if user_id is not None and reservation.owner_user_id != user_id:
            raise PermissionError("upload reservation does not belong to user")
        if reservation.status == "completed":
            self._store.delete(upload_reservation_key(upload_id=upload_id))
            return
        self._store.delete(reservation.blob_key)
        self._store.delete(upload_reservation_key(upload_id=upload_id))
        file_ref = FileRef(user_id=reservation.owner_user_id, file_id=reservation.file_id)
        try:
            manifest = self.load_file_manifest(file_ref)
        except KeyError:
            return
        if manifest.current_version_id is None:
            self.delete_file_tree(file_ref)

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
        if head.size_bytes <= 0:
            self._store.delete(reservation.blob_key)
            raise ValueError("uploaded object is empty")
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
        try:
            manifest = self.load_file_manifest(file_ref)
        except KeyError:
            manifest = self.create_file_manifest(
                file_ref=file_ref,
                kind=reservation.kind,
                display_name=reservation.filename,
            )
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
        if manifest.status == "canceled" and status != "canceled":
            return manifest
        step_updates = manifest.steps
        if status == "completed":
            step_updates = [
                step.model_copy(update={"status": "completed"})
                for step in manifest.steps
            ]
        elif status == "running" and current_step is not None:
            seen_current = False
            next_steps = []
            for step in manifest.steps:
                if step.name == current_step:
                    seen_current = True
                    next_steps.append(step.model_copy(update={"status": "running"}))
                elif seen_current:
                    next_steps.append(step.model_copy(update={"status": "pending"}))
                else:
                    next_steps.append(step.model_copy(update={"status": "completed"}))
            step_updates = next_steps
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

    def archive_run(
        self,
        run_ref: RunRef,
        *,
        reason: str = "user_deleted",
    ) -> RunManifest:
        manifest = self.load_run_manifest(run_ref)
        archived = manifest.model_copy(
            update={
                "archived_at": manifest.archived_at or _utc_now(),
                "archived_reason": reason,
                "updated_at": _utc_now(),
            }
        )
        return self.save_run_manifest(archived)

    def restore_run(self, run_ref: RunRef) -> RunManifest:
        manifest = self.load_run_manifest(run_ref)
        restored = manifest.model_copy(
            update={
                "archived_at": None,
                "archived_reason": None,
                "updated_at": _utc_now(),
            }
        )
        return self.save_run_manifest(restored)

    def create_synthesis_reference(
        self,
        *,
        user_id: str,
        url: str,
        likes: int = 0,
        views: int = 0,
    ) -> SynthesisReferenceRecord:
        now = _utc_now()
        record = SynthesisReferenceRecord(
            reference_id=f"ref_{uuid.uuid4().hex[:12]}",
            owner_user_id=user_id,
            url=url,
            status="queued",
            likes=likes,
            views=views,
            created_at=now,
            updated_at=now,
        )
        return self.save_synthesis_reference(record)

    def save_synthesis_reference(
        self,
        record: SynthesisReferenceRecord,
    ) -> SynthesisReferenceRecord:
        self._store.put_json(
            synthesis_reference_key(
                user_id=record.owner_user_id,
                reference_id=record.reference_id,
            ),
            record.model_dump(mode="json"),
        )
        return record

    def load_synthesis_reference(
        self,
        *,
        user_id: str,
        reference_id: str,
    ) -> SynthesisReferenceRecord:
        return SynthesisReferenceRecord.model_validate(
            self._store.get_json(
                synthesis_reference_key(user_id=user_id, reference_id=reference_id)
            )
        )

    def update_synthesis_reference(
        self,
        *,
        user_id: str,
        reference_id: str,
        status: SynthesisReferenceStatus,
        title: str | None = None,
        author: str | None = None,
        duration_sec: float | None = None,
        metrics: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> SynthesisReferenceRecord:
        current = self.load_synthesis_reference(
            user_id=user_id,
            reference_id=reference_id,
        )
        update: dict[str, Any] = {
            "status": status,
            "updated_at": _utc_now(),
            "last_error": last_error,
        }
        if title is not None:
            update["title"] = title
        if author is not None:
            update["author"] = author
        if duration_sec is not None:
            update["duration_sec"] = duration_sec
        if metrics is not None:
            update["metrics"] = metrics
        return self.save_synthesis_reference(current.model_copy(update=update))

    def list_synthesis_references(self, user_id: str) -> list[SynthesisReferenceRecord]:
        keys = self._store.list_keys(synthesis_reference_prefix(user_id=user_id))
        records = [
            SynthesisReferenceRecord.model_validate(self._store.get_json(key))
            for key in keys
        ]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def upsert_content_candidate(
        self,
        record: ContentCandidateRecord,
    ) -> ContentCandidateRecord:
        try:
            existing = self.load_content_candidate(
                user_id=record.owner_user_id,
                candidate_id=record.candidate_id,
            )
        except KeyError:
            candidate = record
        else:
            candidate = record.model_copy(
                update={
                    "status": existing.status,
                    "created_at": existing.created_at,
                }
            )
        return self.save_content_candidate(candidate)

    def save_content_candidate(
        self,
        record: ContentCandidateRecord,
    ) -> ContentCandidateRecord:
        self._store.put_json(
            content_candidate_key(
                user_id=record.owner_user_id,
                candidate_id=record.candidate_id,
            ),
            record.model_dump(mode="json"),
        )
        return record

    def load_content_candidate(
        self,
        *,
        user_id: str,
        candidate_id: str,
    ) -> ContentCandidateRecord:
        return ContentCandidateRecord.model_validate(
            self._store.get_json(
                content_candidate_key(user_id=user_id, candidate_id=candidate_id)
            )
        )

    def list_content_candidates(self, user_id: str) -> list[ContentCandidateRecord]:
        keys = self._store.list_keys(content_candidate_prefix(user_id=user_id))
        records = [
            ContentCandidateRecord.model_validate(self._store.get_json(key))
            for key in keys
        ]
        return sorted(records, key=lambda item: (item.score, item.updated_at), reverse=True)

    def update_content_candidate_status(
        self,
        *,
        user_id: str,
        candidate_id: str,
        status: ContentCandidateStatus,
    ) -> ContentCandidateRecord:
        record = self.load_content_candidate(
            user_id=user_id,
            candidate_id=candidate_id,
        )
        return self.save_content_candidate(
            record.model_copy(
                update={
                    "status": status,
                    "updated_at": _utc_now(),
                }
            )
        )

    def default_synthesis_prompt_version(
        self,
        *,
        user_id: str,
        prompt_text: str,
    ) -> SynthesisPromptVersion:
        return SynthesisPromptVersion(
            version_id="default",
            owner_user_id=user_id,
            label="Baseline prompt",
            prompt_text=prompt_text,
            generated_guidance="",
            source_reference_ids=[],
            created_at="system",
        )

    def list_synthesis_prompt_versions(
        self,
        *,
        user_id: str,
        default_prompt_text: str,
    ) -> list[SynthesisPromptVersion]:
        versions = [
            self.default_synthesis_prompt_version(
                user_id=user_id,
                prompt_text=default_prompt_text,
            )
        ]
        keys = self._store.list_keys(synthesis_prompt_version_prefix(user_id=user_id))
        versions.extend(
            SynthesisPromptVersion.model_validate(self._store.get_json(key))
            for key in keys
        )
        return sorted(
            versions,
            key=lambda item: "0000" if item.version_id == "default" else item.created_at,
            reverse=True,
        )

    def get_synthesis_prompt_state(
        self,
        *,
        user_id: str,
        default_prompt_text: str,
    ) -> SynthesisPromptState:
        versions = self.list_synthesis_prompt_versions(
            user_id=user_id,
            default_prompt_text=default_prompt_text,
        )
        try:
            stored = StoredSynthesisPromptState.model_validate(
                self._store.get_json(synthesis_prompt_state_key(user_id=user_id))
            )
            active_version_id = stored.active_version_id
        except KeyError:
            active_version_id = "default"
        active = next(
            (version for version in versions if version.version_id == active_version_id),
            versions[-1],
        )
        return SynthesisPromptState(
            owner_user_id=user_id,
            active_version_id=active.version_id,
            active_prompt=active,
            versions=versions,
        )

    def create_synthesis_prompt_version(
        self,
        *,
        user_id: str,
        label: str,
        prompt_text: str,
        generated_guidance: str = "",
        source_reference_ids: list[str] | None = None,
        activate: bool = True,
    ) -> SynthesisPromptVersion:
        version = SynthesisPromptVersion(
            version_id=f"prompt_{uuid.uuid4().hex[:12]}",
            owner_user_id=user_id,
            label=label,
            prompt_text=prompt_text,
            generated_guidance=generated_guidance,
            source_reference_ids=list(source_reference_ids or []),
            created_at=_utc_now(),
        )
        self._store.put_json(
            synthesis_prompt_version_key(
                user_id=user_id,
                version_id=version.version_id,
            ),
            version.model_dump(mode="json"),
        )
        if activate:
            self.activate_synthesis_prompt_version(user_id=user_id, version_id=version.version_id)
        return version

    def activate_synthesis_prompt_version(
        self,
        *,
        user_id: str,
        version_id: str,
    ) -> StoredSynthesisPromptState:
        state = StoredSynthesisPromptState(
            owner_user_id=user_id,
            active_version_id=version_id,
        )
        self._store.put_json(
            synthesis_prompt_state_key(user_id=user_id),
            state.model_dump(mode="json"),
        )
        return state
