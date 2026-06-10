"""
Transition application.

Transitions are baked into the incoming shot's own frames so the concatenate
pipeline stays a simple sequence of fixed-duration clips: `flash` blends the
first ~80ms toward white, `crossfade` dissolves from the previous shot's final
frame. `whip` is still a no-op (falls back to a hard cut).
"""
import numpy as np

from ..synthesis.timeline_schema import Shot

FLASH_DURATION_SEC = 0.08
FLASH_PEAK = 0.85
CROSSFADE_DURATION_SEC = 0.25


def apply_transition(prev_clip, current_clip, shot: Shot):
    """Return current_clip, possibly modified for the incoming transition."""
    kind = shot.transition_in.type
    if kind == "flash":
        return _flash(current_clip, shot.transition_in.duration_sec or FLASH_DURATION_SEC)
    if kind == "crossfade" and prev_clip is not None:
        return _crossfade(
            prev_clip,
            current_clip,
            shot.transition_in.duration_sec or CROSSFADE_DURATION_SEC,
        )
    if kind not in {"cut", "crossfade"}:
        print(f"[render] transition '{kind}' not implemented — using cut")
    return current_clip


def _flash(clip, duration_sec: float):
    duration = min(float(duration_sec), max(float(clip.duration or 0.0), 1e-6))

    def blend(get_frame, t):
        frame = get_frame(t)
        if t >= duration:
            return frame
        alpha = FLASH_PEAK * (1.0 - t / duration)
        mixed = frame.astype(np.float32) * (1.0 - alpha) + 255.0 * alpha
        return mixed.astype("uint8")

    return clip.transform(blend)


def _crossfade(prev_clip, clip, duration_sec: float):
    duration = min(float(duration_sec), float(clip.duration or 0.0) / 2.0)
    if duration <= 0:
        return clip
    # Dissolve from the previous shot's final frame, captured once up front.
    prev_t = max(0.0, float(prev_clip.duration or 0.0) - 1.0 / 30.0)
    base = np.asarray(prev_clip.get_frame(prev_t)).astype(np.float32)

    def blend(get_frame, t):
        frame = get_frame(t)
        if t >= duration or base.shape != frame.shape:
            return frame
        alpha = t / duration
        mixed = base * (1.0 - alpha) + frame.astype(np.float32) * alpha
        return mixed.astype("uint8")

    return clip.transform(blend)
