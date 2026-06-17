from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers

STYLE = TextStyle(size_frac=0.075, rel_y=0.17, align="center", stroke_frac=0.08)


class TextHook(OverlaySkill):
    id = "text.hook"
    description = (
        "Large centered hook line in the upper third — the punchy opening "
        "statement that makes a viewer stay. Use once, early (within the first "
        "~1.5s), with a few words at most. Param: text."
    )
    params_model = TextParams

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)


register(TextHook())
