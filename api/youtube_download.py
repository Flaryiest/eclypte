from __future__ import annotations

import base64
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AttemptStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class YoutubeDownloadAttempt:
    provider: str
    status: AttemptStatus
    detail: str


@dataclass(frozen=True)
class YoutubeDownloadResult:
    title: str
    wav_path: Path
    attempts: list[YoutubeDownloadAttempt]


class YoutubeDownloadError(RuntimeError):
    def __init__(self, attempts: list[YoutubeDownloadAttempt]):
        self.attempts = attempts
        super().__init__(_format_attempt_failures(attempts))


def download_youtube_wav(url: str, workdir: Path) -> YoutubeDownloadResult:
    workdir.mkdir(parents=True, exist_ok=True)
    attempts: list[YoutubeDownloadAttempt] = []

    for provider, downloader in _pytubefix_downloaders(url, workdir):
        try:
            title, wav_path = downloader()
            attempts.append(YoutubeDownloadAttempt(provider, "succeeded", "downloaded audio stream"))
            return YoutubeDownloadResult(title=title, wav_path=wav_path, attempts=attempts)
        except Exception as exc:
            attempts.append(YoutubeDownloadAttempt(provider, "failed", _compact_error(exc)))

    try:
        title, wav_path = _download_with_ytdlp(url, workdir)
        attempts.append(YoutubeDownloadAttempt("yt-dlp", "succeeded", "downloaded best audio"))
        return YoutubeDownloadResult(title=title, wav_path=wav_path, attempts=attempts)
    except Exception as exc:
        attempts.append(YoutubeDownloadAttempt("yt-dlp", "failed", _compact_error(exc)))

    raise YoutubeDownloadError(attempts)


def _pytubefix_downloaders(url: str, workdir: Path):
    yield "pytubefix", lambda: _download_with_pytubefix(
        url,
        workdir,
        provider="pytubefix",
    )

    po_token_verifier = _po_token_verifier_from_env()
    if po_token_verifier is not None:
        yield "pytubefix-po-token", lambda: _download_with_pytubefix(
            url,
            workdir,
            provider="pytubefix-po-token",
            client="WEB",
            use_po_token=True,
            po_token_verifier=po_token_verifier,
        )

    yield "pytubefix-web", lambda: _download_with_pytubefix(
        url,
        workdir,
        provider="pytubefix-web",
        client="WEB",
    )


def _download_with_pytubefix(
    url: str,
    workdir: Path,
    *,
    provider: str,
    **youtube_kwargs,
) -> tuple[str, Path]:
    from pytubefix import YouTube

    yt = YouTube(url, **youtube_kwargs)
    stream = yt.streams.get_audio_only()
    if stream is None:
        raise RuntimeError("no audio-only stream was available")
    audio_path = Path(stream.download(str(workdir), f"{provider}.m4a"))
    wav_path = _convert_to_wav(audio_path, workdir / f"{provider}.wav")
    return yt.title or "YouTube song", wav_path


def _download_with_ytdlp(url: str, workdir: Path) -> tuple[str, Path]:
    import yt_dlp

    ydl_opts = {
        "format": "bestaudio/best[acodec!=none]/best",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    cookiefile = _youtube_cookiefile(workdir)
    if cookiefile is not None:
        ydl_opts["cookiefile"] = str(cookiefile)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        audio_path = _yt_dlp_downloaded_path(info, ydl)

    wav_path = _convert_to_wav(
        audio_path,
        workdir / f"{_safe_audio_basename(info.get('id') or 'youtube_audio')}.wav",
    )
    return info.get("title") or "YouTube song", wav_path


def _convert_to_wav(source_path: Path, wav_path: Path) -> Path:
    from imageio_ffmpeg import get_ffmpeg_exe

    try:
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-i", str(source_path), str(wav_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"failed to convert YouTube audio to WAV: {detail}") from exc
    return wav_path


def _yt_dlp_downloaded_path(info: dict, ydl) -> Path:
    for download in info.get("requested_downloads") or []:
        filepath = download.get("filepath")
        if filepath:
            return Path(filepath)
    filepath = info.get("filepath")
    if filepath:
        return Path(filepath)
    return Path(ydl.prepare_filename(info))


def _youtube_cookiefile(workdir: Path) -> Path | None:
    cookie_text = os.environ.get("ECLYPTE_YOUTUBE_COOKIES")
    encoded = os.environ.get("ECLYPTE_YOUTUBE_COOKIES_B64")
    if encoded:
        try:
            cookie_text = base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("ECLYPTE_YOUTUBE_COOKIES_B64 is not valid base64 text") from exc
    if not cookie_text:
        return None
    cookie_path = workdir / "youtube_cookies.txt"
    cookie_path.write_text(cookie_text, encoding="utf-8", newline="\n")
    return cookie_path


def _po_token_verifier_from_env():
    visitor_data = os.environ.get("ECLYPTE_YOUTUBE_VISITOR_DATA")
    po_token = os.environ.get("ECLYPTE_YOUTUBE_PO_TOKEN")
    if not (visitor_data or po_token):
        return None
    if not (visitor_data and po_token):
        return _raise_incomplete_po_token_config
    return lambda: (visitor_data, po_token)


def _raise_incomplete_po_token_config():
    raise RuntimeError(
        "both ECLYPTE_YOUTUBE_VISITOR_DATA and ECLYPTE_YOUTUBE_PO_TOKEN are required "
        "to use pytubefix PO token mode"
    )


def _format_attempt_failures(attempts: list[YoutubeDownloadAttempt]) -> str:
    failures = [
        f"{attempt.provider} failed: {attempt.detail}"
        for attempt in attempts
        if attempt.status == "failed"
    ]
    return "YouTube import failed. " + " | ".join(failures)


def _compact_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()


def _safe_audio_basename(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    return (cleaned or "youtube_song")[:96]
