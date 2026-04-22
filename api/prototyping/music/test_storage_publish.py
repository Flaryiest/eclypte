from api.storage.refs import FileRef, FileVersionRef, RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


def test_publish_music_artifacts_creates_one_run_and_three_artifacts(tmp_path):
    from api.prototyping.music.storage_publish import publish_music_artifacts

    repo = StorageRepository(InMemoryObjectStore())
    wav_path = tmp_path / "output.wav"
    analysis_path = tmp_path / "output.json"
    lyrics_path = tmp_path / "lyrics.txt"
    wav_path.write_bytes(b"wav-bytes")
    analysis_path.write_text('{"tempo_bpm": 120}', encoding="utf-8")
    lyrics_path.write_text("line one", encoding="utf-8")

    summary = publish_music_artifacts(
        repository=repo,
        user_id="user_123",
        wav_path=wav_path,
        analysis_path=analysis_path,
        lyrics_path=lyrics_path,
    )

    run_manifest = repo.load_run_manifest(
        RunRef(user_id="user_123", run_id=summary.run_id)
    )
    audio_manifest = repo.load_file_manifest(
        FileRef(user_id="user_123", file_id=summary.audio.file_id)
    )
    audio_meta = repo.load_file_version_meta(
        FileVersionRef(
            user_id="user_123",
            file_id=summary.audio.file_id,
            version_id=summary.audio.version_id,
        )
    )
    analysis_meta = repo.load_file_version_meta(
        FileVersionRef(
            user_id="user_123",
            file_id=summary.analysis.file_id,
            version_id=summary.analysis.version_id,
        )
    )
    lyrics_meta = repo.load_file_version_meta(
        FileVersionRef(
            user_id="user_123",
            file_id=summary.lyrics.file_id,
            version_id=summary.lyrics.version_id,
        )
    )

    assert run_manifest.workflow_type == "music_pipeline"
    assert audio_manifest.source_run_id == summary.run_id
    assert audio_meta.content_type == "audio/wav"
    assert analysis_meta.content_type == "application/json"
    assert lyrics_meta.content_type == "text/plain"
    assert lyrics_meta.derived_from.run_id == summary.run_id
