"""
Download a viral AMV from Instagram Reels as (wav, mp4) for Phase-2 ingestion.

Separate from `music/ytdownload.py` because that one is audio-only and
doesn't track metadata we need here (yt_video_id, duration, author).
Files land in a caller-owned tempdir; the caller is expected to delete
the tempdir after running the two analyses. We keep only the derived
JSON, not the media — source is re-downloadable from the URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydub import AudioSegment
import yt_dlp


class ReferenceDownloadError(RuntimeError):
    """Raised when a reference AMV can't be downloaded."""


@dataclass
class ReferenceMedia:
    audio_wav_path: Path
    video_mp4_path: Path
    yt_video_id: str
    title: str
    duration_sec: float
    author: str
    publish_date: Optional[str]


def download_reference(url: str, workdir: Path) -> ReferenceMedia:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': str(workdir / '%(id)s.%(ext)s'),
        'quiet': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            video_id = info.get('id', 'unknown_id')
            title = info.get('title', '')
            duration = float(info.get('duration') or 0.0)
            author = info.get('uploader') or info.get('creator') or ""
            
            upload_date_raw = info.get('upload_date')
            publish = None
            if upload_date_raw and len(upload_date_raw) == 8:
                publish = f"{upload_date_raw[:4]}-{upload_date_raw[4:6]}-{upload_date_raw[6:]}T00:00:00"

            if 'requested_downloads' in info and info['requested_downloads']:
                media_path = Path(info['requested_downloads'][0]['filepath'])
            else:
                ext = info.get('ext', 'mp4')
                media_path = workdir / f"{video_id}.{ext}"

            wav_path = workdir / f"{video_id}.wav"
            AudioSegment.from_file(str(media_path)).export(str(wav_path), format="wav")

    except Exception as exc:
        raise ReferenceDownloadError(f"failed to download {url}: {exc}") from exc

    return ReferenceMedia(
        audio_wav_path=Path(wav_path),
        video_mp4_path=Path(media_path),
        yt_video_id=video_id,
        title=title,
        duration_sec=duration,
        author=author,
        publish_date=publish,
    )
