from .timeline_schema import (
    AudioSpec,
    Markers,
    OutputSpec,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
)
from .validators import validate_timeline

SOURCE_TIMESTAMP_UNIQUENESS_SEC = 1.0


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
        if duration > source_duration_sec:
            raise ValueError(
                f"agent_output[{i}] duration {duration:.3f}s exceeds "
                f"source video duration {source_duration_sec:.3f}s"
            )

        src_start = max(0.0, min(src_ts, source_duration_sec - duration))
        src_end = src_start + duration

        shots.append(
            Shot(
                index=i,
                timeline_start_sec=start_time,
                timeline_end_sec=end_time,
                source=ShotSource(start_sec=src_start, end_sec=src_end),
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
        markers=Markers(beats_used_sec=[], sections=sections),
    )

    validate_timeline(timeline, source_duration_sec=source_duration_sec)
    return timeline
