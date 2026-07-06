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

from ..skills.base import RenderContext, ResolvedOverlay
from ..synthesis.timeline_schema import SPEED_RAMP_END, Shot, Timeline

DEFAULT_CROSSFADE_SEC = 0.25  # mirrors transitions.CROSSFADE_DURATION_SEC
PUNCH_IN_END_SCALE = 1.06     # mirrors effects.PUNCH_IN_END_SCALE
FREEZE_INPUT_SEC = 0.2        # tiny input window for a frozen shot
FREEZE_PAD_EXTRA_SEC = 0.5    # clone slack before the exact re-trim
FLASH_DURATION_SEC = 0.12     # mirrors transitions.BLOOM_DURATION_SEC
# transitions.py lifts brightness multiplicatively (peak x1.18); eq=brightness
# is an additive luma shift, so +0.09 approximates that peak on mid-gray.
FLASH_PEAK_BRIGHTNESS = 0.09

# Features the native renderer implements. Transitions/effects outside these
# sets — and overlay skills without an ffmpeg port (ffmpeg_supported=False) —
# fall back to the MoviePy renderer (see render_timeline).
FFMPEG_TRANSITIONS = frozenset({"cut", "crossfade", "whip", "flash"})
FFMPEG_EFFECTS = frozenset({"freeze", "punch_in", "speed_ramp"})


def _has_effect(shot: Shot, effect_type: str) -> bool:
    return any(e.type == effect_type for e in shot.effects)


def _flash_steps(duration_sec: float) -> list[str]:
    """Discrete approximation of transitions._bloom's sine envelope: three
    equal windows lifting luma half-peak / peak / half-peak, gated with
    ffmpeg's `enable` in the incoming shot's local time (pre-concat)."""
    third = duration_sec / 3.0
    half = FLASH_PEAK_BRIGHTNESS / 2.0
    steps = []
    for i, level in enumerate((half, FLASH_PEAK_BRIGHTNESS, half)):
        lo, hi = i * third, (i + 1) * third
        steps.append(f"eq=brightness={level:g}:enable='between(t,{lo:.3f},{hi:.3f})'")
    return steps


def can_render_with_ffmpeg(timeline: Timeline) -> bool:
    """True when the timeline only uses features the native renderer supports.

    Capability-driven: overlay skills declare their own ffmpeg support in the
    registry, so a newly ported skill extends the fast path without touching
    this gate."""
    if timeline.overlays:
        from .. import skills  # registry (moviepy-free metadata)

        known = skills.ids()
        for ov in timeline.overlays:
            if ov.skill_id not in known or not skills.get(ov.skill_id).ffmpeg_supported:
                return False
    for shot in timeline.shots:
        for effect in shot.effects:
            if effect.type not in FFMPEG_EFFECTS:
                return False
        if shot.transition_in.type not in FFMPEG_TRANSITIONS:
            return False
    return True


def _shot_input_windows(shot: Shot) -> list[tuple[float, float]]:
    """Per-shot (source_start_sec, input_seconds_to_read) windows.

    Normal shots read duration*speed seconds so setpts=PTS/speed yields the
    output duration. A frozen shot reads a tiny window (its chain clones the
    first frame). A speed_ramp shot reads TWO windows — the first half at 1x,
    the second half's footage (duration/2 * SPEED_RAMP_END) retimed to fit —
    which _ramp_chains concatenates back into one shot stream."""
    speed = shot.speed or 1.0
    if _has_effect(shot, "freeze"):
        return [(shot.source.start_sec, min(FREEZE_INPUT_SEC, shot.duration_sec))]
    if _has_effect(shot, "speed_ramp"):
        half = shot.duration_sec / 2.0
        return [
            (shot.source.start_sec, half),
            (shot.source.start_sec + half, half * SPEED_RAMP_END),
        ]
    return [(shot.source.start_sec, shot.duration_sec * speed)]


def _fit_chain(w: int, h: int, crop: str, focus_x: float) -> list[str]:
    if crop in ("fill", "center"):
        # Cover the frame then crop; x offset honors crop_focus_x, y centers.
        # Mirrors geometry.cover_crop_offsets: x = (scaled_w - W) * focus_x.
        return [
            f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}:(iw-{w})*{focus_x:g}:(ih-{h})/2",
        ]
    # letterbox / per_shot
    return [
        f"scale={w}:{h}:force_original_aspect_ratio=decrease",
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
    ]


def _video_chain(input_idx: int, shot: Shot, w: int, h: int, fps: int,
                 crop: str, focus_x: float, out_label: str) -> str:
    chain: list[str] = []
    speed = shot.speed or 1.0
    dur = shot.duration_sec
    frozen = _has_effect(shot, "freeze")
    if frozen:
        # Hold the first frame: keep exactly one frame, clone it past the shot
        # length, then re-trim to the exact duration after fps normalization.
        chain.append("trim=end_frame=1")
        chain.append(f"tpad=stop_mode=clone:stop_duration={dur + FREEZE_PAD_EXTRA_SEC:g}")
    elif speed != 1.0:
        chain.append(f"setpts=PTS/{speed:g}")
    chain += _fit_chain(w, h, crop, focus_x)
    if _has_effect(shot, "punch_in"):
        # Slow center zoom 1.0 -> PUNCH_IN_END_SCALE over the shot. crop can't
        # animate its w/h (config-time only), so zoompan does the zoom: `on` is
        # the output frame index, d=1 emits one frame per input frame. Mirrors
        # effects._punch_in.
        frames = max(1, round(dur * fps))
        chain.append(
            f"zoompan=z='1+{PUNCH_IN_END_SCALE - 1.0:g}*on/{frames}':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
        )
    if shot.transition_in.type == "flash":
        chain += _flash_steps(shot.transition_in.duration_sec or FLASH_DURATION_SEC)
    chain += ["setsar=1", f"fps={fps}", "format=yuv420p"]
    if frozen:
        chain.append(f"trim=duration={dur:.3f},setpts=PTS-STARTPTS")
    # Normalize the timebase: effect chains (tpad/zoompan) emit different
    # timebases than plain ones, and xfade refuses mismatched inputs.
    chain.append("settb=AVTB")
    return f"[{input_idx}:v]" + ",".join(chain) + f"[{out_label}]"


def _ramp_chains(shot_idx: int, in_a: int, in_b: int, shot: Shot,
                 w: int, h: int, fps: int, crop: str, focus_x: float) -> list[str]:
    """Two fitted halves — the second retimed to SPEED_RAMP_END x — concatenated
    back into the shot's `[v{shot_idx}]` stream."""
    fit = _fit_chain(w, h, crop, focus_x)
    tail = ["setsar=1", f"fps={fps}", "format=yuv420p", "settb=AVTB"]
    first = list(fit)
    if shot.transition_in.type == "flash":
        first += _flash_steps(shot.transition_in.duration_sec or FLASH_DURATION_SEC)
    return [
        f"[{in_a}:v]" + ",".join(first + tail) + f"[r{shot_idx}a]",
        f"[{in_b}:v]" + ",".join([f"setpts=PTS/{SPEED_RAMP_END:g}"] + fit + tail) + f"[r{shot_idx}b]",
        f"[r{shot_idx}a][r{shot_idx}b]concat=n=2:v=1[v{shot_idx}]",
    ]


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
    font_path: str | None = None,
) -> list[str]:
    w, h = size or (timeline.output.width, timeline.output.height)
    out_fps = fps or timeline.output.fps
    crop = timeline.output.crop
    focus_x = timeline.output.crop_focus_x
    shots = timeline.shots
    n = len(shots)

    args = ["ffmpeg", "-y"]
    input_map: list[list[int]] = []
    next_input = 0
    for shot in shots:
        indices: list[int] = []
        for start, in_secs in _shot_input_windows(shot):
            args += ["-ss", f"{start:.3f}", "-t", f"{in_secs:.3f}", "-i", source]
            indices.append(next_input)
            next_input += 1
        input_map.append(indices)
    audio_idx = next_input
    args += ["-ss", f"{timeline.audio.start_sec:.3f}",
             "-t", f"{timeline.output.duration_sec:.3f}", "-i", audio]

    parts: list[str] = []
    for i, shot in enumerate(shots):
        indices = input_map[i]
        if len(indices) == 2:
            parts += _ramp_chains(i, indices[0], indices[1], shot, w, h, out_fps, crop, focus_x)
        else:
            parts.append(_video_chain(indices[0], shot, w, h, out_fps, crop, focus_x, f"v{i}"))
    video_label = _assemble_video(parts, shots)

    # Skill fragments (vignette/text/grade/...) apply to the assembled stream,
    # before the tail fade so overlays fade to black with the picture.
    if timeline.overlays:
        from .. import skills  # registry (moviepy-free metadata)

        ctx = RenderContext(output_size=(w, h), fps=out_fps, font_path=font_path or "")
        for k, ov in enumerate(timeline.overlays):
            resolved = ResolvedOverlay(
                skill_id=ov.skill_id,
                timeline_start_sec=ov.timeline_start_sec,
                timeline_end_sec=ov.timeline_end_sec,
                params=ov.params,
            )
            fragment = skills.get(ov.skill_id).ffmpeg_filter(resolved, ctx)
            parts.append(f"{video_label}{fragment}[ov{k}]")
            video_label = f"[ov{k}]"

    fade_v = timeline.output.fade_out_sec
    if fade_v and fade_v > 0:
        # st uses the nominal duration_sec; if crossfades shrink the real video
        # stream (xfade overlap), this fade-out start is slightly approximate.
        # Cut-based reels (the autopilot default) are exact — revisit if
        # crossfade+fade combinations become common.
        st = max(0.0, timeline.output.duration_sec - fade_v)
        parts.append(f"{video_label}fade=t=out:st={st:.3f}:d={fade_v:g}[vfade]")
        video_label = "[vfade]"

    audio_filters: list[str] = []
    gain_db = timeline.audio.gain_db
    if gain_db:
        audio_filters.append(f"volume={gain_db}dB")
    fade_a = timeline.audio.fade_out_sec
    if fade_a and fade_a > 0:
        st = max(0.0, timeline.output.duration_sec - fade_a)
        audio_filters.append(f"afade=t=out:st={st:.3f}:d={fade_a:g}")
    if audio_filters:
        parts.append(f"[{audio_idx}:a]" + ",".join(audio_filters) + "[aout]")
        audio_label = "[aout]"
    else:
        audio_label = f"{audio_idx}:a"

    args += ["-filter_complex", ";".join(parts), "-map", video_label, "-map", audio_label]
    args += _encode_tail(preset, threads, out_path)
    return args
