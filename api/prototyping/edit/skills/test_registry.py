import pytest
from pydantic import BaseModel

from api.prototyping.edit.skills.base import OverlaySkill
from api.prototyping.edit.skills.registry import Registry


class _DummyParams(BaseModel):
    text: str = ""


class _DummySkill(OverlaySkill):
    id = "text.dummy"
    description = "A dummy skill for tests."
    params_model = _DummyParams


def test_register_and_get():
    reg = Registry()
    skill = _DummySkill()
    reg.register(skill)
    assert reg.get("text.dummy") is skill


def test_ids_lists_registered():
    reg = Registry()
    reg.register(_DummySkill())
    assert reg.ids() == {"text.dummy"}


def test_duplicate_registration_raises():
    reg = Registry()
    reg.register(_DummySkill())
    with pytest.raises(ValueError):
        reg.register(_DummySkill())


def test_get_unknown_raises():
    reg = Registry()
    with pytest.raises(KeyError):
        reg.get("text.nope")


def test_agent_catalog_lists_id_description_and_kind():
    reg = Registry()
    reg.register(_DummySkill())
    assert reg.agent_catalog() == [
        {"id": "text.dummy", "description": "A dummy skill for tests.", "kind": "overlay"}
    ]


def test_skill_defaults_to_overlay_kind_without_ffmpeg_support():
    skill = _DummySkill()
    assert skill.kind == "overlay"
    assert skill.ffmpeg_supported is False


def test_ffmpeg_filter_raises_unless_overridden():
    with pytest.raises(NotImplementedError):
        _DummySkill().ffmpeg_filter(None, None)
