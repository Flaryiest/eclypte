"""
Transition application.

Phase 1: only 'cut' is supported (zero-duration, no blending). Crossfade,
whip, and flash are Phase-2 work.
"""
from ..synthesis.timeline_schema import Shot


def apply_transition(prev_clip, current_clip, shot: Shot):
    """
    Return current_clip, possibly modified for the incoming transition.

    Phase 1 implementation: hard cut — return current_clip unchanged.
    The `prev_clip` arg exists for Phase-2 crossfade composition.
    """
    del prev_clip, shot
    return current_clip
