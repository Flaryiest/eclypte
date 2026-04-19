from .timeline_schema import Timeline

GAP_TOLERANCE_SEC = 1e-3


class TimelineError(ValueError):
    pass


def validate_timeline(
    timeline: Timeline,
    *,
    known_pattern_ids: set[str] | None = None,
    source_duration_sec: float | None = None,
) -> None:
    errors: list[str] = []

    if timeline.schema_version != 1:
        errors.append(f"schema_version must be 1, got {timeline.schema_version}")

    if not timeline.shots:
        errors.append("timeline has zero shots")

    for i, shot in enumerate(timeline.shots):
        if shot.index != i:
            errors.append(f"shot[{i}].index is {shot.index}, expected {i}")
        if shot.timeline_end_sec <= shot.timeline_start_sec:
            errors.append(f"shot[{i}] has non-positive duration")
        if shot.source.end_sec <= shot.source.start_sec:
            errors.append(f"shot[{i}] has non-positive source range")
        if shot.speed <= 0:
            errors.append(f"shot[{i}] has non-positive speed {shot.speed}")
        if shot.timeline_end_sec > timeline.output.duration_sec + GAP_TOLERANCE_SEC:
            errors.append(
                f"shot[{i}] timeline_end_sec {shot.timeline_end_sec} exceeds "
                f"output.duration_sec {timeline.output.duration_sec}"
            )
        src_dur = shot.source.end_sec - shot.source.start_sec
        needed = shot.duration_sec / shot.speed
        if src_dur + GAP_TOLERANCE_SEC < needed:
            errors.append(
                f"shot[{i}] source range {src_dur:.3f}s < needed {needed:.3f}s "
                f"(timeline={shot.duration_sec:.3f}s, speed={shot.speed})"
            )
        if source_duration_sec is not None and shot.source.end_sec > source_duration_sec + GAP_TOLERANCE_SEC:
            errors.append(
                f"shot[{i}] source.end_sec {shot.source.end_sec} exceeds "
                f"source video duration {source_duration_sec}"
            )

    for i in range(len(timeline.shots) - 1):
        a = timeline.shots[i]
        b = timeline.shots[i + 1]
        gap = b.timeline_start_sec - a.timeline_end_sec
        if abs(gap) > GAP_TOLERANCE_SEC:
            errors.append(
                f"gap/overlap of {gap:.4f}s between shot[{i}] and shot[{i + 1}]"
            )

    if known_pattern_ids is not None:
        for i, shot in enumerate(timeline.shots):
            refs = list(shot.pattern_refs)
            if shot.transition_in.pattern_ref:
                refs.append(shot.transition_in.pattern_ref)
            for eff in shot.effects:
                if eff.pattern_ref:
                    refs.append(eff.pattern_ref)
            for r in refs:
                if r not in known_pattern_ids:
                    errors.append(f"shot[{i}] references unknown pattern_id {r!r}")

    if errors:
        raise TimelineError("invalid timeline:\n  - " + "\n  - ".join(errors))
