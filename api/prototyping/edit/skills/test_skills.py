import pytest

import api.prototyping.edit.skills as skills

STARTER_IDS = {"text.hook", "text.caption", "text.lower_third", "mask.vignette"}


def test_starter_skills_registered():
    assert STARTER_IDS <= skills.ids()


def test_each_starter_skill_has_description():
    for sid in STARTER_IDS:
        assert skills.get(sid).description.strip()


def test_text_skill_requires_nonempty_text():
    skill = skills.get("text.hook")
    with pytest.raises(Exception):
        skill.params_model(text="")


def test_text_skill_accepts_text():
    params = skills.get("text.caption").params_model(text="hello")
    assert params.text == "hello"


def test_vignette_strength_defaults_and_rejects_out_of_range():
    skill = skills.get("mask.vignette")
    assert skill.params_model().strength == pytest.approx(0.6)
    with pytest.raises(Exception):
        skill.params_model(strength=2.0)


def _ctx(font_path="/fonts/overlay.otf"):
    from api.prototyping.edit.skills.base import RenderContext

    return RenderContext(output_size=(1080, 1920), fps=30, font_path=font_path)


def _overlay(skill_id, params, start=0.0, end=1.5):
    from api.prototyping.edit.skills.base import ResolvedOverlay

    return ResolvedOverlay(
        skill_id=skill_id, timeline_start_sec=start, timeline_end_sec=end, params=params
    )


def test_escape_drawtext_text_double_escapes_for_both_parsers():
    from api.prototyping.edit.skills.text_common import escape_drawtext_text

    # option-level escape then graph-level escape (ffmpeg parses twice):
    # ":" -> "\:" -> "\\:" ; "'" -> "\'" -> "\\\'" ; "," -> "," -> "\,"
    assert escape_drawtext_text("50: it's a,b;c") == "50\\\\: it\\\\\\'s a\\,b\\;c"
    assert escape_drawtext_text("a\\b") == "a\\\\\\\\b"
    assert escape_drawtext_text("line\nbreak") == "line break"
    # drawtext expansion syntax is defused, a lone % passes through
    assert escape_drawtext_text("100%{x}") == "100% {x}"


def test_escape_drawtext_path_handles_windows_fonts():
    from api.prototyping.edit.skills.text_common import escape_drawtext_path

    assert escape_drawtext_path(r"C:\Windows\Fonts\arialbd.ttf") == "C\\\\:/Windows/Fonts/arialbd.ttf"


def test_text_hook_ffmpeg_fragment():
    skill = skills.get("text.hook")
    assert skill.ffmpeg_supported is True
    frag = skill.ffmpeg_filter(_overlay("text.hook", {"text": "no way"}), _ctx())
    # hook style at 1080x1920: fontsize=int(1920*0.075)=144, borderw=int(144*0.08)=11,
    # centered x, y=int(1920*0.17)=326
    assert frag == (
        "drawtext=fontfile=/fonts/overlay.otf:text=no way:fontsize=144:"
        "fontcolor=white:bordercolor=black:borderw=11:"
        "x=(w-text_w)/2:y=326:enable='between(t,0.000,1.500)'"
    )


def test_text_lower_third_fragment_is_left_anchored():
    frag = skills.get("text.lower_third").ffmpeg_filter(
        _overlay("text.lower_third", {"text": "tokyo"}), _ctx()
    )
    # left anchor x=int(1080*0.06)=64, y=int(1920*0.72)=1382, fontsize=int(1920*0.045)=86
    assert "x=64:y=1382" in frag
    assert "fontsize=86" in frag


def test_text_fragment_requires_font_path():
    with pytest.raises(ValueError, match="font"):
        skills.get("text.caption").ffmpeg_filter(
            _overlay("text.caption", {"text": "hi"}), _ctx(font_path="")
        )


def test_vignette_ffmpeg_fragment_maps_strength_to_angle():
    skill = skills.get("mask.vignette")
    assert skill.ffmpeg_supported is True
    frag = skill.ffmpeg_filter(_overlay("mask.vignette", {"strength": 0.6}, end=6.0), _ctx())
    # a = 0.2 + 0.9*0.6 = 0.74
    assert frag == "vignette=a=0.7400:enable='between(t,0.000,6.000)'"
