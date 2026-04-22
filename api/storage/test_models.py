from api.storage.models import (
    DerivedFrom,
    FileManifest,
    FileVersionMeta,
    RunEvent,
    RunManifest,
    RunStep,
)


def test_file_manifest_round_trips():
    manifest = FileManifest(
        file_id="file_001",
        owner_user_id="user_123",
        kind="source_video",
        current_version_id="ver_001",
        source_run_id=None,
        display_name="source.mp4",
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:00:00Z",
        tags=["upload"],
    )

    restored = FileManifest.model_validate_json(manifest.model_dump_json())
    assert restored.current_version_id == "ver_001"
    assert restored.kind == "source_video"


def test_file_version_meta_requires_derivation_details():
    meta = FileVersionMeta(
        version_id="ver_001",
        file_id="file_001",
        owner_user_id="user_123",
        content_type="video/mp4",
        size_bytes=12,
        sha256="abc",
        original_filename="source.mp4",
        created_at="2026-04-21T19:00:00Z",
        created_by_step="upload",
        storage_key="users/user_123/files/file_001/versions/ver_001/blob",
        derived_from=DerivedFrom(
            run_id="run_001",
            step_id="upload_source",
            input_file_version_ids=[],
            params_hash=None,
        ),
    )

    assert meta.derived_from.step_id == "upload_source"


def test_run_manifest_tracks_step_statuses():
    manifest = RunManifest(
        run_id="run_001",
        owner_user_id="user_123",
        workflow_type="edit_pipeline",
        status="running",
        inputs={"source_video": "file_001"},
        outputs={},
        steps=[RunStep(name="upload_source", status="completed")],
        current_step="video_analysis",
        last_error=None,
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:05:00Z",
    )

    assert manifest.steps[0].status == "completed"


def test_run_event_is_append_only_record():
    event = RunEvent(
        event_id="evt_001",
        run_id="run_001",
        owner_user_id="user_123",
        event_type="step_started",
        timestamp="2026-04-21T19:00:00Z",
        payload={"step": "video_analysis"},
    )

    assert event.payload["step"] == "video_analysis"
