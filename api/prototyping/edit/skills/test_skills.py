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


def test_text_lyric_registered():
    skill = skills.get("text.lyric")
    assert skill.description.strip()
    assert skill.params_model(text="a line").text == "a line"
