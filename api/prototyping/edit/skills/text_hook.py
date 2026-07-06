from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers, drawtext_fragment

STYLE = TextStyle(size_frac=0.075, rel_y=0.17, align="center", stroke_frac=0.08)


class TextHook(OverlaySkill):
    id = "text.hook"
    description = (
        "Large centered hook line in the upper third. Only use when the brief "
        "explicitly asks for on-screen hook text; otherwise omit it. A few words "
        "at most. Param: text."
    )
    params_model = TextParams
    ffmpeg_supported = True

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        text = self.params_model(**overlay.params).text
        return drawtext_fragment(text, STYLE, overlay, ctx)


register(TextHook())
