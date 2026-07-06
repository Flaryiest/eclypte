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

# ffmpeg parses -filter_complex twice: the graph parser (quotes/backslashes,
# and `[ ] , ;` as structure) runs first, then the per-filter option parser
# (`:` separates options, `\` escapes, `'` quotes). A literal value therefore
# needs TWO rounds of escaping — option-level first, then graph-level — per
# the "Notes on filtergraph escaping" section of the ffmpeg-utils docs.
_OPTION_SPECIALS = "\\':"
_GRAPH_SPECIALS = "\\'[],;"


def _escape(value: str, specials: str) -> str:
    return "".join(f"\\{ch}" if ch in specials else ch for ch in value)


def escape_drawtext_text(text: str) -> str:
    """Double-escape user text for a drawtext `text=` option value.

    Newlines flatten to spaces; `%{` (drawtext's expansion syntax) is defused
    with a space since there is no reliable literal escape for it."""
    flattened = " ".join(text.splitlines()).replace("%{", "% {")
    return _escape(_escape(flattened, _OPTION_SPECIALS), _GRAPH_SPECIALS)


def escape_drawtext_path(path: str) -> str:
    """Double-escape a font path for drawtext `fontfile=` (Windows drives too)."""
    return _escape(_escape(path.replace("\\", "/"), _OPTION_SPECIALS), _GRAPH_SPECIALS)


def drawtext_fragment(
    text: str,
    style: TextStyle,
    overlay: ResolvedOverlay,
    ctx: RenderContext,
) -> str:
    """Pure ffmpeg drawtext fragment matching build_text_layers' styling.

    No wrapping (drawtext has none); agent text is short by contract. Raises
    when no font file is available — the caller resolves and supplies it.
    """
    if not ctx.font_path:
        raise ValueError("drawtext requires a font path (ctx.font_path is empty)")
    width, height = ctx.output_size
    font_size = max(8, int(height * style.size_frac))
    border_w = max(1, int(font_size * style.stroke_frac))
    if style.align == "left":
        x = str(int(width * style.rel_x))
    else:
        x = "(w-text_w)/2"
    y = int(height * style.rel_y)
    return (
        f"drawtext=fontfile={escape_drawtext_path(ctx.font_path)}:"
        f"text={escape_drawtext_text(text)}:fontsize={font_size}:"
        f"fontcolor=white:bordercolor=black:borderw={border_w}:"
        f"x={x}:y={y}:"
        f"enable='between(t,{overlay.timeline_start_sec:.3f},{overlay.timeline_end_sec:.3f})'"
    )


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
