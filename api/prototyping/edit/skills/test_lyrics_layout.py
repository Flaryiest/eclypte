import pytest

from api.prototyping.edit.skills import lyrics_layout
from api.prototyping.edit.skills.base import ShotStats, ZoneStats
from api.prototyping.edit.skills.lyrics_layout import (
    LineLayout,
    adaptive_colors,
    band_pixel_ranges,
    contrast_ratio,
    fit_font_size,
    hex_relative_luminance,
    pick_band,
    plan_line_layouts,
    style_for_time,
)


def _stats(zones, start=0.0, end=10.0, hue=20.0, sat=0.6):
    return ShotStats(
        start_sec=start,
        end_sec=end,
        zones=tuple(ZoneStats(luma=l, detail=d) for l, d in zones),
        dominant_hue_deg=hue,
        saturation=sat,
    )


# --- geometry -----------------------------------------------------------


def test_band_pixel_ranges_stay_inside_safe_area():
    ranges = band_pixel_ranges(1920)
    assert len(ranges) == 3
    top = round(1920 * lyrics_layout.SAFE_TOP_FRAC)
    bottom = round(1920 * (1 - lyrics_layout.SAFE_BOTTOM_FRAC))
    for y0, y1 in ranges:
        assert top <= y0 < y1 <= bottom
    # top→bottom, non-overlapping
    assert ranges[0][1] <= ranges[1][0] <= ranges[1][1] <= ranges[2][0]


# --- band picking -------------------------------------------------------


def test_pick_band_prefers_calm_low_detail_zone():
    stats = [_stats([(0.5, 0.9), (0.5, 0.8), (0.5, 0.1)])]
    assert pick_band(0.0, 5.0, stats, prev_band=None) == 2


def test_pick_band_letterbox_bars_win():
    # reels_cinematic: bars top+bottom are luma 0 / detail 0; picture in the
    # middle is busy. Lower band should win via the lyric-convention bonus.
    stats = [_stats([(0.0, 0.0), (0.55, 0.7), (0.0, 0.0)])]
    assert pick_band(0.0, 5.0, stats, prev_band=None) == 2


def test_pick_band_hysteresis_keeps_previous_on_near_ties():
    stats = [_stats([(0.5, 0.25), (0.5, 0.9), (0.5, 0.33)])]
    # band 0 scores marginally better than band 2 (0.25 vs 0.33-bonus=0.28),
    # but not by the hysteresis margin — keep the previous band so text
    # doesn't hop around.
    assert pick_band(0.0, 5.0, stats, prev_band=2) == 2


def test_pick_band_switches_when_clearly_better():
    stats = [_stats([(0.5, 0.05), (0.5, 0.9), (0.5, 0.95)])]
    assert pick_band(0.0, 5.0, stats, prev_band=2) == 0


def test_pick_band_weights_overlapping_shots_by_duration():
    calm_lower = _stats([(0.5, 0.9), (0.5, 0.9), (0.5, 0.0)], start=0.0, end=9.0)
    calm_upper = _stats([(0.5, 0.0), (0.5, 0.9), (0.5, 0.9)], start=9.0, end=10.0)
    # Line spans 0-10s: 9s of calm-lower footage dominates 1s of calm-upper.
    assert pick_band(0.0, 10.0, [calm_lower, calm_upper], prev_band=None) == 2


def test_pick_band_without_stats_defaults_to_lower():
    assert pick_band(0.0, 5.0, None, prev_band=None) == 2
    assert pick_band(0.0, 5.0, [], prev_band=None) == 2


# --- color --------------------------------------------------------------


def _zone_linear(zone_luma):
    # footage_stats zone luma is gamma-encoded; contrast must compare in the
    # same (linear) space as hex_relative_luminance.
    return lyrics_layout.zone_relative_luminance(zone_luma)


def test_adaptive_colors_dark_footage_gets_white_fill():
    fill, accent, outline = adaptive_colors(zone_luma=0.15, dominant_hue_deg=210.0, saturation=0.7)
    assert fill == "#FFFFFF"
    assert outline == "#000000"
    assert contrast_ratio(hex_relative_luminance(accent), _zone_linear(0.15)) >= lyrics_layout.MIN_CONTRAST


def test_adaptive_colors_bright_footage_gets_ink_fill():
    fill, accent, outline = adaptive_colors(zone_luma=0.85, dominant_hue_deg=30.0, saturation=0.7)
    assert fill == lyrics_layout.INK_FILL
    assert outline == "#FFFFFF"
    assert contrast_ratio(hex_relative_luminance(accent), _zone_linear(0.85)) >= lyrics_layout.MIN_CONTRAST


def test_adaptive_colors_midtone_footage_keeps_a_visible_accent():
    # Gamma luma 0.30-0.55 is where most real footage lives. The accent must
    # stay distinct from the fill (a white accent on a white fill makes the
    # sweep karaoke invisible) and clear the floor against the LINEAR zone.
    for zone in (0.32, 0.45, 0.54):
        fill, accent, outline = adaptive_colors(
            zone_luma=zone, dominant_hue_deg=210.0, saturation=0.7
        )
        assert fill == "#FFFFFF"
        assert accent != fill, f"zone {zone}: accent collapsed into the fill"
        assert contrast_ratio(
            hex_relative_luminance(accent), _zone_linear(zone)
        ) >= lyrics_layout.MIN_CONTRAST


def test_adaptive_colors_midtone_honors_readable_override():
    # Warm gold on gamma-0.45 footage has a true (linear) contrast ~3.6:1 —
    # the gamma/linear mixup used to reject it.
    _, accent, _ = adaptive_colors(
        zone_luma=0.45, dominant_hue_deg=0.0, saturation=0.8, accent_override="#FFDF6B"
    )
    assert accent == "#FFDF6B"


def test_adaptive_colors_bright_footage_rejects_truly_unreadable_accent():
    # Rust-brown on gamma-0.60 footage: cleared the floor in gamma space (the
    # old bug) but its true linear contrast is ~1.8:1 — must be adapted away.
    _, accent, _ = adaptive_colors(
        zone_luma=0.60, dominant_hue_deg=0.0, saturation=0.8, accent_override="#A85A32"
    )
    assert accent != "#A85A32"
    assert contrast_ratio(
        hex_relative_luminance(accent), _zone_linear(0.60)
    ) >= lyrics_layout.MIN_CONTRAST


def test_adaptive_colors_low_saturation_footage_gets_neutral_accent():
    _, accent, _ = adaptive_colors(zone_luma=0.2, dominant_hue_deg=120.0, saturation=0.05)
    assert accent == lyrics_layout.NEUTRAL_ACCENT_ON_DARK


def test_adaptive_colors_honors_override_when_contrast_passes():
    _, accent, _ = adaptive_colors(
        zone_luma=0.1, dominant_hue_deg=0.0, saturation=0.8, accent_override="#FFD24A"
    )
    assert accent == "#FFD24A"


def test_adaptive_colors_rejects_unreadable_override():
    # Near-black accent on near-black footage fails the contrast floor.
    _, accent, _ = adaptive_colors(
        zone_luma=0.05, dominant_hue_deg=0.0, saturation=0.8, accent_override="#0A0A0A"
    )
    assert accent != "#0A0A0A"
    assert contrast_ratio(
        hex_relative_luminance(accent), _zone_linear(0.05)
    ) >= lyrics_layout.MIN_CONTRAST


# --- font sizing --------------------------------------------------------


def test_fit_font_size_keeps_base_for_short_text():
    assert fit_font_size("hold me", base_size_px=96, safe_width_px=900, width_factor=0.5) == 96


def test_fit_font_size_shrinks_long_lines():
    text = "and all the lights will guide us through the endless night"
    size = fit_font_size(text, base_size_px=96, safe_width_px=900, width_factor=0.5)
    assert size < 96
    # estimated width at the returned size must fit
    assert lyrics_layout.estimate_line_width(text, size, 0.5) <= 900


def test_fit_font_size_respects_floor():
    size = fit_font_size("x" * 500, base_size_px=96, safe_width_px=900, width_factor=0.5)
    assert size == lyrics_layout.MIN_FONT_SIZE_PX


def test_estimate_counts_caps_wider_and_spaces_narrower():
    lower = lyrics_layout.estimate_line_width("scream my name", 50, 0.5)
    caps = lyrics_layout.estimate_line_width("SCREAM MY NAME", 50, 0.5)
    assert caps > lower * 1.15
    # an all-caps font renders lowercase input as caps-width glyphs
    forced = lyrics_layout.estimate_line_width("scream my name", 50, 0.5, all_caps=True)
    assert forced == caps


def test_fit_font_size_gives_caps_lines_smaller_sizes():
    lower = fit_font_size("scream my name into the night", base_size_px=96,
                          safe_width_px=600, width_factor=0.55)
    caps = fit_font_size("SCREAM MY NAME INTO THE NIGHT", base_size_px=96,
                         safe_width_px=600, width_factor=0.55)
    assert caps < lower


# --- row wrapping --------------------------------------------------------


def test_plan_row_splits_short_line_single_row():
    words = ["hold", "me", "close"]
    size, splits = lyrics_layout.plan_row_splits(
        words, base_size_px=86, safe_width_px=864, width_factor=0.5
    )
    assert splits == (3,)
    assert size == 86


def test_plan_row_splits_long_line_wraps_instead_of_flooring():
    # One row would need a size below the readability floor; the planner must
    # split into rows rather than let a floored size overflow the safe width.
    words = "i remember it all too well standing there in the pouring rain again".split()
    size, splits = lyrics_layout.plan_row_splits(
        words, base_size_px=86, safe_width_px=864, width_factor=0.60
    )
    assert len(splits) >= 2
    assert size >= lyrics_layout.MIN_FONT_SIZE_PX
    # every row fits at the returned size
    start = 0
    for end in splits:
        row = " ".join(words[start:end])
        assert lyrics_layout.estimate_line_width(row, size, 0.60) <= 864
        start = end
    assert splits[-1] == len(words)


def test_plan_row_splits_never_overflows_even_for_absurd_lines():
    words = ["supercalifragilistic"] * 12
    size, splits = lyrics_layout.plan_row_splits(
        words, base_size_px=86, safe_width_px=864, width_factor=0.60
    )
    start = 0
    for end in splits:
        row = " ".join(words[start:end])
        assert lyrics_layout.estimate_line_width(row, size, 0.60) <= 864
        start = end


# --- style plan ---------------------------------------------------------


def test_style_for_time_base_and_section_override():
    sections = [{"start_sec": 10.0, "end_sec": 20.0, "style": "pop"}]
    assert style_for_time(5.0, "sweep", sections) == "sweep"
    assert style_for_time(10.0, "sweep", sections) == "pop"
    assert style_for_time(19.99, "sweep", sections) == "pop"
    assert style_for_time(20.0, "sweep", sections) == "sweep"


# --- whole-line planning -------------------------------------------------


def _line(start, end, text="hold me close"):
    words = []
    n = len(text.split())
    for i, w in enumerate(text.split()):
        w_start = start + (end - start) * i / n
        w_end = start + (end - start) * (i + 1) / n
        words.append({"text": w, "start_sec": w_start, "end_sec": w_end})
    return {"text": text, "start_sec": start, "end_sec": end, "words": words}


def test_plan_line_layouts_defaults_without_stats():
    layouts = plan_line_layouts(
        [_line(0.0, 2.0), _line(2.0, 4.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=None,
        base_size_px=86,
        width_factor=0.5,
    )
    assert len(layouts) == 2
    for layout in layouts:
        assert isinstance(layout, LineLayout)
        assert layout.band == 2
        assert layout.alignment == 2  # bottom-center
        assert layout.fill == "#FFFFFF"
        assert layout.accent == lyrics_layout.NEUTRAL_ACCENT_ON_DARK
        assert layout.style == "sweep"
        assert layout.font_size == 86


def test_plan_line_layouts_uses_stats_and_sections():
    stats = [_stats([(0.2, 0.05), (0.5, 0.9), (0.5, 0.95)], start=0.0, end=4.0)]
    layouts = plan_line_layouts(
        [_line(0.0, 2.0), _line(2.0, 4.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=[{"start_sec": 2.0, "end_sec": 4.0, "style": "pop"}],
        shot_stats=stats,
        base_size_px=86,
        width_factor=0.5,
    )
    assert layouts[0].band == 0
    assert layouts[0].alignment == 8  # top-center
    assert layouts[0].style == "sweep"
    assert layouts[1].style == "pop"
    # dark calm zone -> white fill
    assert layouts[0].fill == "#FFFFFF"


def test_plan_line_layouts_margin_v_matches_band_geometry():
    layouts = plan_line_layouts(
        [_line(0.0, 2.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=None,
        base_size_px=86,
        width_factor=0.5,
    )
    assert layouts[0].margin_v == round(1920 * lyrics_layout.SAFE_BOTTOM_FRAC)


def test_width_factor_present_on_all_catalog_fonts():
    from api.prototyping.edit.skills.lyrics_fonts import FONT_CATALOG

    for spec in FONT_CATALOG.values():
        assert 0.3 <= spec.width_factor <= 0.7, spec.font_id


def test_plan_line_layouts_wraps_long_lines_into_rows():
    long_line = _line(0.0, 4.0, text="i remember it all too well standing there in the pouring rain again")
    layouts = plan_line_layouts(
        [long_line],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=None,
        base_size_px=86,
        width_factor=0.60,
    )
    assert len(layouts[0].row_splits) >= 2
    assert layouts[0].row_splits[-1] == len(long_line["words"])


def test_plan_line_layouts_single_row_for_short_lines():
    layouts = plan_line_layouts(
        [_line(0.0, 2.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=None,
        base_size_px=86,
        width_factor=0.5,
    )
    assert layouts[0].row_splits == (3,)


def test_aggregate_hue_ignores_grayscale_filler_shots():
    # A near-grayscale shot reports hue 0.0 (red) as a filler value; the
    # aggregate hue must stay with the saturated footage, not drift to red.
    vivid_blue = _stats([(0.3, 0.1)] * 3, start=0.0, end=1.0, hue=240.0, sat=0.6)
    grayscale = _stats([(0.3, 0.1)] * 3, start=1.0, end=2.0, hue=0.0, sat=0.02)
    zones, hue, sat = lyrics_layout._aggregate_stats(0.0, 2.0, [vivid_blue, grayscale])
    assert hue == pytest.approx(240.0, abs=8.0)


def test_plan_line_layouts_palette_has_hysteresis_across_cuts():
    # Lines alternating over dark and mid-bright shots must not flip fill
    # polarity every line — mid values inside the hysteresis band keep the
    # previous palette.
    dark = _stats([(0.20, 0.1)] * 3, start=0.0, end=2.0, hue=30.0, sat=0.5)
    midbright = _stats([(0.58, 0.1)] * 3, start=2.0, end=4.0, hue=30.0, sat=0.5)
    layouts = plan_line_layouts(
        [_line(0.0, 2.0), _line(2.0, 4.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=[dark, midbright],
        base_size_px=86,
        width_factor=0.5,
    )
    # 0.58 is above the plain 0.55 split but inside the exit band (<=0.62):
    # the palette must stay in dark polarity, identical to line 1.
    assert layouts[0].fill == "#FFFFFF"
    assert layouts[1].fill == layouts[0].fill
    assert layouts[1].accent == layouts[0].accent


def test_plan_line_layouts_palette_flips_on_committed_brightness_change():
    dark = _stats([(0.20, 0.1)] * 3, start=0.0, end=2.0, hue=30.0, sat=0.5)
    bright = _stats([(0.80, 0.1)] * 3, start=2.0, end=4.0, hue=30.0, sat=0.5)
    layouts = plan_line_layouts(
        [_line(0.0, 2.0), _line(2.0, 4.0)],
        output_size=(1080, 1920),
        base_style="sweep",
        section_styles=(),
        shot_stats=[dark, bright],
        base_size_px=86,
        width_factor=0.5,
    )
    assert layouts[0].fill == "#FFFFFF"
    assert layouts[1].fill == lyrics_layout.INK_FILL
