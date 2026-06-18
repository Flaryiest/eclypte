from __future__ import annotations

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register
from .text_common import TextParams, TextStyle, build_text_layers

# Lower-middle, centered, heavy stroke so the line reads over any footage.
STYLE = TextStyle(size_frac=0.05, rel_y=0.62, align="center", stroke_frac=0.09)


class TextLyric(OverlaySkill):
    id = "text.lyric"
    description = (
        "A single synced lyric line, centered in the lower-middle of the frame. "
        "Auto-generated from the song's lyrics (not placed by the agent). Param: text."
    )
    params_model = TextParams

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        text = self.params_model(**overlay.params).text
        return build_text_layers(text, STYLE, overlay, ctx)


register(TextLyric())
