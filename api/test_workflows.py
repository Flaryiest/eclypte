import base64
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


def test_youtube_download_falls_back_when_requested_format_is_unavailable(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))
    seen_formats = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            seen_formats.append(options.get("format"))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            if self.options.get("format") != "best*[acodec!=none]/best*":
                raise RuntimeError("Requested format is not available")
            media_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "mp4"))
            media_path.write_bytes(b"source-media")
            return {
                "id": "abc123",
                "title": "Fallback Song",
                "requested_downloads": [{"filepath": str(media_path)}],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )
    monkeypatch.setattr(
        workflows.subprocess,
        "run",
        lambda command, **_kwargs: Path(command[-1]).write_bytes(b"wav-bytes"),
    )

    with workflows._temporary_directory("eclypte_youtube_") as td:
        title, wav_path = workflows._download_youtube_wav(
            "https://www.youtube.com/watch?v=abc123",
            Path(td),
        )
        assert title == "Fallback Song"
        assert wav_path.read_bytes() == b"wav-bytes"

    assert "best*[acodec!=none]/best*" in seen_formats


def test_youtube_download_falls_back_to_missing_pot_formats(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))
    seen_options = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            seen_options.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            if self.options.get("extractor_args") != {"youtube": {"formats": ["missing_pot"]}}:
                raise RuntimeError("Requested format is not available")
            if self.options.get("format") != "234/233/140/251/bestaudio/best[acodec!=none]/best*[acodec!=none]":
                raise RuntimeError("Requested format is not available")
            media_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "mp4"))
            media_path.write_bytes(b"source-media")
            return {
                "id": "abc123",
                "title": "Missing Pot Song",
                "requested_downloads": [{"filepath": str(media_path)}],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )
    monkeypatch.setattr(
        workflows.subprocess,
        "run",
        lambda command, **_kwargs: Path(command[-1]).write_bytes(b"wav-bytes"),
    )

    with workflows._temporary_directory("eclypte_youtube_") as td:
        title, wav_path = workflows._download_youtube_wav(
            "https://www.youtube.com/watch?v=abc123",
            Path(td),
        )
        assert title == "Missing Pot Song"
        assert wav_path.read_bytes() == b"wav-bytes"

    assert {"youtube": {"formats": ["missing_pot"]}} in [
        options.get("extractor_args") for options in seen_options
    ]


def test_youtube_download_tries_mweb_missing_pot_fallback(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))
    seen_options = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            seen_options.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            extractor_args = self.options.get("extractor_args")
            if extractor_args != {"youtube": {"player_client": ["mweb"], "formats": ["missing_pot"]}}:
                raise RuntimeError("Requested format is not available")
            media_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "mp4"))
            media_path.write_bytes(b"source-media")
            return {
                "id": "abc123",
                "title": "Mweb Song",
                "requested_downloads": [{"filepath": str(media_path)}],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )
    monkeypatch.setattr(
        workflows.subprocess,
        "run",
        lambda command, **_kwargs: Path(command[-1]).write_bytes(b"wav-bytes"),
    )

    with workflows._temporary_directory("eclypte_youtube_") as td:
        title, wav_path = workflows._download_youtube_wav(
            "https://www.youtube.com/watch?v=abc123",
            Path(td),
        )
        assert title == "Mweb Song"
        assert wav_path.read_bytes() == b"wav-bytes"

    assert {"youtube": {"player_client": ["mweb"], "formats": ["missing_pot"]}} in [
        options.get("extractor_args") for options in seen_options
    ]


def test_youtube_download_format_error_lists_visible_formats(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            if download:
                raise RuntimeError("Requested format is not available")
            return {
                "formats": [
                    {
                        "format_id": "sb0",
                        "ext": "mhtml",
                        "acodec": "none",
                        "vcodec": "images",
                        "protocol": "mhtml",
                    },
                    {
                        "format_id": "234",
                        "ext": "mp4",
                        "acodec": "mp4a.40.2",
                        "vcodec": "none",
                        "protocol": "m3u8_native",
                    },
                ],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    with workflows._temporary_directory("eclypte_youtube_") as td:
        try:
            workflows._download_youtube_wav(
                "https://www.youtube.com/watch?v=abc123",
                Path(td),
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected format failure")

    assert "visible formats" in message
    assert "sb0:mhtml:a=none:v=images:p=mhtml" in message
    assert "234:mp4:a=mp4a.40.2:v=none:p=m3u8_native" in message


def test_youtube_download_format_error_lists_probe_errors(monkeypatch):
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            if download:
                raise RuntimeError("Requested format is not available")
            raise RuntimeError("probe could not extract player response")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    with workflows._temporary_directory("eclypte_youtube_") as td:
        try:
            workflows._download_youtube_wav(
                "https://www.youtube.com/watch?v=abc123",
                Path(td),
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected format failure")

    assert "yt-dlp visible formats: none" in message
    assert "probe errors:" in message
    assert "probe could not extract player response" in message


def test_youtube_download_passes_cookiefile_from_base64_env(monkeypatch):
    cookie_text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
    monkeypatch.setenv(
        "ECLYPTE_YOUTUBE_COOKIES_B64",
        base64.b64encode(cookie_text.encode("utf-8")).decode("ascii"),
    )
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            cookiefile = Path(self.options["cookiefile"])
            assert cookiefile.read_text(encoding="utf-8") == cookie_text
            audio_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "m4a"))
            audio_path.write_bytes(b"source-audio")
            return {
                "id": "abc123",
                "title": "Cookie Song",
                "requested_downloads": [{"filepath": str(audio_path)}],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )
    monkeypatch.setattr(
        workflows.subprocess,
        "run",
        lambda command, **_kwargs: Path(command[-1]).write_bytes(b"wav-bytes"),
    )

    with workflows._temporary_directory("eclypte_youtube_") as td:
        title, _wav_path = workflows._download_youtube_wav(
            "https://www.youtube.com/watch?v=abc123",
            Path(td),
        )

    assert title == "Cookie Song"


def test_youtube_download_auth_error_mentions_cookie_secret(monkeypatch):
    monkeypatch.delenv("ECLYPTE_YOUTUBE_COOKIES_B64", raising=False)
    monkeypatch.delenv("ECLYPTE_YOUTUBE_COOKIES", raising=False)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    with workflows._temporary_directory("eclypte_youtube_") as td:
        try:
            workflows._download_youtube_wav(
                "https://www.youtube.com/watch?v=abc123",
                Path(td),
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected auth failure")

    assert "ECLYPTE_YOUTUBE_COOKIES_B64" in message
    assert "Railway" in message
