"""
Clip retrieval.

Two independent retrieval functions:

- `query_ranges` (Phase-1): pure motion-statistics ranking over video scenes.
  No embeddings, no network. Used by the deterministic planner.
- `query_clips` (Phase-3): CLIP semantic similarity via Modal. Used by the
  synthesis agent.
"""
from pathlib import Path
from types import SimpleNamespace

try:
    import modal
except ImportError:  # pragma: no cover - exercised only in lightweight test envs.
    modal = SimpleNamespace(
        Function=SimpleNamespace(from_name=None),
        exception=SimpleNamespace(NotFoundError=RuntimeError),
    )

MIN_SCORE = 1e-6
_QUERY_FUNC = None

# Content-filter thresholds (0-255 scale) for excluding dead frames from CLIP
# results: frames dimmer than MIN_BRIGHTNESS (black/dark credits) or flatter than
# MIN_DETAIL (solid colors, title cards) are never returned. Tuned to err toward
# filtering; lower MIN_BRIGHTNESS if legitimately dark/moody shots get dropped.
MIN_BRIGHTNESS = 30.0
MIN_DETAIL = 12.0


def query_ranges(
    scenes: list[dict],
    section: dict,
    query_text: str,
    *,
    energy_target: float = 0.5,
    n: int = 5,
    min_duration_sec: float = 1.0,
    max_duration_sec: float = 4.0,
    exclude_scene_indices: set[int] | None = None,
    embeddings_path: Path | str | None = None,
    time_window: tuple[float, float] | None = None,
) -> list[dict]:
    """
    Return up to `n` candidate ranges ordered by score (highest first).

    Each result: {"start_sec", "end_sec", "score", "scene_index"}.

    `query_text` and `embeddings_path` are accepted and ignored - they exist
    so Phase-3 CLIP retrieval can be swapped in without changing callers.

    `time_window`, when given as `(lo, hi)`, restricts candidates to scenes whose
    midpoint falls within that source-time window. This lets the planner bias a
    shot toward the region of the source that matches its song position, so the
    edit spans the full source regardless of length.
    """
    del query_text, section, embeddings_path

    excluded = exclude_scene_indices or set()
    candidates: list[tuple[float, dict]] = []

    for scene in scenes:
        if scene.get("index") in excluded:
            continue
        duration = float(scene.get("duration_sec", 0.0))
        if duration < min_duration_sec:
            continue

        if time_window is not None:
            midpoint = (float(scene["start_sec"]) + float(scene["end_sec"])) / 2.0
            if not (time_window[0] <= midpoint <= time_window[1]):
                continue

        motion = scene.get("motion") or {}
        avg_intensity = float(motion.get("avg_intensity", 0.0))
        proximity = 1.0 - abs(avg_intensity - energy_target)
        score = max(MIN_SCORE, proximity)

        span = min(duration, max_duration_sec)
        peak_ts = motion.get("peak_timestamp_sec")
        scene_start = float(scene["start_sec"])
        scene_end = float(scene["end_sec"])
        if peak_ts is not None:
            center = max(scene_start, min(scene_end, float(peak_ts)))
        else:
            center = (scene_start + scene_end) / 2.0

        half = span / 2.0
        start = center - half
        end = center + half
        if start < scene_start:
            start, end = scene_start, scene_start + span
        elif end > scene_end:
            end, start = scene_end, scene_end - span

        candidates.append((
            score,
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "score": round(score, 4),
                "scene_index": int(scene["index"]),
            },
        ))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in candidates[:n]]


def rank_with_content_filter(
    timestamps,
    similarities,
    brightness=None,
    detail=None,
    *,
    top_k: int = 5,
    min_brightness: float = MIN_BRIGHTNESS,
    min_detail: float = MIN_DETAIL,
) -> list[dict]:
    """Return the top_k ``{timestamp, score}`` matches, excluding dead frames.

    Near-black (low brightness) and flat/solid (low detail) frames are dropped so
    black intros/outros, title cards, and end credits can never be selected. When
    `brightness`/`detail` are absent (an older index built before the filter), no
    filtering is applied. If every frame is flagged (degenerate clip), falls back to
    the unfiltered ranking so a result is still returned.
    """
    import numpy as np

    sims = np.asarray(similarities, dtype=np.float64)
    n = int(sims.shape[0])
    if n == 0:
        return []

    live = np.ones(n, dtype=bool)
    if brightness is not None and detail is not None:
        brightness = np.asarray(brightness, dtype=np.float64)
        detail = np.asarray(detail, dtype=np.float64)
        live = (brightness >= min_brightness) & (detail >= min_detail)

    live_idx = np.nonzero(live)[0]
    if live_idx.size == 0:
        live_idx = np.arange(n)

    order = live_idx[np.argsort(sims[live_idx])[::-1][:top_k]]
    return [
        {"timestamp": float(timestamps[i]), "score": float(sims[i])}
        for i in order
    ]


def _lookup_query_func(function_name: str):
    if getattr(modal.Function, "from_name", None) is None:
        raise RuntimeError(
            "Modal is not installed in this environment. Install the `modal` package "
            "or run the query paths where it is available."
        )
    try:
        return modal.Function.from_name("eclypte-query", function_name)
    except modal.exception.NotFoundError as exc:
        raise RuntimeError(
            f"Could not find Modal function eclypte-query::{function_name}. "
            "Have you deployed it?"
        ) from exc


def query_clips(query: str, video_filename: str, top_k: int = 5) -> list[dict]:
    """
    Locally callable proxy to the Modal CLIP query endpoint.
    Retrieves the top K matching timestamps for the text query from the
    video's prebuilt CLIP index on the eclypte-edit volume.
    """
    global _QUERY_FUNC
    if _QUERY_FUNC is None:
        _QUERY_FUNC = _lookup_query_func("query_index")
    return _QUERY_FUNC.remote(query, video_filename, top_k)
