import sys
from pathlib import Path
import subprocess
from types import SimpleNamespace

from api.storage.refs import RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore
import api.workflows as workflows
from api.workflows import DefaultWorkflowRunner


def test_youtube_song_import_publishes_audio_and_analysis(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = repo.create_run(
        user_id="user_123",
        workflow_type="youtube_song_import",
        inputs={"youtube_url": "https://www.youtube.com/watch?v=abc123"},
        steps=["download_youtube_audio", "publish_audio", "analyze_music", "publish_analysis"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    def fake_download(url, workdir):
        assert url == "https://www.youtube.com/watch?v=abc123"
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return "Imported Song", wav_path

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


def test_youtube_download_uses_yt_dlp_and_converts_to_wav(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download):
            assert url == "https://www.youtube.com/watch?v=abc123"
            assert download is True
            audio_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "webm"))
            audio_path.write_bytes(b"source-audio")
            return {
                "id": "abc123",
                "title": "Imported Song",
                "requested_downloads": [{"filepath": str(audio_path)}],
            }

    def fake_run(command, check, capture_output, text, **_kwargs):
        assert command[:4] == ["fake-ffmpeg", "-y", "-i", str(Path(command[3]))]
        assert check is True
        assert capture_output is True
        assert text is True
        Path(command[-1]).write_bytes(b"wav-bytes")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setitem(
        sys.modules,
        "yt_dlp",
        SimpleNamespace(YoutubeDL=FakeYoutubeDL),
    )
    monkeypatch.setitem(
        sys.modules,
        "pytubefix",
        SimpleNamespace(
            YouTube=lambda _url: (_ for _ in ()).throw(
                AssertionError("pytubefix should not be used for API YouTube imports")
            ),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )
    monkeypatch.setattr(workflows.subprocess, "run", fake_run)

    with workflows._temporary_directory("eclypte_youtube_") as td:
        title, wav_path = workflows._download_youtube_wav(
            "https://www.youtube.com/watch?v=abc123",
            Path(td),
        )
        assert title == "Imported Song"
        assert wav_path.name == "abc123.wav"
        assert wav_path.read_bytes() == b"wav-bytes"
