import sys
from pathlib import Path
from types import SimpleNamespace

from api.youtube_download import YoutubeDownloadAttempt, YoutubeDownloadResult
from api.storage.refs import RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore
from api.workflows import DefaultWorkflowRunner


def _create_youtube_import_run(repo: StorageRepository):
    return repo.create_run(
        user_id="user_123",
        workflow_type="youtube_song_import",
        inputs={"youtube_url": "https://www.youtube.com/watch?v=abc123"},
        steps=["download_youtube_audio", "publish_audio", "analyze_music", "publish_analysis"],
    )


def test_youtube_song_import_publishes_audio_and_analysis(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = _create_youtube_import_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    def fake_download(url, workdir):
        assert url == "https://www.youtube.com/watch?v=abc123"
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return YoutubeDownloadResult(
            title="Imported Song",
            wav_path=wav_path,
            attempts=[YoutubeDownloadAttempt("pytubefix", "succeeded", "downloaded audio stream")],
        )

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            assert audio_bytes == b"wav-bytes"
            assert filename == "Imported Song.wav"
            return {"source": {"title": "Imported Song"}}

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setitem(
        sys.modules,
        "modal",
        SimpleNamespace(
            Function=SimpleNamespace(from_name=lambda *_args: FakeAnalyze),
        ),
    )

    runner.run_youtube_song_import(
        user_id="user_123",
        run_id=run.run_id,
        url="https://www.youtube.com/watch?v=abc123",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["audio_file_id"] == f"file_audio_{run.run_id}"
    assert completed.outputs["music_analysis_file_id"] == f"file_music_analysis_{run.run_id}"


def test_youtube_song_import_records_download_attempt_events(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = _create_youtube_import_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    def fake_download(_url, workdir):
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return YoutubeDownloadResult(
            title="Imported Song",
            wav_path=wav_path,
            attempts=[
                YoutubeDownloadAttempt("pytubefix", "failed", "bot gate"),
                YoutubeDownloadAttempt("yt-dlp", "succeeded", "downloaded best audio"),
            ],
        )

    class FakeAnalyze:
        @staticmethod
        def remote(_audio_bytes, _filename):
            return {"source": {"title": "Imported Song"}}

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setitem(
        sys.modules,
        "modal",
        SimpleNamespace(
            Function=SimpleNamespace(from_name=lambda *_args: FakeAnalyze),
        ),
    )

    runner.run_youtube_song_import(
        user_id="user_123",
        run_id=run.run_id,
        url="https://www.youtube.com/watch?v=abc123",
    )

    events = repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
    attempts = [event for event in events if event.event_type == "youtube_download_attempt"]

    assert [attempt.payload["provider"] for attempt in attempts] == ["pytubefix", "yt-dlp"]
    assert [attempt.payload["status"] for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0].payload["detail"] == "bot gate"
