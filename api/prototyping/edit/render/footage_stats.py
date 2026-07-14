"""Footage sampling for kinetic-lyrics layout decisions.

``sample_shot_stats`` (the only impure function — lazy moviepy import) decodes
a few decimated frames per shot and reduces them to per-band luma/detail plus
a dominant hue, matching the candidate text bands in skills/lyrics_layout.py.
Everything else is pure numpy so the geometry/color math is unit-testable.

Failure anywhere must degrade to ``None`` at the call site (renderer wraps the
call) — sampling is a layout hint, never a reason to fail a render.
"""
from __future__ import annotations

import math
from typing import Sequence

from ..skills.base import ShotStats, ZoneStats
from ..skills.lyrics_layout import band_pixel_ranges
from ..synthesis.timeline_schema import Shot, Timeline
from .geometry import cover_crop_offsets, cover_resize_size

# Fractions of the shot's usable source window to sample.
SAMPLE_FRACS = (0.25, 0.6, 0.85)
# speed_ramp's second half breaks the 1:1 timeline->source mapping; sampling
# stays inside the linear first half (mirrors rhythm.py's registration skip).
RAMP_SAFE_FRAC = 0.5
# Decimation factor for the stats canvas (full-res pixels are wasted on means).
CANVAS_DECIMATE = 8
# Mean absolute gradient (0-255 scale) that saturates detail to 1.0.
DETAIL_NORM = 24.0
# Pixels darker than this (max channel, 0-1) are treated as bars/black, not hue.
HUE_BLACK_FLOOR = 0.05


def sample_source_times(shot: Shot) -> list[float]:
    """Representative source timestamps for one shot (pure policy)."""
    start = shot.source.start_sec
    span = shot.source.end_sec - start
    effect_types = {e.type for e in shot.effects}
    if "freeze" in effect_types:
        return [start]
    if "speed_ramp" in effect_types:
        span *= RAMP_SAFE_FRAC
    return [start + frac * span for frac in SAMPLE_FRACS]


def fit_frame_to_canvas(frame, canvas_size: tuple[int, int], crop: str, focus_x: float = 0.5):
    """Nearest-neighbor place a source frame onto a black canvas the way the
    renderer would (letterbox bars stay black; other crops cover-fill).

    ``canvas_size`` is (width, height) like output_size; frame is HxWx3."""
    import numpy as np

    cw, ch = canvas_size
    fh, fw = frame.shape[:2]
    canvas = np.zeros((ch, cw, 3), dtype=frame.dtype)

    if crop == "letterbox":
        scale = min(cw / fw, ch / fh)
        fit_w = max(1, round(fw * scale))
        fit_h = max(1, round(fh * scale))
        x_off = (cw - fit_w) // 2
        y_off = (ch - fit_h) // 2
        rows = np.clip((np.arange(fit_h) / scale).astype(int), 0, fh - 1)
        cols = np.clip((np.arange(fit_w) / scale).astype(int), 0, fw - 1)
        canvas[y_off : y_off + fit_h, x_off : x_off + fit_w] = frame[np.ix_(rows, cols)]
        return canvas

    resized_w, resized_h = cover_resize_size((fw, fh), (cw, ch))
    x_crop, y_crop = cover_crop_offsets(
        (fw, fh), (cw, ch), focus_x=focus_x, scaled_size=(resized_w, resized_h)
    )
    scale = resized_w / fw
    rows = np.clip(((np.arange(ch) + y_crop) / scale).astype(int), 0, fh - 1)
    cols = np.clip(((np.arange(cw) + x_crop) / scale).astype(int), 0, fw - 1)
    canvas[:, :] = frame[np.ix_(rows, cols)]
    return canvas


def zone_stats_for_canvas(canvas) -> tuple[ZoneStats, ...]:
    """Per-band luma mean + normalized gradient detail on an output-space
    canvas (letterbox bars therefore read as luma 0 / detail 0)."""
    import numpy as np

    height = canvas.shape[0]
    rgb = canvas.astype(np.float32)
    luma = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0
    zones = []
    for y0, y1 in band_pixel_ranges(height):
        band = luma[y0:y1]
        if band.size == 0:
            zones.append(ZoneStats(luma=0.0, detail=0.0))
            continue
        grad_y = np.abs(np.diff(band, axis=0)) if band.shape[0] > 1 else np.zeros((1, 1))
        grad_x = np.abs(np.diff(band, axis=1)) if band.shape[1] > 1 else np.zeros((1, 1))
        grad = (float(grad_y.mean()) + float(grad_x.mean())) / 2.0 * 255.0
        zones.append(
            ZoneStats(
                luma=float(band.mean()),
                detail=min(1.0, grad / DETAIL_NORM),
            )
        )
    return tuple(zones)


def dominant_hue(canvas) -> tuple[float, float]:
    """(hue_deg, saturation) of the canvas picture, ignoring black bars.

    Circular mean of per-pixel hue weighted by saturation, so gray pixels
    don't drag the hue; saturation is averaged over non-black pixels only."""
    import numpy as np

    rgb = canvas.reshape(-1, 3).astype(np.float32) / 255.0
    mx = rgb.max(axis=1)
    mn = rgb.min(axis=1)
    delta = mx - mn
    picture = mx > HUE_BLACK_FLOOR
    if not picture.any():
        return 0.0, 0.0

    sat = np.zeros_like(mx)
    np.divide(delta, mx, out=sat, where=mx > 0)

    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    hue = np.zeros_like(mx)
    safe_delta = np.where(delta > 0, delta, 1.0)
    r_max = (mx == r) & (delta > 0)
    g_max = (mx == g) & (delta > 0) & ~r_max
    b_max = (mx == b) & (delta > 0) & ~r_max & ~g_max
    hue[r_max] = (60.0 * ((g - b) / safe_delta))[r_max] % 360.0
    hue[g_max] = (60.0 * ((b - r) / safe_delta) + 120.0)[g_max]
    hue[b_max] = (60.0 * ((r - g) / safe_delta) + 240.0)[b_max]

    weights = (sat * picture).astype(np.float64)
    if weights.sum() <= 0:
        return 0.0, float(sat[picture].mean())
    rad = np.radians(hue)
    mean_deg = math.degrees(
        math.atan2(float((np.sin(rad) * weights).sum()), float((np.cos(rad) * weights).sum()))
    ) % 360.0
    return mean_deg, float(sat[picture].mean())


def sample_shot_stats(timeline: Timeline, output_size: tuple[int, int]) -> list[ShotStats]:
    """Decode a few decimated frames per shot and reduce to ShotStats.

    The only impure function here (moviepy decode); call sites must treat any
    exception as "no stats" rather than failing the render."""
    import numpy as np
    from moviepy import VideoFileClip

    out_w, out_h = output_size
    canvas_size = (max(16, out_w // CANVAS_DECIMATE), max(16, out_h // CANVAS_DECIMATE))
    crop = timeline.output.crop
    focus_x = timeline.output.crop_focus_x

    stats: list[ShotStats] = []
    clip = VideoFileClip(timeline.source.video)
    try:
        max_t = max(0.0, (clip.duration or 0.0) - 0.05)
        for shot in timeline.shots:
            zone_acc: list[list[float]] = [[0.0, 0.0] for _ in band_pixel_ranges(canvas_size[1])]
            hue_x = hue_y = sat_acc = 0.0
            samples = 0
            for t in sample_source_times(shot):
                frame = clip.get_frame(min(max(0.0, t), max_t))
                small = np.asarray(frame)[::CANVAS_DECIMATE, ::CANVAS_DECIMATE]
                canvas = fit_frame_to_canvas(small, canvas_size, crop, focus_x)
                for i, zone in enumerate(zone_stats_for_canvas(canvas)):
                    zone_acc[i][0] += zone.luma
                    zone_acc[i][1] += zone.detail
                hue, sat = dominant_hue(canvas)
                rad = math.radians(hue)
                hue_x += math.cos(rad) * sat
                hue_y += math.sin(rad) * sat
                sat_acc += sat
                samples += 1
            if not samples:
                continue
            stats.append(
                ShotStats(
                    start_sec=shot.timeline_start_sec,
                    end_sec=shot.timeline_end_sec,
                    zones=tuple(
                        ZoneStats(luma=l / samples, detail=d / samples) for l, d in zone_acc
                    ),
                    dominant_hue_deg=math.degrees(math.atan2(hue_y, hue_x)) % 360.0
                    if (hue_x or hue_y)
                    else 0.0,
                    saturation=sat_acc / samples,
                )
            )
    finally:
        clip.close()
    return stats


def wants_shot_stats(overlays: Sequence) -> bool:
    """True when any overlay's skill asked for the sampling pass."""
    from .. import skills  # registry (moviepy-free metadata)

    return any(skills.get(ov.skill_id).wants_shot_stats for ov in overlays)
