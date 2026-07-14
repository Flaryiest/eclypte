from __future__ import annotations

import subprocess
from pathlib import Path


def convert_audio_to_wav(source_path: Path, wav_path: Path) -> Path:
    """Transcode any ffmpeg-supported audio file (mp3/m4a/flac/...) to WAV."""
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
        raise RuntimeError(f"failed to convert audio to WAV: {detail}") from exc
    return wav_path
