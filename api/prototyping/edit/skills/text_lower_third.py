from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers, drawtext_fragment

STYLE = TextStyle(size_frac=0.045, rel_y=0.72, align="left", rel_x=0.06, stroke_frac=0.06)


class TextLowerThird(OverlaySkill):
    id = "text.lower_third"
    description = (
        "Left-aligned lower-third label (a name, place, or tag) sitting above "
        "the bottom safe area. Only use when the brief explicitly asks for "
        "on-screen text; otherwise omit it. Param: text."
    )
    params_model = TextParams
    ffmpeg_supported = True

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        text = self.params_model(**overlay.params).text
        return drawtext_fragment(text, STYLE, overlay, ctx)


register(TextLowerThird())
