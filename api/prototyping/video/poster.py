"""Representative poster-frame selection for source videos.

Pure policy module (no cv2/numpy/Modal imports) so it can be unit-tested and
bundled into the Modal image via add_local_python_source. The CUDA decode loop
feeds sampled frames' brightness/detail here; the picker tracks the best
candidate and the caller snapshots the pixels whenever consider() says so.
Thresholds mirror the CLIP index content filter so we never pick a black,
blown-out, or flat (title card / credits) frame.
"""

POSTER_MIN_BRIGHTNESS = 40.0
POSTER_MAX_BRIGHTNESS = 215.0
POSTER_MIN_DETAIL = 14.0
# Only frames in this fraction-of-duration window are considered; the target is
# ~20% in — past intros/logos, well before spoiler territory.
POSTER_WINDOW = (0.05, 0.45)
POSTER_TARGET_FRAC = 0.20
POSTER_SAMPLE_EVERY_SEC = 2.0


def score_poster_candidate(ts_frac: float, *, brightness: float, detail: float) -> float | None:
    """Score a sampled frame; None means rejected outright."""
    if not (POSTER_WINDOW[0] <= ts_frac <= POSTER_WINDOW[1]):
        return None
    if brightness < POSTER_MIN_BRIGHTNESS or brightness > POSTER_MAX_BRIGHTNESS:
        return None
    if detail < POSTER_MIN_DETAIL:
        return None
    # More texture is better; drifting from the target timestamp costs points.
    return detail - 60.0 * abs(ts_frac - POSTER_TARGET_FRAC)


class PosterPicker:
    def __init__(self, duration_sec: float):
        self._duration_sec = max(float(duration_sec), 1e-6)
        self._best_score: float | None = None
        self.best_ts_sec: float | None = None

    def consider(self, ts_sec: float, *, brightness: float, detail: float) -> bool:
        score = score_poster_candidate(
            ts_sec / self._duration_sec, brightness=brightness, detail=detail
        )
        if score is None:
            return False
        if self._best_score is not None and score <= self._best_score:
            return False
        self._best_score = score
        self.best_ts_sec = ts_sec
        return True
