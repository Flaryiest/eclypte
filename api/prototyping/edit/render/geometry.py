from __future__ import annotations


def cover_crop_offsets(
    source_size: tuple[int, int],
    target_size: tuple[int, int],
    *,
    focus_x: float,
) -> tuple[int, int]:
    source_w, source_h = source_size
    target_w, target_h = target_size
    scale = max(target_w / source_w, target_h / source_h)
    scaled_w = source_w * scale
    scaled_h = source_h * scale
    max_x = max(0.0, scaled_w - target_w)
    max_y = max(0.0, scaled_h - target_h)
    clamped_focus_x = min(1.0, max(0.0, focus_x))
    return round(max_x * clamped_focus_x), round(max_y * 0.5)
