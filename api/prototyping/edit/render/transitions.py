"""
Transition application.

Transitions are baked into the incoming shot's own frames so the concatenate
pipeline stays a simple sequence of fixed-duration clips: `flash` blooms the
first ~120ms with a gentle brightness lift (a soft exposure pop that eases in
and out and never washes toward white), `crossfade` dissolves from the previous
shot's final frame. `whip` is still a no-op (falls back to a hard cut).
"""
import numpy as np

from ..synthesis.timeline_schema import Shot

BLOOM_DURATION_SEC = 0.12
BLOOM_PEAK = 0.18  # max fractional brightness lift at the peak of the bloom
CROSSFADE_DURATION_SEC = 0.25


def apply_transition(prev_clip, current_clip, shot: Shot):
    """Return current_clip, possibly modified for the incoming transition."""
    kind = shot.transition_in.type
    if kind == "flash":
        return _bloom(current_clip, shot.transition_in.duration_sec or BLOOM_DURATION_SEC)
    if kind == "crossfade" and prev_clip is not None:
        return _crossfade(
            prev_clip,
            current_clip,
            shot.transition_in.duration_sec or CROSSFADE_DURATION_SEC,
        )
    if kind not in {"cut", "crossfade"}:
        print(f"[render] transition '{kind}' not implemented — using cut")
    return current_clip


def _bloom(clip, duration_sec: float):
    duration = min(float(duration_sec), max(float(clip.duration or 0.0), 1e-6))

    def brighten(get_frame, t):
        frame = get_frame(t)
        if t >= duration:
            return frame
        # Smooth hump: 0 at the start, peak in the middle, back to 0 at the end,
        # so the incoming shot eases into the lift instead of slamming on frame one.
        envelope = np.sin(np.pi * (t / duration))
        gain = 1.0 + BLOOM_PEAK * envelope
        lifted = np.clip(frame.astype(np.float32) * gain, 0.0, 255.0)
        return lifted.astype("uint8")

    return clip.transform(brighten)


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
