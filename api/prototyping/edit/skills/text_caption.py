from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers, drawtext_fragment

STYLE = TextStyle(size_frac=0.038, rel_y=0.80, align="center", stroke_frac=0.06)


class TextCaption(OverlaySkill):
    id = "text.caption"
    description = (
        "Smaller centered caption near the bottom (inside the Instagram safe "
        "area) for a short supporting line. Only use when the brief explicitly "
        "asks for on-screen text; otherwise omit it. Param: text."
    )
    params_model = TextParams
    ffmpeg_supported = True

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        text = self.params_model(**overlay.params).text
        return drawtext_fragment(text, STYLE, overlay, ctx)


register(TextCaption())
