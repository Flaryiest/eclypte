import pytest

from api.storage.keys import file_version_blob_key
from api.storage.refs import FileRef, RunRef
from api.storage.test_fakes import InMemoryObjectStore


def test_repository_creates_and_completes_direct_upload_reservation():
    from api.storage.repository import StorageRepository

    store = InMemoryObjectStore()
    repo = StorageRepository(store)

    reservation = repo.create_upload_reservation(
        user_id="user_123",
        kind="song_audio",
        filename="song.wav",
        content_type="audio/wav",
        size_bytes=4,
    )

    file_ref = FileRef(user_id="user_123", file_id=reservation.file_id)
    with pytest.raises(KeyError):
        repo.load_file_manifest(file_ref)
    assert reservation.blob_key == file_version_blob_key(
        user_id="user_123",
        file_id=reservation.file_id,
        version_id=reservation.version_id,
    )

    store.put_bytes(reservation.blob_key, b"song", content_type="audio/wav")
    version_ref = repo.complete_upload_reservation(
        upload_id=reservation.upload_id,
        sha256="a" * 64,
    )

    manifest = repo.load_file_manifest(file_ref)
    meta = repo.load_file_version_meta(version_ref)
    completed = repo.load_upload_reservation("user_123", reservation.upload_id)

    assert manifest.current_version_id == reservation.version_id
    assert meta.size_bytes == 4
    assert meta.sha256 == "a" * 64
    assert meta.original_filename == "song.wav"
    assert completed.status == "completed"


def test_repository_deletes_incomplete_upload_reservation_and_staged_blob():
    from api.storage.repository import StorageRepository

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    reservation = repo.create_upload_reservation(
        user_id="user_123",
        kind="source_video",
        filename="source.mp4",
        content_type="video/mp4",
        size_bytes=5,
    )
    store.put_bytes(reservation.blob_key, b"video", content_type="video/mp4")

    repo.delete_upload_reservation(upload_id=reservation.upload_id, user_id="user_123")

    with pytest.raises(KeyError):
        repo.load_upload_reservation("user_123", reservation.upload_id)
    assert reservation.blob_key not in store.objects


def test_repository_upload_cleanup_does_not_delete_completed_asset_blob():
    from api.storage.repository import StorageRepository

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    reservation = repo.create_upload_reservation(
        user_id="user_123",
        kind="song_audio",
        filename="song.wav",
        content_type="audio/wav",
        size_bytes=4,
    )
    store.put_bytes(reservation.blob_key, b"song", content_type="audio/wav")
    repo.complete_upload_reservation(
        upload_id=reservation.upload_id,
        sha256="a" * 64,
        user_id="user_123",
    )

    repo.delete_upload_reservation(upload_id=reservation.upload_id, user_id="user_123")

    manifest = repo.load_file_manifest(FileRef(user_id="user_123", file_id=reservation.file_id))
    assert manifest.current_version_id == reservation.version_id
    assert reservation.blob_key in store.objects


def test_repository_rejects_empty_upload_without_creating_visible_asset():
    from api.storage.repository import StorageRepository

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    reservation = repo.create_upload_reservation(
        user_id="user_123",
        kind="song_audio",
        filename="empty.wav",
        content_type="audio/wav",
        size_bytes=1,
    )
    store.put_bytes(reservation.blob_key, b"", content_type="audio/wav")

    with pytest.raises(ValueError, match="empty"):
        repo.complete_upload_reservation(
            upload_id=reservation.upload_id,
            sha256="a" * 64,
            user_id="user_123",
        )

    with pytest.raises(KeyError):
        repo.load_file_manifest(FileRef(user_id="user_123", file_id=reservation.file_id))


def test_repository_updates_run_status_outputs_and_events():
    from api.storage.repository import StorageRepository

    repo = StorageRepository(InMemoryObjectStore())
    run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": "ver_audio"},
        steps=["analyze_music", "publish_analysis"],
    )

    updated = repo.update_run_status(
        RunRef(user_id="user_123", run_id=run.run_id),
        status="completed",
        current_step=None,
        outputs={"music_analysis_version_id": "ver_analysis"},
    )
    repo.append_run_event(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        event_type="run_completed",
        timestamp=updated.updated_at,
        event_id="evt_done",
        payload={"ok": True},
    )

    loaded = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    events = repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))

    assert loaded.status == "completed"
    assert loaded.outputs["music_analysis_version_id"] == "ver_analysis"
    assert [step.status for step in loaded.steps] == ["completed", "completed"]
    assert events[0].event_type == "run_completed"


def test_repository_appends_run_progress_events():
    from api.storage.repository import StorageRepository

    repo = StorageRepository(InMemoryObjectStore())
    run = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={"audio_version_id": "ver_audio"},
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )

    event = repo.append_run_progress(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        stage="music",
        percent=45,
        detail="Analyzing beats",
    )

    events = repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
    assert event.event_type == "progress"
    assert events[0].payload == {
        "stage": "music",
        "percent": 45,
        "detail": "Analyzing beats",
    }
    assert repo.list_latest_run_progress(
        RunRef(user_id="user_123", run_id=run.run_id)
    )["music"]["percent"] == 45


def test_canceled_run_ignores_later_status_and_progress_updates():
    from api.storage.repository import StorageRepository

    repo = StorageRepository(InMemoryObjectStore())
    run = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={"audio_version_id": "ver_audio"},
        steps=["assets", "music", "video"],
    )
    repo.append_run_progress(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        stage="music",
        percent=20,
        detail="Analyzing",
    )
    canceled = repo.update_run_status(
        RunRef(user_id="user_123", run_id=run.run_id),
        status="canceled",
        current_step="music",
    )
    ignored = repo.update_run_status(
        RunRef(user_id="user_123", run_id=run.run_id),
        status="completed",
        outputs={"render_output_file_id": "file_render"},
    )
    repo.append_run_progress(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        stage="music",
        percent=90,
        detail="Late worker update",
    )

    latest = repo.list_latest_run_progress(RunRef(user_id="user_123", run_id=run.run_id))

    assert canceled.status == "canceled"
    assert ignored.status == "canceled"
    assert "render_output_file_id" not in ignored.outputs
    assert latest["music"]["percent"] == 20


def test_repository_records_existing_blob_version_written_by_worker():
    from api.storage.repository import StorageRepository

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    file_ref = FileRef(user_id="user_123", file_id="file_render")
    repo.create_file_manifest(
        file_ref=file_ref,
        kind="render_output",
        display_name="output.mp4",
        source_run_id="run_render",
    )
    version_ref = repo.reserve_file_version(file_ref)
    store.put_bytes(version_ref.blob_key, b"mp4", content_type="video/mp4")

    repo.record_existing_version(
        file_ref=file_ref,
        version_ref=version_ref,
        content_type="video/mp4",
        size_bytes=3,
        sha256="d" * 64,
        original_filename="output.mp4",
        created_by_step="render",
        derived_from_step="render",
        input_file_version_ids=["ver_timeline", "ver_audio", "ver_source"],
        derived_from_run_id="run_render",
    )

    manifest = repo.load_file_manifest(file_ref)
    meta = repo.load_file_version_meta(version_ref)

    assert manifest.current_version_id == version_ref.version_id
    assert meta.storage_key == version_ref.blob_key
    assert meta.derived_from.input_file_version_ids == [
        "ver_timeline",
        "ver_audio",
        "ver_source",
    ]
