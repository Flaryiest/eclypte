import pytest

from api.prototyping.edit.synthesis.timeline_schema import (
    AudioSpec,
    OutputSpec,
    Overlay,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
)
from api.prototyping.edit.synthesis.validators import TimelineError, validate_timeline


def _timeline(overlays):
    return Timeline(
        source=SourceRef(video="v.mp4", audio="a.wav"),
        output=OutputSpec(width=1080, height=1920, fps=30, duration_sec=6.0, crop="letterbox"),
        audio=AudioSpec(path="a.wav", start_sec=0.0),
        shots=[
            Shot(
                index=0,
                timeline_start_sec=0.0,
                timeline_end_sec=6.0,
                source=ShotSource(start_sec=0.0, end_sec=6.0),
            )
        ],
        overlays=overlays,
    )


def _overlay(skill_id="text.hook", start=0.0, end=1.5):
    return Overlay(
        skill_id=skill_id,
        timeline_start_sec=start,
        timeline_end_sec=end,
        params={"text": "hi"},
    )


def test_valid_overlay_passes():
    validate_timeline(_timeline([_overlay()]))


def test_overlay_end_beyond_duration_raises():
    with pytest.raises(TimelineError):
        validate_timeline(_timeline([_overlay(end=7.0)]))


def test_overlay_negative_start_raises():
    with pytest.raises(TimelineError):
        validate_timeline(_timeline([_overlay(start=-0.5)]))


def test_overlay_nonpositive_window_raises():
    with pytest.raises(TimelineError):
        validate_timeline(_timeline([_overlay(start=2.0, end=2.0)]))


def test_overlay_unknown_skill_raises():
    with pytest.raises(TimelineError):
        validate_timeline(_timeline([_overlay(skill_id="text.bogus")]))


def _lyrics_overlay(end=6.0):
    return Overlay(
        skill_id="lyrics.kinetic",
        timeline_start_sec=0.0,
        timeline_end_sec=end,
        params={
            "font_id": "anton",
            "lines": [
                {
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "words": [{"text": "hold", "start_sec": 0.0, "end_sec": 1.0}],
                }
            ],
        },
    )


def test_single_lyrics_overlay_passes():
    validate_timeline(_timeline([_lyrics_overlay()]))


def test_duplicate_singleton_skill_raises():
    with pytest.raises(TimelineError, match="singleton"):
        validate_timeline(_timeline([_lyrics_overlay(), _lyrics_overlay()]))


def test_duplicate_non_singleton_skill_is_fine():
    validate_timeline(_timeline([_overlay(end=1.0), _overlay(start=2.0, end=3.0)]))
