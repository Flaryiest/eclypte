"""Tests for the footage sampling seam: everything except the moviepy decode
is pure numpy, so band mapping, hue math, and sample-time policy run anywhere."""
import pytest

np = pytest.importorskip("numpy")

from api.prototyping.edit.render.footage_stats import (
    SAMPLE_FRACS,
    dominant_hue,
    fit_frame_to_canvas,
    sample_source_times,
    zone_stats_for_canvas,
)
from api.prototyping.edit.skills.lyrics_layout import band_pixel_ranges
from api.prototyping.edit.synthesis.timeline_schema import (
    Effect,
    Shot,
    ShotSource,
    Transition,
)


def _shot(start=10.0, end=14.0, effects=()):
    return Shot(
        index=0,
        timeline_start_sec=0.0,
        timeline_end_sec=end - start,
        source=ShotSource(start_sec=start, end_sec=end),
        transition_in=Transition(type="cut"),
        effects=list(effects),
    )


# --- sample-time policy -----------------------------------------------------


def test_sample_source_times_spreads_over_source_window():
    times = sample_source_times(_shot(10.0, 14.0))
    assert times == [10.0 + f * 4.0 for f in SAMPLE_FRACS]


def test_sample_source_times_speed_ramp_stays_in_first_half():
    # the ramp's second half breaks the 1:1 time mapping (mirrors rhythm.py's
    # registration skip) — every sample must sit in the first 50% of the window
    times = sample_source_times(_shot(10.0, 15.0, effects=[Effect(type="speed_ramp")]))
    assert all(10.0 <= t <= 12.5 for t in times)


def test_sample_source_times_freeze_samples_the_frozen_frame():
    assert sample_source_times(_shot(10.0, 14.0, effects=[Effect(type="freeze")])) == [10.0]


# --- canvas fitting ----------------------------------------------------------


def test_fit_frame_to_canvas_letterbox_leaves_black_bars():
    frame = np.full((90, 160, 3), 255, dtype=np.uint8)  # 16:9 white frame
    canvas = fit_frame_to_canvas(frame, canvas_size=(90, 160), crop="letterbox")
    assert canvas.shape == (160, 90, 3)
    # bars top and bottom, picture centered: 90*(90/160)≈50 rows of picture
    assert canvas[0].max() == 0
    assert canvas[-1].max() == 0
    assert canvas[80].min() == 255


def test_fit_frame_to_canvas_cover_fills_everything():
    frame = np.full((90, 160, 3), 200, dtype=np.uint8)
    canvas = fit_frame_to_canvas(frame, canvas_size=(90, 160), crop="center")
    assert canvas.min() == 200


# --- zone stats ---------------------------------------------------------------


def test_zone_stats_letterbox_bars_read_as_calm_dark():
    height, width = 240, 135
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    # noisy bright picture strip in the middle only
    rng = np.random.default_rng(7)
    canvas[90:150] = rng.integers(100, 255, size=(60, width, 3), dtype=np.uint8)
    zones = zone_stats_for_canvas(canvas)
    ranges = band_pixel_ranges(height)
    assert len(zones) == len(ranges)
    # upper band (rows ~34-91) is mostly bar: near-zero luma and detail
    assert zones[0].luma < 0.1
    assert zones[0].detail < 0.1
    # middle band (rows ~96-144) is the noisy picture: bright and busy
    assert zones[1].luma > 0.4
    assert zones[1].detail > 0.3


def test_zone_stats_uniform_bright_area_has_no_detail():
    canvas = np.full((240, 135, 3), 230, dtype=np.uint8)
    zones = zone_stats_for_canvas(canvas)
    for zone in zones:
        assert zone.luma > 0.8
        assert zone.detail == pytest.approx(0.0, abs=1e-6)


# --- hue ----------------------------------------------------------------------


def test_dominant_hue_solid_red():
    canvas = np.zeros((64, 64, 3), dtype=np.uint8)
    canvas[..., 0] = 220
    hue, sat = dominant_hue(canvas)
    assert hue == pytest.approx(0.0, abs=2.0) or hue == pytest.approx(360.0, abs=2.0)
    assert sat > 0.9


def test_dominant_hue_blue_ignores_black_bars():
    canvas = np.zeros((64, 64, 3), dtype=np.uint8)
    canvas[16:48, :, 2] = 200  # blue picture strip between black bars
    hue, sat = dominant_hue(canvas)
    assert hue == pytest.approx(240.0, abs=2.0)
    assert sat > 0.9


def test_dominant_hue_gray_footage_reads_desaturated():
    canvas = np.full((64, 64, 3), 128, dtype=np.uint8)
    _, sat = dominant_hue(canvas)
    assert sat < 0.05
