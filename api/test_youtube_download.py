import base64
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.youtube_download import YoutubeDownloadError, download_youtube_wav


def _workdir(name):
    path = Path.cwd() / "youtube-worker-tmp" / f"{name}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return path


def _install_ffmpeg(monkeypatch, module):
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: "fake-ffmpeg"),
    )

    def fake_run(command, check, capture_output, text):
        assert command[:3] == ["fake-ffmpeg", "-y", "-i"]
        assert check is True
        assert capture_output is True
        assert text is True
        Path(command[-1]).write_bytes(b"wav-bytes")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)


def test_download_youtube_wav_uses_pytubefix_audio_stream_first(monkeypatch):
    import api.youtube_download as youtube_download

    class FakeStream:
        def download(self, output_path, filename):
            path = Path(output_path) / filename
            path.write_bytes(b"source-audio")
            return str(path)

    class FakeYouTube:
        def __init__(self, url):
            assert url == "https://www.youtube.com/watch?v=abc123"
            self.title = "Prototype Song"
            self.streams = SimpleNamespace(get_audio_only=lambda: FakeStream())

    monkeypatch.setitem(sys.modules, "pytubefix", SimpleNamespace(YouTube=FakeYouTube))
    _install_ffmpeg(monkeypatch, youtube_download)

    result = download_youtube_wav("https://www.youtube.com/watch?v=abc123", _workdir("pytubefix"))

    assert result.title == "Prototype Song"
    assert result.wav_path.read_bytes() == b"wav-bytes"
    assert [(attempt.provider, attempt.status) for attempt in result.attempts] == [
        ("pytubefix", "succeeded")
    ]


def test_download_youtube_wav_falls_back_to_ytdlp_after_pytubefix_failure(monkeypatch):
    import api.youtube_download as youtube_download

    class FakeYouTube:
        def __init__(self, _url):
            raise RuntimeError("pytubefix bot gate")

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
            audio_path = Path(self.options["outtmpl"].replace("%(id)s", "abc123").replace("%(ext)s", "m4a"))
            audio_path.write_bytes(b"source-audio")
            return {
                "id": "abc123",
                "title": "Yt-dlp Song",
                "requested_downloads": [{"filepath": str(audio_path)}],
            }

    monkeypatch.setitem(sys.modules, "pytubefix", SimpleNamespace(YouTube=FakeYouTube))
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    _install_ffmpeg(monkeypatch, youtube_download)

    result = download_youtube_wav("https://www.youtube.com/watch?v=abc123", _workdir("fallback"))

    assert result.title == "Yt-dlp Song"
    assert result.wav_path.read_bytes() == b"wav-bytes"
    assert [(attempt.provider, attempt.status) for attempt in result.attempts] == [
        ("pytubefix", "failed"),
        ("yt-dlp", "succeeded"),
    ]


def test_download_youtube_wav_passes_cookiefile_to_ytdlp(monkeypatch):
    import api.youtube_download as youtube_download

    cookie_text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
    monkeypatch.setenv(
        "ECLYPTE_YOUTUBE_COOKIES_B64",
        base64.b64encode(cookie_text.encode("utf-8")).decode("ascii"),
    )

    class FakeYouTube:
        def __init__(self, _url):
            raise RuntimeError("pytubefix bot gate")

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

    monkeypatch.setitem(sys.modules, "pytubefix", SimpleNamespace(YouTube=FakeYouTube))
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    _install_ffmpeg(monkeypatch, youtube_download)

    result = download_youtube_wav("https://www.youtube.com/watch?v=abc123", _workdir("cookie"))

    assert result.title == "Cookie Song"


def test_download_youtube_wav_reports_all_provider_failures(monkeypatch):
    class FakeYouTube:
        def __init__(self, _url):
            raise RuntimeError("pytubefix bot gate")

    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setitem(sys.modules, "pytubefix", SimpleNamespace(YouTube=FakeYouTube))
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    with pytest.raises(YoutubeDownloadError) as exc_info:
        download_youtube_wav("https://www.youtube.com/watch?v=abc123", _workdir("failure"))

    message = str(exc_info.value)
    assert "pytubefix failed: pytubefix bot gate" in message
    assert "yt-dlp failed: Sign in to confirm you're not a bot" in message
    assert [(attempt.provider, attempt.status) for attempt in exc_info.value.attempts] == [
        ("pytubefix", "failed"),
        ("yt-dlp", "failed"),
    ]
