from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers

STYLE = TextStyle(size_frac=0.038, rel_y=0.80, align="center", stroke_frac=0.06)


class TextCaption(OverlaySkill):
    id = "text.caption"
    description = (
        "Smaller centered caption near the bottom (inside the Instagram safe "
        "area) for a short supporting line. Param: text."
    )
    params_model = TextParams

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)


register(TextCaption())
