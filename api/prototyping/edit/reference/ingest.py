"""
Ingest one viral AMV: download → Modal music + video analysis → metrics
→ `store/<ref_id>.json`.

Reuses the two existing Modal apps (`eclypte-analysis`, `eclypte-video`)
via the bytes-path entrypoints — no new image, no volume upload. AMVs are
short enough that round-tripping the mp4 as bytes is cheaper than the
volume put/get dance.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .download import download_reference
from .metrics import compute_metrics

SCHEMA_VERSION = 1

log = logging.getLogger(__name__)


class AlreadyIngestedError(RuntimeError):
    pass


def ingest(
    url: str,
    *,
    likes: int,
    views: int,
    store_dir: Path,
    force: bool = False,
) -> Path:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    pre_ref_id = _probe_ref_id(url)
    if pre_ref_id:
        pre_path = store_dir / f"{pre_ref_id}.json"
        if pre_path.exists() and not force:
            raise AlreadyIngestedError(
                f"already ingested: {pre_path} (use --force to overwrite)"
            )

    with tempfile.TemporaryDirectory(prefix="eclypte_ref_") as td:
        workdir = Path(td)
        log.info("downloading %s", url)
        media = download_reference(url, workdir)

        ref_id = media.yt_video_id or hashlib.sha256(url.encode()).hexdigest()[:11]
        out_path = store_dir / f"{ref_id}.json"
        if out_path.exists() and not force:
            raise AlreadyIngestedError(
                f"already ingested: {out_path} (use --force to overwrite)"
            )

        log.info("running music analysis (Modal) on %s", media.audio_wav_path.name)
        music = _run_music_analysis(media.audio_wav_path)

        log.info("running video analysis (Modal) on %s", media.video_mp4_path.name)
        video = _run_video_analysis(media.video_mp4_path)

        metrics = compute_metrics(music, video)

        record = {
            "schema_version": SCHEMA_VERSION,
            "ref_id": ref_id,
            "meta": {
                "url": url,
                "yt_video_id": media.yt_video_id,
                "title": media.title,
                "author": media.author,
                "publish_date": media.publish_date,
                "duration_sec": media.duration_sec,
                "likes": int(likes),
                "views": int(views),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            },
            "music": music,
            "video": video,
            "metrics": metrics,
        }

        _atomic_write_json(out_path, record)
        log.info("wrote %s  (%d cuts, %d scenes)", out_path,
                 metrics.get("n_cuts", 0), metrics.get("n_scenes", 0))
        return out_path


def _run_music_analysis(audio_path: Path) -> dict:
    import modal
    fn = modal.Function.from_name("eclypte-analysis", "analyze_remote")
    audio_bytes = audio_path.read_bytes()
    return fn.remote(audio_bytes, audio_path.name)


def _run_video_analysis(video_path: Path) -> dict:
    import modal
    fn = modal.Function.from_name("eclypte-video", "analyze_remote_bytes")
    video_bytes = video_path.read_bytes()
    return fn.remote(video_bytes, video_path.name)


def _probe_ref_id(url: str) -> str | None:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": False}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("id") if info else None
    except Exception:
        return None


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
