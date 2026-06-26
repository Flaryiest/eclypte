"""Pure builder: a validated Timeline -> an ffmpeg argv list.

Keeps every pixel inside one ffmpeg process (decode -> scale/crop -> concat ->
encode) instead of MoviePy's per-frame Python pump. No subprocess, no moviepy,
so it is fully unit-testable.

Each shot becomes one seeked input (`-ss start -t dur*speed -i source`) and a
filter chain that retimes (speed), fits to the output size (letterbox or cover
crop), and normalizes SAR/fps/pixfmt so the segments concatenate cleanly. The
encode flags mirror the MoviePy renderer exactly (CRF 18 / tune animation /
yuv420p / faststart / 192k AAC).
"""
from __future__ import annotations

from ..synthesis.timeline_schema import Shot, Timeline

DEFAULT_CROSSFADE_SEC = 0.25  # mirrors transitions.CROSSFADE_DURATION_SEC

# Phase 1 of the native renderer covers the base montage. Per-frame effects
# (freeze/punch_in), the flash bloom, and overlay skills are not ported yet, so
# timelines using them fall back to the MoviePy renderer (see render_timeline).
PHASE1_TRANSITIONS = frozenset({"cut", "crossfade", "whip"})


def can_render_with_ffmpeg(timeline: Timeline) -> bool:
    """True when the timeline only uses features the native renderer supports."""
    if timeline.overlays:
        return False
    for shot in timeline.shots:
        if shot.effects:
            return False
        if shot.transition_in.type not in PHASE1_TRANSITIONS:
            return False
    return True


def _shot_window(shot: Shot) -> tuple[float, float, float]:
    """(source_start_sec, input_seconds_to_read, speed). We read duration*speed
    seconds of source so that setpts=PTS/speed yields the shot's output duration,
    matching MoviePy's subclipped(...).with_speed_scaled(...).with_duration(...)."""
    speed = shot.speed or 1.0
    return shot.source.start_sec, shot.duration_sec * speed, speed


def _video_chain(idx: int, shot: Shot, w: int, h: int, fps: int,
                 crop: str, focus_x: float, out_label: str) -> str:
    chain: list[str] = []
    speed = shot.speed or 1.0
    if speed != 1.0:
        chain.append(f"setpts=PTS/{speed:g}")
    if crop in ("fill", "center"):
        # Cover the frame then crop; x offset honors crop_focus_x, y centers.
        # Mirrors geometry.cover_crop_offsets: x = (scaled_w - W) * focus_x.
        chain.append(f"scale={w}:{h}:force_original_aspect_ratio=increase")
        chain.append(f"crop={w}:{h}:(iw-{w})*{focus_x:g}:(ih-{h})/2")
    else:  # letterbox / per_shot
        chain.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
        chain.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    chain += ["setsar=1", f"fps={fps}", "format=yuv420p"]
    return f"[{idx}:v]" + ",".join(chain) + f"[{out_label}]"


def _assemble_video(parts: list[str], shots: list[Shot]) -> str:
    """Join the per-shot `[v{i}]` streams into one `[vout]`-style label.

    Pure cuts collapse into a single `concat=n=N` (the fast common path). When
    any shot uses a crossfade, fold left-to-right so each boundary is either a
    2-way `concat` (cut) or an `xfade` whose `offset` is the start time of the
    transition within the accumulated stream (cumulative across prior shots)."""
    n = len(shots)
    if n == 1:
        return "[v0]"
    if not any(s.transition_in.type == "crossfade" for s in shots[1:]):
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1[vout]")
        return "[vout]"

    acc = "v0"
    acc_dur = shots[0].duration_sec
    for i in range(1, n):
        out = f"m{i - 1}"
        shot = shots[i]
        if shot.transition_in.type == "crossfade":
            d = shot.transition_in.duration_sec or DEFAULT_CROSSFADE_SEC
            d = min(d, acc_dur, shot.duration_sec)
            offset = acc_dur - d
            parts.append(
                f"[{acc}][v{i}]xfade=transition=fade:duration={d:g}:offset={offset:g}[{out}]"
            )
            acc_dur = acc_dur + shot.duration_sec - d
        else:
            parts.append(f"[{acc}][v{i}]concat=n=2:v=1[{out}]")
            acc_dur = acc_dur + shot.duration_sec
        acc = out
    return f"[{acc}]"


def _encode_tail(preset: str, threads: int | None, out_path: str) -> list[str]:
    tail = [
        "-c:v", "libx264", "-preset", preset, "-crf", "18",
        "-tune", "animation", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
    ]
    if threads:
        tail += ["-threads", str(threads)]
    tail.append(out_path)
    return tail


def build_command(
    timeline: Timeline,
    *,
    source: str,
    audio: str,
    out_path: str,
    preset: str = "medium",
    threads: int | None = None,
    size: tuple[int, int] | None = None,
    fps: int | None = None,
) -> list[str]:
    w, h = size or (timeline.output.width, timeline.output.height)
    out_fps = fps or timeline.output.fps
    crop = timeline.output.crop
    focus_x = timeline.output.crop_focus_x
    shots = timeline.shots
    n = len(shots)

    args = ["ffmpeg", "-y"]
    for shot in shots:
        start, in_secs, _ = _shot_window(shot)
        args += ["-ss", f"{start:.3f}", "-t", f"{in_secs:.3f}", "-i", source]
    args += ["-ss", f"{timeline.audio.start_sec:.3f}",
             "-t", f"{timeline.output.duration_sec:.3f}", "-i", audio]

    parts = [
        _video_chain(i, shot, w, h, out_fps, crop, focus_x, f"v{i}")
        for i, shot in enumerate(shots)
    ]
    video_label = _assemble_video(parts, shots)

    gain_db = timeline.audio.gain_db
    if gain_db:
        parts.append(f"[{n}:a]volume={gain_db}dB[aout]")
        audio_label = "[aout]"
    else:
        audio_label = f"{n}:a"

    args += ["-filter_complex", ";".join(parts), "-map", video_label, "-map", audio_label]
    args += _encode_tail(preset, threads, out_path)
    return args
