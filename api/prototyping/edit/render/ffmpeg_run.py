"""Executor for the native-ffmpeg renderer.

Runs the argv from `ffmpeg_filtergraph.build_command` as a single ffmpeg process,
streams `-progress` output to a `progress_callback(percent, detail)` (the same
0-100 contract the MoviePy path uses), then extracts a JPEG poster.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..synthesis.timeline_schema import Timeline
from .ffmpeg_filtergraph import build_command


def _ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg  # bundled with moviepy; always present in the render image

    return imageio_ffmpeg.get_ffmpeg_exe()


def progress_percent(line: str, total_frames: int) -> int | None:
    """Parse one ffmpeg `-progress` line into a 0-100 percent, or None.

    ffmpeg emits `key=value` lines; only `frame=N` advances our bar."""
    line = line.strip()
    if total_frames <= 0 or not line.startswith("frame="):
        return None
    try:
        frame = int(line.split("=", 1)[1])
    except ValueError:
        return None
    return max(0, min(100, round(frame / total_frames * 100)))


def render_with_ffmpeg(
    timeline: Timeline,
    *,
    source: str | Path,
    audio: str | Path,
    out_path: str | Path,
    preset: str = "medium",
    threads: int | None = None,
    size: tuple[int, int] | None = None,
    fps: int | None = None,
    progress_callback=None,
    poster_path: str | Path | None = None,
    font_path: str | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_fps = fps or timeline.output.fps
    total_frames = max(1, round(out_fps * timeline.output.duration_sec))

    cmd = build_command(
        timeline, source=str(source), audio=str(audio), out_path=str(out_path),
        preset=preset, threads=threads, size=size, fps=fps, font_path=font_path,
    )
    cmd[0] = _ffmpeg_exe()
    # Insert progress/quiet flags before the trailing output path.
    out_token = cmd.pop()
    cmd += ["-progress", "pipe:1", "-nostats", "-loglevel", "error", out_token]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last = -1
    assert proc.stdout is not None
    for line in proc.stdout:
        pct = progress_percent(line, total_frames)
        if pct is not None and pct != last:
            last = pct
            if progress_callback is not None:
                progress_callback(pct, f"Encoding MP4 ({pct}%)")
    proc.wait()
    if proc.returncode != 0:
        err = (proc.stderr.read() if proc.stderr else "")[-2000:]
        raise RuntimeError(f"ffmpeg render failed (rc={proc.returncode}): {err}")
    if progress_callback is not None:
        progress_callback(100, "Encoded MP4")

    if poster_path is not None:
        _extract_poster(out_path, max(0.0, timeline.output.duration_sec / 2.0), Path(poster_path))
    return out_path


def _extract_poster(video: Path, t: float, poster: Path) -> None:
    poster.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg_exe(), "-y", "-ss", f"{t:.3f}", "-i", str(video),
           "-frames:v", "1", "-q:v", "3", "-loglevel", "error", str(poster)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
