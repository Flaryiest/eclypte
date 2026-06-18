from bisect import bisect_left

from .timeline_schema import (
    AudioSpec,
    Effect,
    Markers,
    OutputSpec,
    Overlay,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
    Transition,
)
from .validators import validate_timeline

SOURCE_TIMESTAMP_UNIQUENESS_SEC = 1.0
BEAT_SNAP_TOLERANCE_SEC = 0.15
MIN_SNAPPED_SHOT_SEC = 0.4
AGENT_TRANSITIONS = {"cut", "flash", "crossfade"}
AGENT_EFFECTS = {"freeze", "punch_in"}


def adapt(
    agent_output: list[dict],
    song: dict,
    video: dict,
    source_video_path: str,
    audio_path: str,
    output_size: tuple[int, int] = (1920, 1080),
    output_fps: int = 30,
    output_crop: str = "letterbox",
    crop_focus_x: float = 0.5,
    audio_start_sec: float = 0.0,
    overlays: list[dict] | None = None,
    content_end_sec: float | None = None,
) -> Timeline:
    """
    Convert `run_synthesis_loop` output into a validated renderable Timeline.

    agent_output items: {start_time, end_time, source_timestamp}.
    Source ranges are anchored at source_timestamp and shifted inward when
    the anchor+duration would run past the end of the source. Shot durations
    are preserved; timeline positions are rewritten contiguously (sorted by
    start_time) so the validator's no-gap/no-overlap rule is always met.
    """
    if not agent_output:
        raise ValueError("agent_output is empty")

    source_duration_sec = float(video["source"]["duration_sec"])
    # Cap the usable source to the detected content end (credit boundary) so no
    # shot can anchor into the end credits. Falls back to the full source.
    effective_source_end = source_duration_sec
    if content_end_sec is not None:
        effective_source_end = min(source_duration_sec, float(content_end_sec))

    ordered = sorted(agent_output, key=lambda s: float(s["start_time"]))

    shots: list[Shot] = []
    for i, raw in enumerate(ordered):
        start_time = float(raw["start_time"])
        end_time = float(raw["end_time"])
        src_ts = float(raw["source_timestamp"])

        duration = end_time - start_time
        if duration <= 0:
            raise ValueError(
                f"agent_output[{i}] has non-positive duration: "
                f"start_time={start_time}, end_time={end_time}"
            )
        if duration > effective_source_end:
            raise ValueError(
                f"agent_output[{i}] duration {duration:.3f}s exceeds "
                f"usable source duration {effective_source_end:.3f}s"
            )

        src_start = max(0.0, min(src_ts, effective_source_end - duration))
        src_end = src_start + duration

        # Optional agent-chosen styling; unknown values fall back to plain cuts.
        transition_raw = str(raw.get("transition_in") or "cut")
        effect_raw = str(raw.get("effect") or "")

        shots.append(
            Shot(
                index=i,
                timeline_start_sec=start_time,
                timeline_end_sec=end_time,
                source=ShotSource(start_sec=src_start, end_sec=src_end),
                transition_in=Transition(
                    type=transition_raw if transition_raw in AGENT_TRANSITIONS else "cut"
                ),
                effects=(
                    [Effect(type=effect_raw)] if effect_raw in AGENT_EFFECTS else []
                ),
            )
        )

    seen_source_starts: list[float] = []
    deduped: list[Shot] = []
    for shot in shots:
        if any(
            abs(shot.source.start_sec - seen) <= SOURCE_TIMESTAMP_UNIQUENESS_SEC
            for seen in seen_source_starts
        ):
            print(f"adapter: dropped duplicate source_timestamp {shot.source.start_sec:.3f}")
            continue
        seen_source_starts.append(shot.source.start_sec)
        deduped.append(shot)
    if not deduped:
        raise ValueError("all shots were duplicates")
    shots = deduped

    t = 0.0
    for i, shot in enumerate(shots):
        dur = round(shot.timeline_end_sec - shot.timeline_start_sec, 3)
        shots[i] = shot.model_copy(update={
            "index": i,
            "timeline_start_sec": round(t, 3),
            "timeline_end_sec": round(t + dur, 3),
        })
        t = round(t + dur, 3)
    last_end = t

    song_duration = float(song.get("source", {}).get("duration_sec", 0.0))
    if song_duration > 0 and last_end > song_duration:
        last = shots[-1]
        overshoot = last_end - song_duration
        new_end = last.timeline_end_sec - overshoot
        new_src_end = last.source.end_sec - overshoot
        if new_end <= last.timeline_start_sec or new_src_end <= last.source.start_sec:
            raise ValueError(
                f"adapter could not trim last shot to song duration "
                f"{song_duration:.3f}s without collapsing it"
            )
        shots[-1] = last.model_copy(update={
            "timeline_end_sec": round(new_end, 3),
            "source": ShotSource(
                start_sec=last.source.start_sec,
                end_sec=round(new_src_end, 3),
            ),
        })
        last_end = round(new_end, 3)

    shots, beats_used = snap_shots_to_beats(
        shots,
        [float(b) for b in song.get("beats_sec") or []],
        source_duration_sec=effective_source_end,
    )

    sections = [
        {
            "start_sec": float(s["start_sec"]),
            "end_sec": float(s["end_sec"]),
            "label": s["label"],
        }
        for s in song.get("segments", [])
    ]

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
        audio=AudioSpec(path=audio_path, start_sec=round(audio_start_sec, 3)),
        shots=shots,
        markers=Markers(beats_used_sec=beats_used, sections=sections),
        overlays=_resolve_overlays(overlays or [], round(last_end, 3)),
    )

    validate_timeline(timeline, source_duration_sec=effective_source_end)
    return timeline


def _resolve_overlays(raw_overlays: list[dict], duration_sec: float) -> list[Overlay]:
    """Validate agent overlay specs against the skill registry.

    Overlays are decorative, so a bad one is dropped (with a log) rather than
    failing the whole edit — mirroring how duplicate shots are dropped above.
    Each overlay's window is clamped into [0, duration_sec]; its params are
    validated against the named skill's params model.
    """
    from .. import skills  # registry of overlay skills (moviepy-free metadata)

    known = skills.ids()
    resolved: list[Overlay] = []
    for raw in raw_overlays:
        skill_id = str(raw.get("skill_id") or "")
        if skill_id not in known:
            print(f"adapter: dropped overlay with unknown skill_id {skill_id!r}")
            continue
        try:
            start = float(raw["start_time"])
            end = float(raw["end_time"])
        except (KeyError, TypeError, ValueError):
            print(f"adapter: dropped overlay {skill_id!r} with missing/invalid timing")
            continue
        start = max(0.0, min(start, duration_sec))
        end = min(end, duration_sec)
        if end - start <= 0:
            print(f"adapter: dropped overlay {skill_id!r} with non-positive window")
            continue
        candidate = {"text": raw["text"]} if raw.get("text") is not None else {}
        try:
            params = skills.get(skill_id).params_model(**candidate).model_dump()
        except Exception as exc:  # invalid params for this skill
            print(f"adapter: dropped overlay {skill_id!r} with invalid params: {exc}")
            continue
        resolved.append(
            Overlay(
                skill_id=skill_id,
                timeline_start_sec=round(start, 3),
                timeline_end_sec=round(end, 3),
                params=params,
            )
        )
    return resolved


def snap_shots_to_beats(
    shots: list[Shot],
    beats_sec: list[float],
    *,
    source_duration_sec: float,
    tolerance_sec: float = BEAT_SNAP_TOLERANCE_SEC,
) -> tuple[list[Shot], list[float]]:
    """Snap interior shot boundaries to the nearest beat within `tolerance_sec`.

    Cuts that land exactly on beats are what make an edit read as "on beat";
    the agent aims for this but its timestamps drift. The first boundary (0.0)
    and the final boundary (song end) stay fixed. Each snapped boundary moves
    the outgoing shot's timeline/source end and the incoming shot's timeline
    start + source end together, so contiguity and source-range/duration
    parity are preserved. A snap is skipped when it would push either shot
    below MIN_SNAPPED_SHOT_SEC or run the outgoing source range past the end
    of the source video. Returns the adjusted shots and the beat times used.
    """
    beats = sorted(b for b in beats_sec if b > 0)
    if not beats or len(shots) < 2:
        return shots, []

    def nearest_beat(t: float) -> float:
        i = bisect_left(beats, t)
        candidates = beats[max(0, i - 1):i + 1]
        return min(candidates, key=lambda b: abs(b - t))

    snapped = list(shots)
    beats_used: list[float] = []
    for i in range(len(snapped) - 1):
        out_shot = snapped[i]
        in_shot = snapped[i + 1]
        boundary = out_shot.timeline_end_sec
        beat = nearest_beat(boundary)
        delta = round(beat - boundary, 3)
        if abs(beat - boundary) > tolerance_sec:
            continue
        if delta == 0.0:
            beats_used.append(round(beat, 3))
            continue
        new_out_dur = (boundary + delta) - out_shot.timeline_start_sec
        new_in_dur = in_shot.timeline_end_sec - (boundary + delta)
        new_out_src_end = round(out_shot.source.end_sec + delta, 3)
        new_in_src_end = round(in_shot.source.end_sec - delta, 3)
        if new_out_dur < MIN_SNAPPED_SHOT_SEC or new_in_dur < MIN_SNAPPED_SHOT_SEC:
            continue
        if new_out_src_end > source_duration_sec or new_in_src_end > source_duration_sec:
            continue
        snapped[i] = out_shot.model_copy(update={
            "timeline_end_sec": round(boundary + delta, 3),
            "source": ShotSource(
                start_sec=out_shot.source.start_sec,
                end_sec=new_out_src_end,
            ),
        })
        snapped[i + 1] = in_shot.model_copy(update={
            "timeline_start_sec": round(boundary + delta, 3),
            "source": ShotSource(
                start_sec=in_shot.source.start_sec,
                end_sec=new_in_src_end,
            ),
        })
        beats_used.append(round(beat, 3))

    return snapped, sorted(set(beats_used))
