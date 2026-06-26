"""
moviepy-based renderer.

Consumes a validated Timeline and writes an MP4. Phase 1 supports:
  - hard cuts only (no crossfades/whips/flashes)
  - letterbox or center-crop to the output size
  - audio attached once at composite level with audio.start_sec offset
  - per-shot effects are no-ops (see effects.py)

moviepy v2 API conventions used: `subclipped`, `with_duration`, `with_start`,
`resized`, `with_audio`, `without_audio`.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips

from .. import skills
from ..skills.base import RenderContext, ResolvedOverlay
from ..synthesis.timeline_schema import OutputSpec, Shot, Timeline
from ..synthesis.validators import validate_timeline
from .effects import apply_effects
from .ffmpeg_filtergraph import can_render_with_ffmpeg
from .ffmpeg_run import render_with_ffmpeg
from .geometry import cover_crop_offsets, cover_resize_size
from .transitions import apply_transition

CODEC_VIDEO = "libx264"
CODEC_AUDIO = "aac"
DEFAULT_ENCODE_PRESET = "medium"

# Font lookup for text overlays. The Modal render image bundles a font at
# /fonts/overlay.otf; ECLYPTE_OVERLAY_FONT overrides; the rest are local
# fallbacks so the guarded renderer test runs without the bundled font.
_FONT_CANDIDATES = [
    os.environ.get("ECLYPTE_OVERLAY_FONT"),
    "/fonts/overlay.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def _resolve_font_path() -> str:
    for candidate in _FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "no overlay font available; set ECLYPTE_OVERLAY_FONT or bundle /fonts/overlay.otf"
    )


def _apply_overlays(base, timeline: Timeline, target_size: tuple[int, int]):
    """Composite the timeline's overlay skills on top of the concatenated video."""
    if not timeline.overlays:
        return base
    ctx = RenderContext(
        output_size=target_size,
        fps=timeline.output.fps,
        font_path=_resolve_font_path(),
    )
    layers = []
    for ov in timeline.overlays:
        resolved = ResolvedOverlay(
            skill_id=ov.skill_id,
            timeline_start_sec=ov.timeline_start_sec,
            timeline_end_sec=ov.timeline_end_sec,
            params=ov.params,
        )
        layers.extend(skills.get(ov.skill_id).build_layers(resolved, ctx))
    if not layers:
        return base
    return CompositeVideoClip([base, *layers], size=target_size)


def _log_timing(step: str, started_at: float) -> None:
    elapsed = time.perf_counter() - started_at
    print(f"[renderer] {step}: {elapsed:.2f}s")


def render_timeline(
    timeline_path: Path | str,
    out_path: Path | str,
    *,
    preview: bool = False,
    encode_preset: str = DEFAULT_ENCODE_PRESET,
    threads: int | None = None,
    progress_callback=None,
    poster_path: Path | str | None = None,
) -> Path:
    total_started = time.perf_counter()
    timeline_path = Path(timeline_path)
    out_path = Path(out_path)

    timeline = _load_timeline(timeline_path)
    validate_timeline(timeline)

    target_size, target_fps = _resolve_output(timeline.output, preview=preview)

    # Fast path: a single native ffmpeg filtergraph (no per-frame Python pump).
    # Covers the common montage (cuts/crossfade, no overlays/effects); anything
    # else falls through to the MoviePy renderer below.
    if can_render_with_ffmpeg(timeline):
        render_with_ffmpeg(
            timeline,
            source=timeline.source.video,
            audio=timeline.audio.path,
            out_path=out_path,
            preset=encode_preset,
            threads=threads,
            size=target_size,
            fps=target_fps,
            progress_callback=progress_callback,
            poster_path=poster_path,
        )
        _log_timing("total render_timeline (ffmpeg)", total_started)
        return out_path

    source = None
    audio = None
    concat = None
    final = None
    shot_clips = []

    open_started = time.perf_counter()
    source = VideoFileClip(timeline.source.video)
    audio = AudioFileClip(timeline.audio.path)
    _log_timing("open media", open_started)
    _report(progress_callback, 10, "Opened media")

    try:
        build_started = time.perf_counter()
        shot_clips = _build_shot_clips(
            source,
            timeline.shots,
            target_size,
            timeline.output.crop,
            timeline.output.crop_focus_x,
        )
        _log_timing("build shot clips", build_started)
        _report(progress_callback, 30, "Built shot clips")

        concat_started = time.perf_counter()
        concat = concatenate_videoclips(shot_clips, method="compose")
        composited = _apply_overlays(concat, timeline, target_size)
        audio_slice = audio.subclipped(
            timeline.audio.start_sec,
            timeline.audio.start_sec + timeline.output.duration_sec,
        )
        final = composited.with_audio(audio_slice).with_duration(timeline.output.duration_sec)
        _log_timing("concat/compose", concat_started)
        _report(progress_callback, 45, "Composed timeline")

        if poster_path is not None:
            poster_path = Path(poster_path)
            poster_path.parent.mkdir(parents=True, exist_ok=True)
            poster_t = max(0.0, min(1.0, float(timeline.output.duration_sec) / 2.0))
            try:
                _save_poster_jpeg(final, poster_t, poster_path)
            except Exception as exc:  # poster is best-effort; never fail the render for it
                print(f"[renderer] poster generation skipped: {exc}")
            _report(progress_callback, 50, "Saved poster frame")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_started = time.perf_counter()
        _report(progress_callback, 55, "Encoding MP4")
        final.write_videofile(
            str(out_path),
            fps=target_fps,
            codec=CODEC_VIDEO,
            audio_codec=CODEC_AUDIO,
            audio_bitrate="192k",
            preset=encode_preset,
            threads=threads,
            # High-quality source so Instagram/YouTube re-encodes degrade less:
            # CRF 18 (visually lossless-ish), animation tune for flat shading,
            # yuv420p for universal playback, faststart for instant web playback.
            ffmpeg_params=[
                "-movflags", "+faststart",
                "-crf", "18",
                "-tune", "animation",
                "-pix_fmt", "yuv420p",
            ],
            logger=_make_encode_logger(progress_callback),
        )
        _log_timing("write_videofile", write_started)
        _report(progress_callback, 100, "Encoded MP4")
    finally:
        if final is not None:
            final.close()
        elif concat is not None:
            concat.close()
        for clip in shot_clips:
            clip.close()
        if source is not None:
            source.close()
        if audio is not None:
            audio.close()

    _log_timing("total render_timeline", total_started)
    return out_path


def _report(progress_callback, percent, detail):
    if progress_callback is not None:
        progress_callback(percent, detail)


def _save_poster_jpeg(clip, t, poster_path):
    """Save a single RGB JPEG frame. Composited clips (e.g. letterbox) expose an
    RGBA frame that JPEG can't encode, so we drop any alpha channel first."""
    import numpy as np
    from PIL import Image

    frame = np.asarray(clip.get_frame(t))
    if frame.ndim == 3 and frame.shape[2] == 4:
        frame = frame[:, :, :3]
    Image.fromarray(frame.astype("uint8")).convert("RGB").save(
        str(poster_path), format="JPEG", quality=85
    )


def _make_encode_logger(progress_callback):
    """Bridge MoviePy's proglog progress into `progress_callback`.

    `write_videofile` reports frame-writing progress through proglog's
    ``"frame_index"`` bar. We map that bar's index/total onto the 55->99 band so
    the encode — the longest step — animates instead of freezing at 55%. Falls
    back to MoviePy's default ``"bar"`` logger when no callback is wired or
    proglog is unavailable.
    """
    if progress_callback is None:
        return "bar"
    try:
        from proglog import ProgressBarLogger
    except Exception:  # pragma: no cover - proglog ships with moviepy
        return "bar"

    class _EncodeLogger(ProgressBarLogger):
        def bars_callback(self, bar, attr, value, old_value=None):
            if bar != "frame_index" or attr != "index":
                return
            total = self.bars.get(bar, {}).get("total")
            if not total:
                return
            frac = max(0.0, min(1.0, float(value) / float(total)))
            mapped = 55 + int(frac * 44)
            _report(progress_callback, mapped, f"Encoding MP4 ({int(frac * 100)}%)")

    return _EncodeLogger()


def _load_timeline(path: Path) -> Timeline:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Timeline.model_validate(data)


def _resolve_output(spec: OutputSpec, *, preview: bool) -> tuple[tuple[int, int], int]:
    if preview:
        scale = 720 / max(spec.height, 1)
        return (int(spec.width * scale), 720), min(spec.fps, 24)
    return (spec.width, spec.height), spec.fps


def _build_shot_clips(
    source: VideoFileClip,
    shots: list[Shot],
    size: tuple[int, int],
    crop_mode: str,
    crop_focus_x: float,
):
    clips = []
    prev = None
    for shot in shots:
        sub = source.subclipped(shot.source.start_sec, shot.source.end_sec)
        sub = sub.without_audio()
        if shot.speed != 1.0:
            sub = sub.with_speed_scaled(factor=shot.speed)
        sub = sub.with_duration(shot.duration_sec)
        sub = _fit(sub, size, crop_mode, crop_focus_x)
        sub = apply_effects(sub, shot)
        sub = apply_transition(prev, sub, shot)
        if tuple(sub.size) != tuple(size):
            raise ValueError(
                f"shot[{shot.index}] rendered size {tuple(sub.size)} does not match "
                f"target size {tuple(size)}"
            )
        clips.append(sub)
        prev = sub
    return clips


def _fit(clip, size: tuple[int, int], crop_mode: str, crop_focus_x: float = 0.5):
    target_w, target_h = size
    w, h = clip.size
    if (w, h) == (target_w, target_h):
        return clip

    if crop_mode in {"center", "fill"}:
        scaled_size = cover_resize_size((w, h), (target_w, target_h))
        scaled = clip.resized(new_size=scaled_size)
        x, y = cover_crop_offsets(
            (w, h),
            (target_w, target_h),
            focus_x=crop_focus_x,
            scaled_size=scaled_size,
        )
        return scaled.cropped(x1=x, y1=y, x2=x + target_w, y2=y + target_h)

    scale = min(target_w / w, target_h / h)
    scaled = clip.resized(scale)
    bg = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).with_duration(clip.duration)
    return CompositeVideoClip([bg, scaled.with_position("center")], size=(target_w, target_h))
