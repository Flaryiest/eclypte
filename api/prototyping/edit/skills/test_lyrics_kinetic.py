import pytest

import api.prototyping.edit.skills as skills
from api.prototyping.edit.skills.base import RenderContext, ResolvedOverlay
from api.prototyping.edit.skills.lyrics_kinetic import (
    ASS_FILENAME,
    KineticLyricsParams,
    build_ass_for_overlay,
)


def _words(*specs):
    return [{"text": t, "start_sec": s, "end_sec": e} for t, s, e in specs]


def _params(**overrides):
    base = {
        "font_id": "bebas_neue",
        "style": "sweep",
        "lines": [
            {
                "text": "hold me close",
                "start_sec": 0.0,
                "end_sec": 1.5,
                "words": _words(("hold", 0.0, 0.5), ("me", 0.5, 1.0), ("close", 1.0, 1.5)),
            },
            {
                "text": "never let go",
                "start_sec": 2.2,
                "end_sec": 3.6,
                "words": _words(("never", 2.2, 2.7), ("let", 2.7, 3.1), ("go", 3.1, 3.6)),
            },
        ],
    }
    base.update(overrides)
    return KineticLyricsParams(**base)


def _ctx(**overrides):
    fields = {
        "output_size": (1080, 1920),
        "fps": 30,
        "font_path": "/fonts/overlay.otf",
        "asset_dir": "/scratch",
        "fonts_dir": "/fonts/kinetic",
    }
    fields.update(overrides)
    return RenderContext(**fields)


def _overlay(params, end=25.0):
    return ResolvedOverlay(
        skill_id="lyrics.kinetic",
        timeline_start_sec=0.0,
        timeline_end_sec=end,
        params=params.model_dump(),
    )


# --- registration / flags -------------------------------------------------


def test_registered_with_lyrics_kind_and_flags():
    skill = skills.get("lyrics.kinetic")
    assert skill.kind == "lyrics"
    assert skill.ffmpeg_supported is True
    assert skill.wants_shot_stats is True
    assert skill.singleton is True
    assert skill.description.strip()


def test_base_skill_defaults_for_new_contract():
    # existing skills are untouched by the new contract
    hook = skills.get("text.hook")
    assert hook.wants_shot_stats is False
    assert hook.singleton is False
    assert hook.ffmpeg_assets(None, None) == {}


# --- params validation ------------------------------------------------------


def test_params_reject_unknown_font():
    with pytest.raises(Exception):
        _params(font_id="comic_sans")


def test_params_reject_malformed_accent():
    with pytest.raises(Exception):
        _params(accent_color="red")
    assert _params(accent_color="#FFD24A").accent_color == "#FFD24A"


def test_params_require_lines():
    with pytest.raises(Exception):
        _params(lines=[])


def test_params_defaults():
    params = _params()
    assert params.style == "sweep"
    assert params.mode == "aligned"
    assert params.masking == "none"
    assert params.section_styles == []


# --- ASS document assembly ---------------------------------------------------


def test_sweep_document_structure():
    doc = build_ass_for_overlay(_params(), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    assert "PlayResX: 1080" in doc
    assert "PlayResY: 1920" in doc
    # one dialogue per line, karaoke-filled
    assert doc.count("Dialogue:") == 2
    assert "{\\kf50}hold {\\kf50}me {\\kf50}close" in doc
    # sweep = accent fills through the line: primary(accent) != secondary(fill)
    assert "Style: L0,Bebas Neue," in doc


def test_sweep_line_events_clamp_to_next_line_start():
    doc = build_ass_for_overlay(_params(), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    # line 1 ends at 1.5s; hold would run past 2.2s only if unclamped — the
    # event must end at or before line 2's 2.2s start.
    assert "Dialogue: 0,0:00:00.00,0:00:01.85,L0" in doc
    assert ",0:00:02.20," in doc


def test_pop_document_one_event_per_word_centered():
    doc = build_ass_for_overlay(
        _params(style="pop"), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0
    )
    assert doc.count("Dialogue:") == 6
    assert "\\fscx" in doc  # scale-pop animation
    # pop styles force middle-center regardless of band
    for line_style in ("L0", "L1"):
        style_line = next(l for l in doc.splitlines() if l.startswith(f"Style: {line_style},"))
        assert style_line.split(",")[18] == "5"


def test_build_document_accumulates_words_with_accent_on_last():
    doc = build_ass_for_overlay(
        _params(style="build"), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0
    )
    assert doc.count("Dialogue:") == 6
    # second word event shows first word in fill and current word in accent
    assert "hold {\\1c" in doc
    assert "}me" in doc


def test_section_styles_switch_variant_mid_reel():
    doc = build_ass_for_overlay(
        _params(section_styles=[{"start_sec": 2.0, "end_sec": 4.0, "style": "pop"}]),
        shot_stats=None,
        output_size=(1080, 1920),
        duration_sec=25.0,
    )
    # line 1 sweeps (1 event), line 2 pops (3 word events)
    assert doc.count("Dialogue:") == 4


# --- ffmpeg integration -------------------------------------------------------


def test_ffmpeg_assets_returns_ass_document():
    skill = skills.get("lyrics.kinetic")
    assets = skill.ffmpeg_assets(_overlay(_params()), _ctx())
    assert set(assets) == {ASS_FILENAME}
    assert "[Script Info]" in assets[ASS_FILENAME]


def test_ffmpeg_filter_exact_fragment_with_windows_asset_dir():
    skill = skills.get("lyrics.kinetic")
    frag = skill.ffmpeg_filter(_overlay(_params()), _ctx(asset_dir="C:\\tmp\\assets"))
    assert frag == (
        "ass=filename=C\\\\:/tmp/assets/lyrics_kinetic.ass:fontsdir=/fonts/kinetic"
    )


def test_ffmpeg_filter_omits_fontsdir_when_unresolved():
    skill = skills.get("lyrics.kinetic")
    frag = skill.ffmpeg_filter(_overlay(_params()), _ctx(fonts_dir=""))
    assert frag == "ass=filename=/scratch/lyrics_kinetic.ass"


def test_ffmpeg_filter_requires_asset_dir():
    skill = skills.get("lyrics.kinetic")
    with pytest.raises(ValueError, match="asset_dir"):
        skill.ffmpeg_filter(_overlay(_params()), _ctx(asset_dir=""))


def test_build_layers_is_noop_on_moviepy_path():
    skill = skills.get("lyrics.kinetic")
    assert skill.build_layers(_overlay(_params()), _ctx()) == []


def test_build_single_word_line_merges_fades():
    # One \fad per event: libass keeps only the last tag, so a single-word
    # line needs the in+out merged into {\fad(80,120)}.
    params = _params(
        style="build",
        lines=[{
            "text": "yeah", "start_sec": 0.0, "end_sec": 0.8,
            "words": [{"text": "yeah", "start_sec": 0.0, "end_sec": 0.8}],
        }],
    )
    doc = build_ass_for_overlay(params, shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    assert "{\\fad(80,120)}" in doc
    assert "{\\fad(80,0)}{\\fad(0,120)}" not in doc


def test_sweep_long_line_wraps_with_hard_breaks():
    words = "i remember it all too well standing there in the pouring rain again".split()
    n = len(words)
    step = 3.0 / n
    params = _params(
        font_id="archivo_black",  # widest catalog face forces the wrap
        lines=[{
            "text": " ".join(words), "start_sec": 0.0, "end_sec": 3.0,
            "words": [
                {"text": w, "start_sec": round(i * step, 3), "end_sec": round((i + 1) * step, 3)}
                for i, w in enumerate(words)
            ],
        }],
    )
    doc = build_ass_for_overlay(params, shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    assert "\\N" in doc


def test_styles_carry_spacing_shadow_and_soft_back():
    doc = build_ass_for_overlay(_params(), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    style_line = next(l for l in doc.splitlines() if l.startswith("Style: L0,"))
    fields = style_line.split(",")
    # bebas_neue carries letter-spacing; shadow gives the text depth
    assert float(fields[13]) > 0        # Spacing
    assert float(fields[17]) > 0        # Shadow
    # BackColour (shadow color) is semi-transparent black, not fully transparent
    assert fields[6].startswith("&H") and fields[6] != "&HFF000000"


def test_sweep_base_size_is_prominent():
    # 1920-high reel: sweep lines should render >= 100px so the text reads as
    # a designed element, not a subtitle afterthought.
    doc = build_ass_for_overlay(_params(), shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    style_line = next(l for l in doc.splitlines() if l.startswith("Style: L0,"))
    assert int(style_line.split(",")[2]) >= 100


def test_pop_words_share_one_size_across_lines():
    params = _params(
        style="pop",
        lines=[
            {"text": "go", "start_sec": 0.0, "end_sec": 0.6,
             "words": [{"text": "go", "start_sec": 0.0, "end_sec": 0.6}]},
            {"text": "running", "start_sec": 1.0, "end_sec": 1.8,
             "words": [{"text": "running", "start_sec": 1.0, "end_sec": 1.8}]},
        ],
    )
    doc = build_ass_for_overlay(params, shot_stats=None, output_size=(1080, 1920), duration_sec=25.0)
    sizes = {
        int(l.split(",")[2])
        for l in doc.splitlines()
        if l.startswith("Style: L")
    }
    assert len(sizes) == 1  # "go" must not render comically larger than "running"
