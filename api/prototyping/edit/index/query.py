"""
Clip retrieval interface.

Phase 1: ranks scenes by motion.avg_intensity proximity to an energy target.
No embeddings, no semantic matching — just motion statistics.

Phase 3 will swap the body for CLIP similarity. The signature must stay
stable so callers (planner, agent) don't need to change.
"""
from pathlib import Path

MIN_SCORE = 1e-6


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
) -> list[dict]:
    """
    Return up to `n` candidate ranges ordered by score (highest first).

    Each result: {"start_sec", "end_sec", "score", "scene_index"}.

    `query_text` is ignored in Phase 1. It's part of the signature so Phase 3
    can wire in CLIP similarity without a caller-side change.

    `section` is the song segment being filled, shape {label, start_sec, end_sec}.
    `energy_target` in [0, 1] biases selection toward scenes with matching motion.
    """
    del query_text, section, embeddings_path  # Phase-3 hooks.

    excluded = exclude_scene_indices or set()
    candidates: list[tuple[float, dict]] = []

    for scene in scenes:
        if scene.get("index") in excluded:
            continue
        duration = float(scene.get("duration_sec", 0.0))
        if duration < min_duration_sec:
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

        candidates.append((score, {
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "score": round(score, 4),
            "scene_index": int(scene["index"]),
        }))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in candidates[:n]]
