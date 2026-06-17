"""Shared text-overlay styling + layer construction.

`TextParams` and `TextStyle` are pure (importable on the control plane). The
moviepy `TextClip` construction lives in `build_text_layers`, which imports
moviepy lazily so the metadata stays importable without the render stack.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from .base import RenderContext, ResolvedOverlay

# Keep text inside a horizontal safe margin so nothing clips on 9:16.
SAFE_WIDTH_FRAC = 0.86


class TextParams(BaseModel):
    text: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class TextStyle:
    size_frac: float       # font size as a fraction of output height
    rel_y: float           # top of the text block as a fraction of height
    align: str             # "center" | "left"
    rel_x: float = 0.0     # left anchor as a fraction of width (align="left")
    stroke_frac: float = 0.06  # stroke width as a fraction of font size


def build_text_layers(
    text: str,
    style: TextStyle,
    overlay: ResolvedOverlay,
    ctx: RenderContext,
) -> list:
    from moviepy import TextClip

    width, height = ctx.output_size
    font_size = max(8, int(height * style.size_frac))
    stroke_width = max(1, int(font_size * style.stroke_frac))
    clip = TextClip(
        font=ctx.font_path,
        text=text,
        font_size=font_size,
        color="white",
        stroke_color="black",
        stroke_width=stroke_width,
        method="caption",
        size=(int(width * SAFE_WIDTH_FRAC), None),
        text_align=style.align,
    )
    clip = clip.with_start(overlay.timeline_start_sec).with_duration(overlay.duration_sec)
    if style.align == "left":
        clip = clip.with_position((int(width * style.rel_x), int(height * style.rel_y)))
    else:
        clip = clip.with_position(("center", int(height * style.rel_y)))
    return [clip]
