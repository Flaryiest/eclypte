from api.storage.refs import FileRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


def test_stage_version_to_tempdir_writes_blob_to_disk(tmp_path):
    from api.storage.staging import stage_version_to_tempdir

    repo = StorageRepository(InMemoryObjectStore())
    file_ref = FileRef(user_id="user_123", file_id="file_001")
    repo.create_file_manifest(
        file_ref=file_ref,
        kind="song_audio",
        display_name="song.wav",
    )
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=b"abc123",
        content_type="audio/wav",
        original_filename="song.wav",
        created_by_step="upload_song",
        derived_from_step="upload_song",
        input_file_version_ids=[],
    )

    staged_path = stage_version_to_tempdir(
        repository=repo,
        version_ref=version_ref,
        temp_dir=tmp_path,
        filename="song.wav",
    )

    assert staged_path.read_bytes() == b"abc123"
