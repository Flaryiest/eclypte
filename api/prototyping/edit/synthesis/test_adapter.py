import pytest

from api.prototyping.edit.synthesis.adapter import adapt, snap_shots_to_beats
from api.prototyping.edit.synthesis.timeline_schema import Shot, ShotSource
from api.prototyping.edit.synthesis.validators import TimelineError, validate_timeline


SOURCE_DURATION = 300.0
SONG = {
    "source": {"duration_sec": 180.0},
    "segments": [
        {"start_sec": 0.0, "end_sec": 30.0, "label": "intro"},
        {"start_sec": 30.0, "end_sec": 90.0, "label": "chorus"},
    ],
}
VIDEO = {"source": {"duration_sec": SOURCE_DURATION}}
SRC_PATH = "video/content/source.mp4"
AUDIO_PATH = "music/content/output.wav"


def _three_shots_contiguous():
    return [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 2.0, "end_time": 4.5, "source_timestamp": 60.0},
        {"start_time": 4.5, "end_time": 6.0, "source_timestamp": 120.0},
    ]


def test_adapt_maps_overlays():
    overlays = [
        {"skill_id": "text.hook", "text": "no way", "start_time": 0.0, "end_time": 1.5},
        {"skill_id": "mask.vignette", "start_time": 0.0, "end_time": 6.0},
    ]
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH, overlays=overlays)

    assert len(tl.overlays) == 2
    hook = tl.overlays[0]
    assert hook.skill_id == "text.hook"
    assert hook.params == {"text": "no way"}
    assert hook.timeline_start_sec == pytest.approx(0.0)
    assert hook.timeline_end_sec == pytest.approx(1.5)
    assert tl.overlays[1].skill_id == "mask.vignette"
    assert tl.overlays[1].params == {"strength": 0.6}


def test_adapt_without_overlays_is_empty():
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH)
    assert tl.overlays == []


def test_adapt_drops_unknown_skill_overlay():
    overlays = [{"skill_id": "text.bogus", "text": "x", "start_time": 0.0, "end_time": 1.0}]
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH, overlays=overlays)
    assert tl.overlays == []


def test_adapt_drops_overlay_with_invalid_params():
    # A text skill with empty text fails its params model -> dropped, not raised.
    overlays = [{"skill_id": "text.hook", "text": "", "start_time": 0.0, "end_time": 1.0}]
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH, overlays=overlays)
    assert tl.overlays == []


def test_adapt_clamps_overlay_window_to_timeline():
    overlays = [{"skill_id": "mask.vignette", "start_time": -3.0, "end_time": 100.0}]
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH, overlays=overlays)
    ov = tl.overlays[0]
    assert ov.timeline_start_sec == pytest.approx(0.0)
    assert ov.timeline_end_sec == pytest.approx(tl.output.duration_sec)


def test_adapt_drops_overlay_with_nonpositive_window():
    overlays = [{"skill_id": "mask.vignette", "start_time": 5.0, "end_time": 5.0}]
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH, overlays=overlays)
    assert tl.overlays == []


def test_adapt_clamps_source_range_to_content_end():
    # Shots anchored deep in the source must be pulled back so their source
    # range never crosses content_end_sec (the credit boundary).
    shots = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 290.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 250.0},
    ]
    tl = adapt(shots, SONG, VIDEO, SRC_PATH, AUDIO_PATH, content_end_sec=200.0)
    for shot in tl.shots:
        assert shot.source.end_sec <= 200.0 + 1e-6


def test_adapt_without_content_end_uses_full_source():
    shots = [{"start_time": 0.0, "end_time": 2.0, "source_timestamp": 290.0}]
    tl = adapt(shots, SONG, VIDEO, SRC_PATH, AUDIO_PATH)
    # Anchor near the end stays near the end (clamped only by full source length).
    assert tl.shots[0].source.end_sec > 200.0


def test_basic_adapt():
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.schema_version == 1
    assert tl.source.video == SRC_PATH
    assert tl.source.audio == AUDIO_PATH
    assert tl.audio.path == AUDIO_PATH
    assert tl.audio.start_sec == 0.0
    assert tl.output.width == 1920
    assert tl.output.height == 1080
    assert tl.output.fps == 30
    assert tl.output.duration_sec == pytest.approx(6.0)
    assert len(tl.shots) == 3
    assert tl.shots[0].source.start_sec == 10.0
    assert tl.shots[0].source.end_sec == pytest.approx(12.0)
    assert tl.shots[1].source.start_sec == 60.0
    assert tl.shots[1].source.end_sec == pytest.approx(62.5)
    assert len(tl.markers.sections) == 2
    assert tl.markers.sections[0]["label"] == "intro"
    assert tl.markers.beats_used_sec == []


def test_gappy_input_repaired():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 3.0, "end_time": 5.0, "source_timestamp": 60.0},
        {"start_time": 7.0, "end_time": 8.5, "source_timestamp": 120.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].timeline_start_sec == 0.0
    assert tl.shots[0].timeline_end_sec == pytest.approx(2.0)
    assert tl.shots[1].timeline_start_sec == pytest.approx(2.0)
    assert tl.shots[1].timeline_end_sec == pytest.approx(4.0)
    assert tl.shots[2].timeline_start_sec == pytest.approx(4.0)
    assert tl.shots[2].timeline_end_sec == pytest.approx(5.5)
    assert tl.output.duration_sec == pytest.approx(5.5)


def test_unsorted_input_sorted():
    agent = [
        {"start_time": 4.5, "end_time": 6.0, "source_timestamp": 120.0},
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 2.0, "end_time": 4.5, "source_timestamp": 60.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].source.start_sec == 10.0
    assert tl.shots[1].source.start_sec == 60.0
    assert tl.shots[2].source.start_sec == 120.0


def test_source_clamps_to_bounds():
    agent = [
        {"start_time": 0.0, "end_time": 5.0, "source_timestamp": 298.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].source.start_sec == pytest.approx(295.0)
    assert tl.shots[0].source.end_sec == pytest.approx(300.0)
    assert tl.shots[0].source.end_sec - tl.shots[0].source.start_sec == pytest.approx(5.0)


def test_source_clamps_when_timestamp_negative_edge():
    agent = [
        {"start_time": 0.0, "end_time": 5.0, "source_timestamp": -3.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].source.start_sec == 0.0
    assert tl.shots[0].source.end_sec == pytest.approx(5.0)


def test_empty_input_raises():
    with pytest.raises(ValueError, match="empty"):
        adapt([], SONG, VIDEO, SRC_PATH, AUDIO_PATH)


def test_non_positive_duration_raises():
    agent = [{"start_time": 2.0, "end_time": 2.0, "source_timestamp": 10.0}]
    with pytest.raises(ValueError, match="non-positive duration"):
        adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)


def test_duration_exceeds_source_raises():
    agent = [{"start_time": 0.0, "end_time": 400.0, "source_timestamp": 0.0}]
    with pytest.raises(ValueError, match="exceeds usable source duration"):
        adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)


def test_validator_runs():
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH)
    validate_timeline(tl, source_duration_sec=SOURCE_DURATION)


def test_custom_output_spec():
    tl = adapt(
        _three_shots_contiguous(),
        SONG,
        VIDEO,
        SRC_PATH,
        AUDIO_PATH,
        output_size=(1280, 720),
        output_fps=24,
    )
    assert tl.output.width == 1280
    assert tl.output.height == 720
    assert tl.output.fps == 24


def test_custom_export_options_are_preserved():
    tl = adapt(
        _three_shots_contiguous(),
        SONG,
        VIDEO,
        SRC_PATH,
        AUDIO_PATH,
        output_size=(1080, 1920),
        output_fps=30,
        output_crop="fill",
        crop_focus_x=0.75,
        audio_start_sec=12.5,
    )

    assert tl.output.width == 1080
    assert tl.output.height == 1920
    assert tl.output.crop == "fill"
    assert tl.output.crop_focus_x == 0.75
    assert tl.audio.start_sec == 12.5


def test_missing_segments_ok():
    song_no_segs = {"source": {"duration_sec": 180.0}}
    tl = adapt(_three_shots_contiguous(), song_no_segs, VIDEO, SRC_PATH, AUDIO_PATH)
    assert tl.markers.sections == []


def test_duplicate_source_timestamps_dropped():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 10.0},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 60.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert len(tl.shots) == 2
    assert tl.shots[0].source.start_sec == 10.0
    assert tl.shots[1].source.start_sec == 60.0


def test_near_duplicate_within_tolerance_dropped():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 100.00},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 100.05},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 60.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert len(tl.shots) == 2
    assert tl.shots[0].source.start_sec == pytest.approx(100.0)
    assert tl.shots[1].source.start_sec == 60.0


def test_source_timestamps_one_second_apart_are_dropped():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 100.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 101.0},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 60.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert len(tl.shots) == 2
    assert tl.shots[0].source.start_sec == pytest.approx(100.0)
    assert tl.shots[1].source.start_sec == 60.0


def test_source_timestamps_more_than_one_second_apart_are_kept():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 100.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 101.001},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 60.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert len(tl.shots) == 3
    assert tl.shots[0].source.start_sec == pytest.approx(100.0)
    assert tl.shots[1].source.start_sec == pytest.approx(101.001)
    assert tl.shots[2].source.start_sec == 60.0


def test_duplicates_not_adjacent_dropped():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 60.0},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 10.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert len(tl.shots) == 2
    assert tl.shots[0].source.start_sec == 10.0
    assert tl.shots[1].source.start_sec == 60.0


def test_all_duplicates_collapse_to_one():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 10.05},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 10.0},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)
    assert len(tl.shots) == 1
    assert tl.shots[0].source.start_sec == 10.0


def test_adapt_maps_agent_transitions_and_effects():
    agent = [
        {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 10.0,
         "transition_in": "flash", "effect": "freeze"},
        {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 60.0,
         "effect": "punch_in"},
        {"start_time": 4.0, "end_time": 6.0, "source_timestamp": 120.0,
         "transition_in": "wormhole", "effect": "explode"},
    ]
    tl = adapt(agent, SONG, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].transition_in.type == "flash"
    assert [e.type for e in tl.shots[0].effects] == ["freeze"]
    assert tl.shots[1].transition_in.type == "cut"
    assert [e.type for e in tl.shots[1].effects] == ["punch_in"]
    # unknown values fall back to plain cut / no effects
    assert tl.shots[2].transition_in.type == "cut"
    assert tl.shots[2].effects == []


def _shot(index, start, end, src_start):
    return Shot(
        index=index,
        timeline_start_sec=start,
        timeline_end_sec=end,
        source=ShotSource(start_sec=src_start, end_sec=src_start + (end - start)),
    )


def test_adapt_snaps_interior_boundaries_to_beats():
    song = {
        "source": {"duration_sec": 180.0},
        "beats_sec": [0.5, 2.0, 4.5, 7.0],
    }
    agent = [
        {"start_time": 0.0, "end_time": 2.1, "source_timestamp": 10.0},
        {"start_time": 2.1, "end_time": 4.4, "source_timestamp": 60.0},
        {"start_time": 4.4, "end_time": 6.0, "source_timestamp": 120.0},
    ]
    tl = adapt(agent, song, VIDEO, SRC_PATH, AUDIO_PATH)

    assert tl.shots[0].timeline_end_sec == pytest.approx(2.0)
    assert tl.shots[1].timeline_start_sec == pytest.approx(2.0)
    assert tl.shots[1].timeline_end_sec == pytest.approx(4.5)
    assert tl.shots[2].timeline_start_sec == pytest.approx(4.5)
    # final boundary is fixed even though 6.0 has no beat
    assert tl.shots[2].timeline_end_sec == pytest.approx(6.0)
    assert tl.output.duration_sec == pytest.approx(6.0)
    # source ranges track the new durations from each shot's chosen start
    assert tl.shots[0].source.end_sec == pytest.approx(12.0)
    assert tl.shots[1].source.start_sec == pytest.approx(60.0)
    assert tl.shots[1].source.end_sec == pytest.approx(62.5)
    assert tl.markers.beats_used_sec == [2.0, 4.5]
    validate_timeline(tl, source_duration_sec=SOURCE_DURATION)


def test_snap_ignores_beats_outside_tolerance():
    shots = [_shot(0, 0.0, 2.3, 10.0), _shot(1, 2.3, 6.0, 60.0)]
    snapped, beats_used = snap_shots_to_beats(
        shots, [2.0, 6.0], source_duration_sec=SOURCE_DURATION
    )

    assert snapped[0].timeline_end_sec == pytest.approx(2.3)
    assert beats_used == []


def test_snap_skips_when_shot_would_collapse():
    shots = [
        _shot(0, 0.0, 2.0, 10.0),
        _shot(1, 2.0, 2.45, 60.0),
        _shot(2, 2.45, 6.0, 120.0),
    ]
    snapped, beats_used = snap_shots_to_beats(
        shots, [2.1], source_duration_sec=SOURCE_DURATION
    )

    assert [s.timeline_end_sec for s in snapped] == [2.0, 2.45, 6.0]
    assert beats_used == []


def test_snap_skips_when_source_would_overrun():
    shots = [_shot(0, 0.0, 2.0, 298.0), _shot(1, 2.0, 4.0, 60.0)]
    snapped, beats_used = snap_shots_to_beats(
        shots, [2.1], source_duration_sec=SOURCE_DURATION
    )

    assert snapped[0].timeline_end_sec == pytest.approx(2.0)
    assert snapped[0].source.end_sec == pytest.approx(300.0)
    assert beats_used == []


def test_snap_records_boundary_already_on_beat():
    shots = [_shot(0, 0.0, 2.0, 10.0), _shot(1, 2.0, 4.0, 60.0)]
    snapped, beats_used = snap_shots_to_beats(
        shots, [2.0], source_duration_sec=SOURCE_DURATION
    )

    assert snapped[0].timeline_end_sec == pytest.approx(2.0)
    assert snapped[1].timeline_start_sec == pytest.approx(2.0)
    assert beats_used == [2.0]


def test_tail_fade_for_clamps_to_a_third_of_short_reels():
    from api.prototyping.edit.synthesis.timeline_schema import TAIL_FADE_SEC, tail_fade_for

    assert tail_fade_for(30.0) == TAIL_FADE_SEC      # long reel -> full fade
    assert tail_fade_for(6.0) == 2.0                 # short reel -> clamped to dur/3
    assert tail_fade_for(0.0) == 0.0


def test_adapt_sets_tail_fade_on_audio_and_output():
    tl = adapt(_three_shots_contiguous(), SONG, VIDEO, SRC_PATH, AUDIO_PATH)
    # _three_shots_contiguous totals 6.0s -> clamped fade of 2.0s on both streams.
    assert tl.output.fade_out_sec == 2.0
    assert tl.audio.fade_out_sec == 2.0
