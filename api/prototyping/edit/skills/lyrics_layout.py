"""Pure layout/color decisions for kinetic lyrics.

Turns per-shot footage stats (``ShotStats`` from render/footage_stats.py, or
None when sampling was unavailable) into per-line placement and color choices:
which vertical band the line sits in (calm, low-detail areas win; letterbox
bars are ideal), light-vs-dark fill, and a footage-hue-derived accent with a
contrast floor. No numpy/moviepy — mirrors the rhythm.py pure-decision
pattern so every choice is unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .base import ShotStats

# Instagram UI keep-out zones (username top, caption/actions bottom, side rails).
SAFE_TOP_FRAC = 0.14
SAFE_BOTTOM_FRAC = 0.22
SAFE_SIDE_FRAC = 0.10

# Candidate text bands (fractions of output height), top -> bottom, inside the
# safe area. Index 2 (lower third) is the lyric-placement convention.
BAND_FRACS: tuple[tuple[float, float], ...] = ((0.14, 0.38), (0.40, 0.60), (0.62, 0.78))
NUM_BANDS = len(BAND_FRACS)
DEFAULT_BAND = 2
LOWER_BAND_BONUS = 0.05     # convention nudge toward the lower third
HYSTERESIS_MARGIN = 0.08    # a new band must beat the previous by this much

# Outlined video text needs less contrast than flat body text (WCAG 4.5 is for
# the latter); 3.0 keeps accents vivid instead of forcing near-white/black.
MIN_CONTRAST = 3.0
MIN_SATURATION = 0.12       # below this the footage is effectively monochrome
INK_FILL = "#141414"
NEUTRAL_ACCENT_ON_DARK = "#FFDF6B"   # warm gold — the default lyric accent
NEUTRAL_ACCENT_ON_LIGHT = "#7A2412"  # burnt sienna for bright footage
MIN_FONT_SIZE_PX = 28   # readability target; longer lines WRAP rather than shrink below it
MAX_TEXT_ROWS = 3
# Width-estimate glyph weights (× width_factor): caps/digits run wide, spaces
# and thin punctuation narrow. Rough, so fits carry the wrap fallback below.
CAPS_GLYPH_WEIGHT = 1.25
NARROW_GLYPH_WEIGHT = 0.5
_NARROW_GLYPHS = set(" .,'!:;|il")


@dataclass(frozen=True)
class LineLayout:
    """Placement + palette for one lyric line (consumed by lyrics_kinetic)."""

    line_index: int
    style: str        # "sweep" | "pop" | "build"
    band: int         # 0 upper / 1 middle / 2 lower
    alignment: int    # ASS numpad: 8 top-center / 5 middle-center / 2 bottom-center
    margin_v: int     # px; 0 for middle alignment
    font_size: int
    fill: str         # #RRGGBB fill (post-sweep color)
    accent: str       # #RRGGBB accent (pre-sweep color / emphasis words)
    outline: str      # #RRGGBB outline
    row_splits: tuple[int, ...] = ()  # cumulative word-end index per visual row


def band_pixel_ranges(height: int) -> list[tuple[int, int]]:
    return [(round(height * top), round(height * bottom)) for top, bottom in BAND_FRACS]


# --- color math (sRGB / WCAG-style) --------------------------------------


def _srgb_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def hex_relative_luminance(hex_rgb: str) -> float:
    rgb = hex_rgb.lstrip("#")
    r, g, b = (int(rgb[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * _srgb_linear(r) + 0.7152 * _srgb_linear(g) + 0.0722 * _srgb_linear(b)


def zone_relative_luminance(zone_luma: float) -> float:
    """footage_stats zone luma is a GAMMA-encoded Rec.709 mean of sRGB bytes;
    linearize it (as a gray value) before comparing against WCAG-linear text
    luminance — comparing across spaces made mid-tone contrast unsatisfiable."""
    return _srgb_linear(min(1.0, max(0.0, zone_luma)))


def contrast_ratio(luminance_a: float, luminance_b: float) -> float:
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def hsl_to_hex(hue_deg: float, saturation: float, lightness: float) -> str:
    c = (1 - abs(2 * lightness - 1)) * saturation
    hp = (hue_deg % 360.0) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    r, g, b = (
        (c, x, 0.0), (x, c, 0.0), (0.0, c, x),
        (0.0, x, c), (x, 0.0, c), (c, 0.0, x),
    )[min(5, int(hp))]
    m = lightness - c / 2
    return "#" + "".join(f"{round((v + m) * 255):02X}" for v in (r, g, b))


def _ensure_contrast(hex_rgb: str, hue_deg: float, saturation: float,
                     zone_linear: float, lighten: bool) -> str:
    """Walk HSL lightness until the accent clears the contrast floor
    (``zone_linear`` must already be linearized)."""
    if contrast_ratio(hex_relative_luminance(hex_rgb), zone_linear) >= MIN_CONTRAST:
        return hex_rgb
    lightness = 0.62 if lighten else 0.35
    step = 0.04 if lighten else -0.04
    for _ in range(24):
        lightness = min(0.98, max(0.02, lightness + step))
        candidate = hsl_to_hex(hue_deg, saturation, lightness)
        if contrast_ratio(hex_relative_luminance(candidate), zone_linear) >= MIN_CONTRAST:
            return candidate
    return "#FFFFFF" if lighten else "#000000"


def adaptive_colors(
    zone_luma: float,
    dominant_hue_deg: float,
    saturation: float,
    accent_override: str | None = None,
    dark_zone: bool | None = None,
) -> tuple[str, str, str]:
    """(fill, accent, outline) for a text band with the given footage character.

    ``zone_luma`` is the gamma-encoded band luma from footage_stats; the
    dark/bright split happens in that (perceptual) space, contrast checks in
    linear space. ``dark_zone`` overrides the split (palette hysteresis)."""
    if dark_zone is None:
        dark_zone = zone_luma < 0.55
    zone_linear = zone_relative_luminance(zone_luma)
    fill = "#FFFFFF" if dark_zone else INK_FILL
    outline = "#000000" if dark_zone else "#FFFFFF"

    if accent_override and contrast_ratio(
        hex_relative_luminance(accent_override), zone_linear
    ) >= MIN_CONTRAST:
        return fill, accent_override, outline

    if saturation < MIN_SATURATION:
        neutral = NEUTRAL_ACCENT_ON_DARK if dark_zone else NEUTRAL_ACCENT_ON_LIGHT
        accent = _ensure_contrast(neutral, 45.0, 0.7, zone_linear, lighten=dark_zone)
        return fill, accent, outline

    lifted_sat = min(0.85, max(0.60, saturation))
    seed = hsl_to_hex(dominant_hue_deg, lifted_sat, 0.62 if dark_zone else 0.35)
    accent = _ensure_contrast(seed, dominant_hue_deg, lifted_sat, zone_linear, lighten=dark_zone)
    return fill, accent, outline


# --- band picking ---------------------------------------------------------


def _aggregate_stats(
    start_sec: float, end_sec: float, shot_stats: Sequence[ShotStats]
) -> tuple[list[tuple[float, float]], float, float] | None:
    """Duration-weighted (luma, detail) per band + circular-mean hue + mean
    saturation over the shots overlapping [start_sec, end_sec)."""
    total = 0.0
    zone_acc = [[0.0, 0.0] for _ in range(NUM_BANDS)]
    hue_x = hue_y = sat_acc = 0.0
    for shot in shot_stats:
        overlap = min(end_sec, shot.end_sec) - max(start_sec, shot.start_sec)
        if overlap <= 0 or len(shot.zones) != NUM_BANDS:
            continue
        total += overlap
        for i, zone in enumerate(shot.zones):
            zone_acc[i][0] += zone.luma * overlap
            zone_acc[i][1] += zone.detail * overlap
        # Hue is weighted by saturation too (matching dominant_hue's per-pixel
        # weighting): a near-grayscale shot reports hue 0° (red) as a filler
        # value and must not drag the accent toward red at full weight.
        rad = math.radians(shot.dominant_hue_deg)
        hue_weight = overlap * shot.saturation
        hue_x += math.cos(rad) * hue_weight
        hue_y += math.sin(rad) * hue_weight
        sat_acc += shot.saturation * overlap
    if total <= 0:
        return None
    zones = [(l / total, d / total) for l, d in zone_acc]
    hue = math.degrees(math.atan2(hue_y, hue_x)) % 360.0 if (hue_x or hue_y) else 0.0
    return zones, hue, sat_acc / total


def pick_band(
    start_sec: float,
    end_sec: float,
    shot_stats: Sequence[ShotStats] | None,
    prev_band: int | None,
) -> int:
    """Calmest candidate band for the window, with hysteresis toward
    ``prev_band`` so consecutive lines don't hop across the frame."""
    if not shot_stats:
        return DEFAULT_BAND
    aggregated = _aggregate_stats(start_sec, end_sec, shot_stats)
    if aggregated is None:
        return DEFAULT_BAND
    zones, _, _ = aggregated
    scores = [
        detail - (LOWER_BAND_BONUS if band == DEFAULT_BAND else 0.0)
        for band, (_, detail) in enumerate(zones)
    ]
    best = min(range(NUM_BANDS), key=lambda band: scores[band])
    if prev_band is not None and scores[prev_band] - scores[best] < HYSTERESIS_MARGIN:
        return prev_band
    return best


# --- sizing / style plan ---------------------------------------------------


def _glyph_weights(text: str, all_caps: bool) -> float:
    total = 0.0
    for ch in text:
        if ch in _NARROW_GLYPHS:
            total += NARROW_GLYPH_WEIGHT
        elif ch.isupper() or ch.isdigit() or (all_caps and ch.isalpha()):
            total += CAPS_GLYPH_WEIGHT
        else:
            total += 1.0
    return max(total, NARROW_GLYPH_WEIGHT)


def estimate_line_width(
    text: str, font_size: float, width_factor: float, all_caps: bool = False
) -> float:
    """Rough rendered width in px: per-glyph weights × the font's width factor."""
    return font_size * width_factor * _glyph_weights(text, all_caps)


def _fitted_size(text: str, base_size_px: int, safe_width_px: float,
                 width_factor: float, all_caps: bool) -> int:
    weights = _glyph_weights(text, all_caps)
    return max(8, min(base_size_px, int(safe_width_px / (weights * width_factor))))


def fit_font_size(
    text: str, *, base_size_px: int, safe_width_px: float, width_factor: float,
    all_caps: bool = False,
) -> int:
    """Shrink from base until the estimated line width fits the safe width
    (single-row fit with a readability floor — used for pop's single words;
    whole lines go through plan_row_splits, which wraps instead of flooring)."""
    fitted = _fitted_size(text, base_size_px, safe_width_px, width_factor, all_caps)
    return max(MIN_FONT_SIZE_PX, fitted)


def _balanced_splits(word_texts: Sequence[str], rows: int, all_caps: bool) -> tuple[int, ...]:
    """Greedy cumulative-weight split of words into ``rows`` visual rows."""
    weights = [_glyph_weights(w, all_caps) + NARROW_GLYPH_WEIGHT for w in word_texts]
    total = sum(weights)
    splits: list[int] = []
    acc = 0.0
    target = total / rows
    for i, w in enumerate(weights):
        acc += w
        remaining_rows = rows - len(splits) - 1
        remaining_words = len(word_texts) - (i + 1)
        if len(splits) < rows - 1 and acc >= target and remaining_words >= remaining_rows:
            splits.append(i + 1)
            acc = 0.0
    splits.append(len(word_texts))
    return tuple(splits)


def _rows_text(word_texts: Sequence[str], splits: tuple[int, ...]) -> list[str]:
    rows, start = [], 0
    for end in splits:
        rows.append(" ".join(word_texts[start:end]))
        start = end
    return rows


def plan_row_splits(
    word_texts: Sequence[str],
    *,
    base_size_px: int,
    safe_width_px: float,
    width_factor: float,
    all_caps: bool = False,
) -> tuple[int, tuple[int, ...]]:
    """(font_size, cumulative word-end index per row) for one lyric line.

    Size-constancy first: lines WRAP (up to MAX_TEXT_ROWS) to fit at the base
    size, so consecutive lines render at ONE size instead of jittering — the
    professional lyric look. Only a line that can't fit at the base size even
    fully wrapped shrinks, and then the returned size still CONTAINS every
    row (the ASS document uses WrapStyle 2 — an unfitted line would hard-clip
    at the frame edges, and tiny beats clipped)."""
    best: tuple[int, tuple[int, ...]] | None = None
    for rows in range(1, min(MAX_TEXT_ROWS, len(word_texts)) + 1):
        splits = _balanced_splits(word_texts, rows, all_caps)
        size = min(
            _fitted_size(row, base_size_px, safe_width_px, width_factor, all_caps)
            for row in _rows_text(word_texts, splits)
        )
        best = (size, splits)  # more rows never fit worse — keep the last
        if size >= base_size_px:
            return best
    assert best is not None
    return best


def style_for_time(t: float, base_style: str, section_styles: Sequence[Mapping]) -> str:
    for section in section_styles:
        if float(section["start_sec"]) <= t < float(section["end_sec"]):
            return str(section["style"])
    return base_style


_BAND_ALIGNMENT = {0: 8, 1: 5, 2: 2}  # ASS numpad codes per band


def _band_margin_v(band: int, height: int) -> int:
    if band == 0:
        return round(height * SAFE_TOP_FRAC)
    if band == 2:
        return round(height * SAFE_BOTTOM_FRAC)
    return 0  # middle alignment ignores MarginV


def _line_text(line: Mapping) -> str:
    text = str(line.get("text") or "").strip()
    if text:
        return text
    return " ".join(str(w["text"]) for w in line.get("words", []))


# Dark/bright hysteresis band around the 0.55 split: the palette only flips
# polarity when the footage clearly commits to the other side, so lyric colors
# don't flicker line-to-line across alternating shots.
DARK_ENTER_LUMA = 0.48
DARK_EXIT_LUMA = 0.62


def _dark_with_hysteresis(zone_luma: float, prev_dark: bool | None) -> bool:
    if prev_dark is None:
        return zone_luma < 0.55
    if prev_dark:
        return not (zone_luma > DARK_EXIT_LUMA)
    return zone_luma < DARK_ENTER_LUMA


def _line_words(line: Mapping) -> list[str]:
    words = [str(w["text"]) for w in line.get("words", []) if str(w.get("text", "")).strip()]
    if words:
        return words
    return _line_text(line).split() or [""]


def plan_line_layouts(
    lines: Sequence[Mapping],
    *,
    output_size: tuple[int, int],
    base_style: str,
    section_styles: Sequence[Mapping] = (),
    shot_stats: Sequence[ShotStats] | None = None,
    base_size_px: int,
    width_factor: float,
    accent_override: str | None = None,
    all_caps: bool = False,
) -> list[LineLayout]:
    """One LineLayout per lyric line: style variant, band (with hysteresis),
    adaptive palette (with dark/bright hysteresis so colors don't flicker
    line-to-line), row wrapping, fitted font size. shot_stats=None degrades to
    the safe defaults (lower third, white on black outline, neutral accent)."""
    width, height = output_size
    safe_width = width * (1 - 2 * SAFE_SIDE_FRAC)
    layouts: list[LineLayout] = []
    prev_band: int | None = None
    prev_dark: bool | None = None
    prev_palette: tuple[str, str, str] | None = None
    for i, line in enumerate(lines):
        start = float(line["start_sec"])
        end = float(line["end_sec"])
        style = style_for_time(start, base_style, section_styles)
        band = pick_band(start, end, shot_stats, prev_band)
        prev_band = band

        aggregated = _aggregate_stats(start, end, shot_stats) if shot_stats else None
        if aggregated is None:
            fill, outline = "#FFFFFF", "#000000"
            accent = accent_override or NEUTRAL_ACCENT_ON_DARK
        else:
            zones, hue, sat = aggregated
            dark = _dark_with_hysteresis(zones[band][0], prev_dark)
            if prev_palette is not None and dark == prev_dark:
                # Palette continuity: same polarity as the previous line keeps
                # the previous colors — constancy reads as intentional design.
                fill, accent, outline = prev_palette
            else:
                fill, accent, outline = adaptive_colors(
                    zones[band][0], hue, sat, accent_override, dark_zone=dark
                )
            prev_dark = dark
            prev_palette = (fill, accent, outline)

        font_size, row_splits = plan_row_splits(
            _line_words(line),
            base_size_px=base_size_px,
            safe_width_px=safe_width,
            width_factor=width_factor,
            all_caps=all_caps,
        )
        layouts.append(
            LineLayout(
                line_index=i,
                style=style,
                band=band,
                alignment=_BAND_ALIGNMENT[band],
                margin_v=_band_margin_v(band, height),
                font_size=font_size,
                fill=fill,
                accent=accent,
                outline=outline,
                row_splits=row_splits,
            )
        )
    return layouts
