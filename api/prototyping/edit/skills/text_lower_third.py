from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers

STYLE = TextStyle(size_frac=0.045, rel_y=0.72, align="left", rel_x=0.06, stroke_frac=0.06)


class TextLowerThird(OverlaySkill):
    id = "text.lower_third"
    description = (
        "Left-aligned lower-third label (a name, place, or tag) sitting above "
        "the bottom safe area. Param: text."
    )
    params_model = TextParams

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)


register(TextLowerThird())
