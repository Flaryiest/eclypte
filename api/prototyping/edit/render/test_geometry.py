from api.prototyping.edit.render.geometry import cover_crop_offsets


def test_cover_crop_offsets_focus_left_center_and_right():
    source_size = (1920, 1080)
    target_size = (1080, 1920)

    assert cover_crop_offsets(source_size, target_size, focus_x=0.0) == (0, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=0.5) == (1167, 0)
    assert cover_crop_offsets(source_size, target_size, focus_x=1.0) == (2333, 0)
