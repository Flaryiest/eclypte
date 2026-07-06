import numpy as np
import pytest

moviepy = pytest.importorskip("moviepy")
from moviepy import ColorClip  # noqa: E402

from api.prototyping.edit.render.effects import apply_effects  # noqa: E402
from api.prototyping.edit.render.transitions import apply_transition  # noqa: E402
from api.prototyping.edit.synthesis.timeline_schema import (  # noqa: E402
    Effect,
    Shot,
    ShotSource,
    Transition,
)

SIZE = (64, 36)
DURATION = 1.0


def _clip(color):
    return ColorClip(size=SIZE, color=color).with_duration(DURATION)


def _shot(*, effects=None, transition="cut"):
    return Shot(
        index=0,
        timeline_start_sec=0.0,
        timeline_end_sec=DURATION,
        source=ShotSource(start_sec=10.0, end_sec=10.0 + DURATION),
        effects=effects or [],
        transition_in=Transition(type=transition),
    )


def test_plain_cut_returns_clip_unchanged():
    clip = _clip((50, 50, 50))
    assert apply_transition(None, clip, _shot()) is clip


def test_flash_blooms_in_middle_then_returns():
    clip = apply_transition(None, _clip((100, 100, 100)), _shot(transition="flash"))

    assert clip.duration == pytest.approx(DURATION)
    assert tuple(clip.size) == SIZE
    start = clip.get_frame(0.0)
    mid = clip.get_frame(0.06)  # ~middle of the 0.12s bloom
    after = clip.get_frame(0.5)
    assert start.mean() == pytest.approx(100.0, abs=2.0)  # eases in, no instant onset
    assert mid.mean() > start.mean() + 5  # gentle brightness lift peaks mid-bloom
    assert mid.mean() < 200  # never washes toward white
    assert after.mean() == pytest.approx(100.0, abs=1.0)  # returns to source after the bloom


def test_crossfade_dissolves_from_previous_frame():
    prev = _clip((255, 0, 0))
    cur = apply_transition(prev, _clip((0, 0, 255)), _shot(transition="crossfade"))

    assert cur.duration == pytest.approx(DURATION)
    start = cur.get_frame(0.0)
    late = cur.get_frame(0.6)
    assert start[0, 0, 0] > 200  # starts nearly all previous-shot red
    assert start[0, 0, 2] < 60
    assert late[0, 0, 2] > 200  # settles on the incoming shot's blue
    assert late[0, 0, 0] < 10


def test_whip_falls_back_to_cut():
    clip = _clip((50, 50, 50))
    assert apply_transition(None, clip, _shot(transition="whip")) is clip


def test_freeze_holds_first_frame():
    moving = _clip((10, 10, 10)).transform(
        lambda gf, t: (gf(t) + int(t * 200)).clip(0, 255).astype("uint8")
    )
    frozen = apply_effects(moving, _shot(effects=[Effect(type="freeze")]))

    assert frozen.duration == pytest.approx(DURATION)
    np.testing.assert_array_equal(frozen.get_frame(0.9), frozen.get_frame(0.0))


def test_punch_in_preserves_size_and_zooms():
    base = np.zeros((SIZE[1], SIZE[0], 3), dtype="uint8")
    base[0:2, :, :] = 255  # bright strip on the top edge
    clip = _clip((0, 0, 0)).transform(lambda gf, t: base)
    zoomed = apply_effects(clip, _shot(effects=[Effect(type="punch_in")]))

    first = zoomed.get_frame(0.0)
    last = zoomed.get_frame(DURATION - 1e-3)
    assert first.shape == last.shape == (SIZE[1], SIZE[0], 3)
    # zooming in pushes the edge strip out of frame, dimming the top rows
    assert last[0:2].mean() < first[0:2].mean()


def test_unknown_effect_is_skipped():
    clip = _clip((50, 50, 50))
    out = apply_effects(clip, _shot(effects=[Effect(type="speed_ramp")]))
    assert out is clip


def test_speed_ramp_time_warp_accelerates_second_half():
    from api.prototyping.edit.render.effects import speed_ramp_time_warp

    warp = speed_ramp_time_warp(2.0)
    assert warp(0.0) == pytest.approx(0.0)
    assert warp(0.5) == pytest.approx(0.5)     # first half plays 1:1
    assert warp(1.0) == pytest.approx(1.0)
    assert warp(1.5) == pytest.approx(1.75)    # second half runs at 1.5x
    assert warp(2.0) == pytest.approx(2.5)     # consumes 1.25x duration of source
