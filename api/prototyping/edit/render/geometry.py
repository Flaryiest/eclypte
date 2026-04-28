from __future__ import annotations

from math import ceil


def cover_resize_size(
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int]:
    source_w, source_h = source_size
    target_w, target_h = target_size
    scale = max(target_w / source_w, target_h / source_h)
    return (
        max(target_w, ceil(source_w * scale)),
        max(target_h, ceil(source_h * scale)),
    )


def cover_crop_offsets(
    source_size: tuple[int, int],
    target_size: tuple[int, int],
    *,
    focus_x: float,
    scaled_size: tuple[int, int] | None = None,
) -> tuple[int, int]:
    target_w, target_h = target_size
    scaled_w, scaled_h = scaled_size or cover_resize_size(source_size, target_size)
    max_x = max(0.0, scaled_w - target_w)
    max_y = max(0.0, scaled_h - target_h)
    clamped_focus_x = min(1.0, max(0.0, focus_x))
    return round(max_x * clamped_focus_x), round(max_y * 0.5)
