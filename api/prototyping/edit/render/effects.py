"""
Per-shot effect application.

Implemented as per-frame transforms so duration, size, and audio wiring are
always preserved: `freeze` (hold the shot's first frame), `punch_in` (slow
center zoom over the shot). `speed_ramp` and `hold` remain no-ops (logged);
piecewise re-timing is deferred.
"""
import numpy as np
from PIL import Image

from ..synthesis.timeline_schema import Effect, Shot

PUNCH_IN_END_SCALE = 1.06


def apply_effects(clip, shot: Shot):
    for eff in shot.effects:
        clip = _apply_one(clip, eff)
    return clip


def _apply_one(clip, effect: Effect):
    if effect.type == "freeze":
        return clip.transform(lambda gf, t: gf(0.0))
    if effect.type == "punch_in":
        return _punch_in(clip)
    print(f"[render] effect '{effect.type}' not implemented — skipping "
          f"(pattern_ref={effect.pattern_ref})")
    return clip


def _punch_in(clip):
    duration = max(float(clip.duration or 0.0), 1e-6)

    def zoom(get_frame, t):
        frame = get_frame(t)
        progress = min(max(t / duration, 0.0), 1.0)
        scale = 1.0 + (PUNCH_IN_END_SCALE - 1.0) * progress
        if scale <= 1.0:
            return frame
        h, w = frame.shape[:2]
        crop_w = max(2, int(round(w / scale)))
        crop_h = max(2, int(round(h / scale)))
        x0 = (w - crop_w) // 2
        y0 = (h - crop_h) // 2
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        resized = Image.fromarray(cropped).resize((w, h), Image.LANCZOS)
        return np.asarray(resized)

    return clip.transform(zoom)
