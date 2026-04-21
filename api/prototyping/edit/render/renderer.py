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
from pathlib import Path

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips

from ..synthesis.timeline_schema import OutputSpec, Shot, Timeline
from ..synthesis.validators import validate_timeline
from .effects import apply_effects
from .transitions import apply_transition

CODEC_VIDEO = "libx264"
CODEC_AUDIO = "aac"
DEFAULT_ENCODE_PRESET = "medium"


def render_timeline(
    timeline_path: Path | str,
    out_path: Path | str,
    *,
    preview: bool = False,
    encode_preset: str = DEFAULT_ENCODE_PRESET,
    threads: int | None = None,
) -> Path:
    timeline_path = Path(timeline_path)
    out_path = Path(out_path)

    timeline = _load_timeline(timeline_path)
    validate_timeline(timeline)

    target_size, target_fps = _resolve_output(timeline.output, preview=preview)

    source = VideoFileClip(timeline.source.video)
    audio = AudioFileClip(timeline.audio.path)

    try:
        shot_clips = _build_shot_clips(source, timeline.shots, target_size, timeline.output.crop)
        concat = concatenate_videoclips(shot_clips, method="compose")

        audio_slice = audio.subclipped(
            timeline.audio.start_sec,
            timeline.audio.start_sec + timeline.output.duration_sec,
        )
        final = concat.with_audio(audio_slice).with_duration(timeline.output.duration_sec)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(
            str(out_path),
            fps=target_fps,
            codec=CODEC_VIDEO,
            audio_codec=CODEC_AUDIO,
            preset=encode_preset,
            threads=threads,
            ffmpeg_params=["-movflags", "+faststart"],
        )
    finally:
        source.close()
        audio.close()

    return out_path


def _load_timeline(path: Path) -> Timeline:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Timeline.model_validate(data)


def _resolve_output(spec: OutputSpec, *, preview: bool) -> tuple[tuple[int, int], int]:
    if preview:
        scale = 720 / max(spec.height, 1)
        return (int(spec.width * scale), 720), min(spec.fps, 24)
    return (spec.width, spec.height), spec.fps


def _build_shot_clips(source: VideoFileClip, shots: list[Shot], size: tuple[int, int], crop_mode: str):
    clips = []
    prev = None
    for shot in shots:
        sub = source.subclipped(shot.source.start_sec, shot.source.end_sec)
        sub = sub.without_audio()
        if shot.speed != 1.0:
            sub = sub.with_speed_scaled(factor=shot.speed)
        sub = sub.with_duration(shot.duration_sec)
        sub = _fit(sub, size, crop_mode)
        sub = apply_effects(sub, shot)
        sub = apply_transition(prev, sub, shot)
        clips.append(sub)
        prev = sub
    return clips


def _fit(clip, size: tuple[int, int], crop_mode: str):
    target_w, target_h = size
    w, h = clip.size
    if (w, h) == (target_w, target_h):
        return clip

    if crop_mode == "center":
        scale = max(target_w / w, target_h / h)
        scaled = clip.resized(scale)
        sw, sh = scaled.size
        x = (sw - target_w) // 2
        y = (sh - target_h) // 2
        return scaled.cropped(x1=x, y1=y, x2=x + target_w, y2=y + target_h)

    scale = min(target_w / w, target_h / h)
    scaled = clip.resized(scale)
    bg = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).with_duration(clip.duration)
    return CompositeVideoClip([bg, scaled.with_position("center")], size=(target_w, target_h))
