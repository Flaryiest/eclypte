import pytest

from api.prototyping.edit.synthesis.adapter import adapt
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
    with pytest.raises(ValueError, match="exceeds source video duration"):
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
