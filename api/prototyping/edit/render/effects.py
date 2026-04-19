"""
Per-shot effect application.

Phase 1: effects are recorded in the timeline but render as no-ops (logged).
Freeze requires splitting a clip; speed_ramp requires piecewise re-timing.
Both deferred to Phase 2 so the walking skeleton stays simple.
"""
from ..synthesis.timeline_schema import Effect, Shot

_SUPPORTED: set[str] = set()


def apply_effects(clip, shot: Shot):
    for eff in shot.effects:
        _apply_one(clip, eff)
    return clip


def _apply_one(clip, effect: Effect):
    if effect.type in _SUPPORTED:
        return clip
    print(f"[render] effect '{effect.type}' not implemented in Phase 1 — skipping "
          f"(pattern_ref={effect.pattern_ref})")
    return clip
