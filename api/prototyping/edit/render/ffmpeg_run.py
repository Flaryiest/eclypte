"""Executor for the native-ffmpeg renderer.

Runs the argv from `ffmpeg_filtergraph.build_command` as a single ffmpeg process,
streams `-progress` output to a `progress_callback(percent, detail)` (the same
0-100 contract the MoviePy path uses), then extracts a JPEG poster. Skill side
files (`ffmpeg_assets`, e.g. the kinetic-lyrics .ass document) are materialized
into a scratch dir that lives until the process exits.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..skills.base import RenderContext
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


def write_skill_assets(timeline: Timeline, asset_dir: Path, ctx: RenderContext) -> list[Path]:
    """Materialize each overlay skill's ``ffmpeg_assets`` into ``asset_dir``.

    Raises on filename collisions — asset names are namespaced by skill id and
    singleton skills appear once, so a collision is a programming error."""
    from .. import skills  # registry (moviepy-free metadata)
    from ..skills.base import ResolvedOverlay

    written: list[Path] = []
    seen: set[str] = set()
    for ov in timeline.overlays:
        resolved = ResolvedOverlay(
            skill_id=ov.skill_id,
            timeline_start_sec=ov.timeline_start_sec,
            timeline_end_sec=ov.timeline_end_sec,
            params=ov.params,
        )
        for filename, content in skills.get(ov.skill_id).ffmpeg_assets(resolved, ctx).items():
            if filename in seen:
                raise ValueError(f"skill asset filenames collide: {filename!r}")
            seen.add(filename)
            target = asset_dir / filename
            target.write_text(content, encoding="utf-8")
            written.append(target)
    return written


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
    fonts_dir: str | None = None,
    shot_stats=None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_fps = fps or timeline.output.fps
    total_frames = max(1, round(out_fps * timeline.output.duration_sec))

    # The scratch dir must outlive the subprocess: the ass filter opens its
    # file when the filtergraph initializes.
    with tempfile.TemporaryDirectory(prefix="eclypte-skill-assets-") as asset_dir:
        if timeline.overlays:
            w, h = size or (timeline.output.width, timeline.output.height)
            ctx = RenderContext(
                output_size=(w, h), fps=out_fps, font_path=font_path or "",
                asset_dir=asset_dir, fonts_dir=fonts_dir or "",
                shot_stats=tuple(shot_stats) if shot_stats else None,
            )
            write_skill_assets(timeline, Path(asset_dir), ctx)

        cmd = build_command(
            timeline, source=str(source), audio=str(audio), out_path=str(out_path),
            preset=preset, threads=threads, size=size, fps=fps, font_path=font_path,
            asset_dir=asset_dir, fonts_dir=fonts_dir or "", shot_stats=shot_stats,
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
