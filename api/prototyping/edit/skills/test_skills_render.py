"""Guarded tests for the moviepy layer construction in each skill.

These exercise `build_layers`, which needs moviepy + a usable font file. They
skip cleanly where neither is available (e.g. a moviepy-less control plane).
"""
from pathlib import Path

import pytest

import api.prototyping.edit.skills as skills
from api.prototyping.edit.skills.base import RenderContext, ResolvedOverlay

pytest.importorskip("moviepy")

OUTPUT_SIZE = (1080, 1920)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def _font_path() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    pytest.skip("no usable font file found for TextClip")


@pytest.fixture
def ctx() -> RenderContext:
    return RenderContext(output_size=OUTPUT_SIZE, fps=30, font_path=_font_path())


def test_text_hook_layer_timing_and_fits_width(ctx):
    overlay = ResolvedOverlay(
        skill_id="text.hook",
        timeline_start_sec=0.5,
        timeline_end_sec=2.0,
        params={"text": "no way"},
    )
    layers = skills.get("text.hook").build_layers(overlay, ctx)
    assert len(layers) == 1
    layer = layers[0]
    assert layer.start == pytest.approx(0.5)
    assert layer.duration == pytest.approx(1.5)
    assert layer.size[0] <= OUTPUT_SIZE[0]


def test_vignette_layer_matches_output_size(ctx):
    overlay = ResolvedOverlay(
        skill_id="mask.vignette",
        timeline_start_sec=0.0,
        timeline_end_sec=3.0,
        params={},
    )
    layers = skills.get("mask.vignette").build_layers(overlay, ctx)
    assert len(layers) == 1
    layer = layers[0]
    assert tuple(layer.size) == OUTPUT_SIZE
    assert layer.duration == pytest.approx(3.0)
    assert layer.mask is not None  # alpha drives the edge darkening
