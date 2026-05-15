"""
Deterministic Phase-1 planner.

Walks song segments, emits one shot per downbeat (or every 2 downbeats,
depending on section label), picks source ranges by motion-intensity proximity
to a per-label energy target. Hard cuts only. No LLM, no embeddings.
"""
from __future__ import annotations

from pathlib import Path

from ..index.query import query_ranges
from ..patterns import compose, registry
from ..patterns.schema import Pattern
from .prompt import energy_target_for, intent_for
from .timeline_schema import (
    AudioSpec,
    Effect,
    OutputSpec,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
    Transition,
)
from .validators import validate_timeline

MIN_SHOT_SEC = 0.2
DEFAULT_FPS = 30
DEFAULT_SIZE = (1920, 1080)


def plan(
    song: dict,
    video: dict,
    *,
    source_video_path: str,
    audio_path: str,
    patterns: list[Pattern] | None = None,
    patterns_path: Path | str | None = None,
    output_size: tuple[int, int] = DEFAULT_SIZE,
    output_fps: int = DEFAULT_FPS,
    output_crop: str = "letterbox",
    crop_focus_x: float = 0.5,
    audio_start_sec: float | None = None,
    max_duration_sec: float | None = None,
) -> Timeline:
    if patterns is None:
        patterns = registry.load(patterns_path)
    known_ids = registry.ids(patterns)

    bpm = float(song.get("tempo_bpm", 120.0))
    macro = compose.pick_macro(patterns, bpm=bpm)
    macro_refs = [macro.id] if macro else []

    downbeats = [float(d) for d in song.get("downbeats_sec") or []]
    segments = list(song.get("segments") or [])
    scenes = list(video.get("scenes") or [])
    source_duration = float(video["source"]["duration_sec"])

    if not segments:
        segments = [{
            "start_sec": 0.0,
            "end_sec": float(song["source"]["duration_sec"]),
            "label": "instrumental",
        }]

    explicit_audio_start = audio_start_sec is not None
    audio_start = 0.0 if explicit_audio_start else _pick_audio_start(segments[0], downbeats)
    render_audio_start = float(audio_start_sec) if explicit_audio_start else audio_start

    shots: list[Shot] = []
    last_scene: int | None = None
    beats_used: list[float] = []

    for seg in segments:
        label = str(seg.get("label", "instrumental"))
        seg_start = float(seg["start_sec"])
        seg_end = float(seg["end_sec"])
        meso = compose.pick_meso_for_section(
            patterns,
            section_label=label,
            avg_energy=energy_target_for(label),
            bpm=bpm,
        )
        meso_refs = [meso.id] if meso else []
        stride = _stride_for(label, meso)
        boundaries = _boundaries_in_segment(
            downbeats,
            seg_start,
            seg_end,
            stride,
            include_segment_start=explicit_audio_start,
        )

        energy_target = energy_target_for(label)
        query_text = intent_for(label)

        for i in range(len(boundaries) - 1):
            song_t0 = boundaries[i]
            song_t1 = boundaries[i + 1]
            timeline_t0 = song_t0 - audio_start
            timeline_t1 = song_t1 - audio_start
            if timeline_t0 < 0:
                continue
            duration = timeline_t1 - timeline_t0
            if duration < MIN_SHOT_SEC:
                continue

            pick = _pick_range(
                scenes,
                {"label": label, "start_sec": seg_start, "end_sec": seg_end},
                query_text,
                energy_target=energy_target,
                duration=duration,
                exclude={last_scene} if last_scene is not None else set(),
            )
            if pick is None:
                continue
            last_scene = pick["scene_index"]
            beats_used.append(round(song_t0, 3))
            source_start, source_end, speed = _fit_source_range(
                pick_start_sec=float(pick["start_sec"]),
                shot_duration_sec=duration,
                source_duration_sec=source_duration,
            )

            shots.append(Shot(
                index=len(shots),
                timeline_start_sec=round(timeline_t0, 3),
                timeline_end_sec=round(timeline_t1, 3),
                source=ShotSource(
                    start_sec=round(source_start, 3),
                    end_sec=round(source_end, 3),
                ),
                speed=round(speed, 3),
                effects=_effects_for(label, meso, scenes, pick),
                transition_in=Transition(
                    type="cut",
                    duration_sec=0.0,
                    pattern_ref="transition.hard_cut" if "transition.hard_cut" in known_ids else None,
                ),
                pattern_refs=[*macro_refs, *meso_refs, "micro.beat_cut_on_downbeat"],
            ))

    if not shots:
        raise ValueError("planner produced zero shots (check segments/downbeats)")

    # Stitch: rewrite timeline times so shots are perfectly contiguous.
    # Beat alignment to original song grid is preserved within segments;
    # any gaps from skipped shots or segment-boundary mismatches are closed here.
    t = 0.0
    for i, shot in enumerate(shots):
        dur = round(shot.timeline_end_sec - shot.timeline_start_sec, 3)
        shots[i] = shot.model_copy(update={
            "index": i,
            "timeline_start_sec": round(t, 3),
            "timeline_end_sec": round(t + dur, 3),
        })
        t = round(t + dur, 3)

    last_end = shots[-1].timeline_end_sec
    if max_duration_sec is not None and last_end > max_duration_sec:
        shots = [s for s in shots if s.timeline_end_sec <= max_duration_sec]
        if not shots:
            raise ValueError("max_duration_sec shorter than first shot")
        last_end = shots[-1].timeline_end_sec

    timeline = Timeline(
        source=SourceRef(video=source_video_path, audio=audio_path),
        output=OutputSpec(
            width=output_size[0],
            height=output_size[1],
            fps=output_fps,
            duration_sec=round(last_end, 3),
            crop=output_crop,
            crop_focus_x=crop_focus_x,
        ),
        audio=AudioSpec(path=audio_path, start_sec=round(render_audio_start, 3)),
        shots=shots,
        markers={
            "beats_used_sec": beats_used,
            "sections": [
                {"start_sec": float(s["start_sec"]), "end_sec": float(s["end_sec"]), "label": s["label"]}
                for s in segments
            ],
        },
    )

    validate_timeline(
        timeline,
        known_pattern_ids=known_ids,
        source_duration_sec=source_duration,
    )
    return timeline


def _fit_source_range(
    *,
    pick_start_sec: float,
    shot_duration_sec: float,
    source_duration_sec: float,
) -> tuple[float, float, float]:
    source_span = min(shot_duration_sec, source_duration_sec)
    if source_span <= 0:
        return 0.0, 0.0, 1.0
    source_start = max(0.0, min(pick_start_sec, source_duration_sec - source_span))
    source_end = source_start + source_span
    speed = shot_duration_sec / source_span
    return source_start, source_end, speed


def _pick_audio_start(first_segment: dict, downbeats: list[float]) -> float:
    seg_start = float(first_segment["start_sec"])
    seg_end = float(first_segment["end_sec"])
    for d in downbeats:
        if seg_start <= d < seg_end:
            return d
    return seg_start


def _stride_for(label: str, meso: Pattern | None) -> int:
    if meso is not None:
        density = meso.params.get("cut_density_per_beat")
        if density is not None:
            val = float(density.default)
            if val >= 1.0:
                return 1
            if val >= 0.5:
                return 2
            return max(1, round(1.0 / val))
    return 1 if label == "chorus" else 2


def _boundaries_in_segment(
    downbeats: list[float],
    seg_start: float,
    seg_end: float,
    stride: int,
    *,
    include_segment_start: bool = False,
) -> list[float]:
    db_in = [d for d in downbeats if seg_start <= d < seg_end]
    if len(db_in) < 2:
        span = seg_end - seg_start
        n = max(2, int(span / 2.0))
        return [seg_start + i * span / (n - 1) for i in range(n)]
    grid = db_in[::stride]
    if include_segment_start and grid[0] > seg_start:
        grid.insert(0, seg_start)
    if grid[-1] < seg_end:
        grid.append(seg_end)
    return grid


def _pick_range(
    scenes: list[dict],
    section: dict,
    query_text: str,
    *,
    energy_target: float,
    duration: float,
    exclude: set[int],
) -> dict | None:
    # Try progressively looser constraints — always return something.
    for ex, min_dur in [
        (exclude, duration),
        (set(),   duration),
        (set(),   max(0.3, duration * 0.5)),
        (set(),   0.0),
    ]:
        ranges = query_ranges(
            scenes,
            section=section,
            query_text=query_text,
            energy_target=energy_target,
            n=8,
            min_duration_sec=min_dur,
            max_duration_sec=duration + 2.0,
            exclude_scene_indices=ex,
        )
        if ranges:
            return ranges[0]
    return None


def _effects_for(
    label: str,
    meso: Pattern | None,
    scenes: list[dict],
    pick: dict,
) -> list[Effect]:
    if meso is None:
        return []
    if "shot_move.freeze_on_stillness" not in {r for r in meso.composes_with.requires}:
        return []
    scene = next((s for s in scenes if s["index"] == pick["scene_index"]), None)
    if scene is None:
        return []
    stillness = (scene.get("impacts") or {}).get("stillness_points") or []
    if not stillness:
        return []
    sp = stillness[0]
    at_sec = float(sp["timestamp_sec"])
    if not (pick["start_sec"] <= at_sec <= pick["start_sec"] + (pick["end_sec"] - pick["start_sec"])):
        return []
    return [Effect(
        type="freeze",
        at_sec=round(at_sec, 3),
        duration_sec=0.12,
        pattern_ref="shot_move.freeze_on_stillness",
    )]
