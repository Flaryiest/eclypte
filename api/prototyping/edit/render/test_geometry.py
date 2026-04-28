from moviepy import ColorClip

from api.prototyping.edit.render.geometry import cover_crop_offsets
from api.prototyping.edit.render.renderer import _fit


def test_cover_crop_offsets_focus_left_center_and_right():
    source_size = (1920, 1080)
    target_size = (1080, 1920)

    assert cover_crop_offsets(source_size, target_size, focus_x=0.0) == (0, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=0.5) == (1167, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=1.0) == (2334, 0)


def test_cover_crop_offsets_use_ceil_scaled_size_for_wide_cinema_source():
    source_size = (1920, 804)
    target_size = (1080, 1920)

    assert cover_crop_offsets(source_size, target_size, focus_x=0.0) == (0, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=0.5) == (1753, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=1.0) == (3506, 0)


def test_fill_crop_keeps_requested_even_reels_size_for_wide_source():
    clip = ColorClip(size=(1920, 804), color=(0, 0, 0)).with_duration(1)
    fitted = _fit(clip, (1080, 1920), "fill", 0.5)
    try:
        assert fitted.size == (1080, 1920)
    finally:
        fitted.close()
        clip.close()
