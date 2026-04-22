from api.storage.refs import FileRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


def test_storage_smoke_flow_can_publish_stage_and_derive_json(tmp_path):
    from api.storage.staging import stage_version_to_tempdir

    repo = StorageRepository(InMemoryObjectStore())
    source_ref = FileRef(user_id="user_123", file_id="file_source")
    derived_ref = FileRef(user_id="user_123", file_id="file_analysis")

    repo.create_file_manifest(
        file_ref=source_ref,
        kind="source_video",
        display_name="source.mp4",
    )
    repo.create_file_manifest(
        file_ref=derived_ref,
        kind="video_analysis",
        display_name="source.json",
    )
    source_version = repo.publish_bytes(
        file_ref=source_ref,
        body=b"frame-bytes",
        content_type="video/mp4",
        original_filename="source.mp4",
        created_by_step="upload_source",
        derived_from_step="upload_source",
        input_file_version_ids=[],
    )

    staged_path = stage_version_to_tempdir(
        repository=repo,
        version_ref=source_version,
        temp_dir=tmp_path,
        filename="source.mp4",
    )
    repo.publish_json(
        file_ref=derived_ref,
        data={"source_path": str(staged_path), "ok": True},
        original_filename="source.json",
        created_by_step="video_analysis",
        derived_from_step="video_analysis",
        input_file_version_ids=[source_version.version_id],
    )

    manifest = repo.load_file_manifest(derived_ref)

    assert manifest.current_version_id is not None
