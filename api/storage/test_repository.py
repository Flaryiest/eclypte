from api.storage.models import RunManifest
from api.storage.refs import FileRef, RunRef
from api.storage.test_fakes import InMemoryObjectStore


def test_publish_bytes_writes_blob_meta_and_promotes_current_version():
    from api.storage.repository import StorageRepository

    repo = StorageRepository(InMemoryObjectStore())
    file_ref = FileRef(user_id="user_123", file_id="file_001")

    repo.create_file_manifest(
        file_ref=file_ref,
        kind="source_video",
        display_name="source.mp4",
    )
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=b"video",
        content_type="video/mp4",
        original_filename="source.mp4",
        created_by_step="upload_source",
        derived_from_step="upload_source",
        input_file_version_ids=[],
    )

    manifest = repo.load_file_manifest(file_ref)
    meta = repo.load_file_version_meta(version_ref)

    assert manifest.current_version_id == version_ref.version_id
    assert meta.size_bytes == 5
    assert meta.content_type == "video/mp4"


def test_repository_creates_run_and_appends_events():
    from api.storage.repository import StorageRepository

    repo = StorageRepository(InMemoryObjectStore())
    run_ref = RunRef(user_id="user_123", run_id="run_001")

    repo.save_run_manifest(
        RunManifest(
            run_id="run_001",
            owner_user_id="user_123",
            workflow_type="edit_pipeline",
            status="created",
            inputs={},
            outputs={},
            steps=[],
            current_step=None,
            last_error=None,
            created_at="2026-04-21T19:00:00Z",
            updated_at="2026-04-21T19:00:00Z",
        )
    )
    repo.append_run_event(
        run_ref=run_ref,
        event_type="step_started",
        timestamp="2026-04-21T19:01:00Z",
        event_id="evt_001",
        payload={"step": "upload_source"},
    )

    events = repo.list_run_events(run_ref)

    assert len(events) == 1
    assert events[0].payload["step"] == "upload_source"
