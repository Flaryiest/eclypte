"""Kinetic lyrics skill: word-synced lyric text burned over the whole reel.

The agent enables this via finish_edit's dedicated ``lyrics`` field (not the
overlays list); the adapter embeds the windowed word-timing payload in the
overlay params so the timeline JSON stays self-contained for the renderer.

Three treatments, switchable per song section:
- ``sweep``: the full line on screen, accent color filling word-by-word as
  the vocal passes over it (ASS ``\\kf`` karaoke)
- ``pop``: one big word at a time, center stage, landing on its timestamp
- ``build``: words accumulate into the line, the current word accented

Everything here is pure string building (module stays moviepy-free); the
render executor materializes ``ffmpeg_assets`` and libass does the drawing.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field, field_validator

from .base import OverlaySkill, RenderContext, ResolvedOverlay, ShotStats
from .lyrics_ass import AssEvent, AssStyle, ass_color, kf_line_text, sanitize_ass_text
from .lyrics_fonts import font_ids, get_font
from .lyrics_layout import (
    SAFE_SIDE_FRAC,
    fit_font_size,
    plan_line_layouts,
)
from .registry import register
from .text_common import escape_drawtext_path

logger = logging.getLogger(__name__)

ASS_FILENAME = "lyrics_kinetic.ass"

# Base font sizes as fractions of output height. Lyric text is a designed
# element, not a subtitle — err prominent; long lines wrap rather than shrink.
SWEEP_SIZE_FRAC = 0.056   # full lines (sweep/build)
POP_SIZE_FRAC = 0.098     # single big words
POP_MIN_SCALE = 0.65      # one long word may not shrink every pop below this
OUTLINE_FRAC = 0.05       # outline width as a fraction of font size
SHADOW_FRAC = 0.03        # drop-shadow depth as a fraction of font size
SHADOW_ALPHA = 0.35       # shadow transparency (ASS BackColour alpha)
LINE_HOLD_SEC = 0.35      # how long a finished line lingers (clamped to the next line)
POP_HOLD_SEC = 0.30       # how long a popped word lingers past its end

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class LyricWord(BaseModel):
    text: str = Field(min_length=1)
    start_sec: float = Field(ge=0)
    end_sec: float
    confidence: float = Field(default=1.0, ge=0, le=1)


class LyricLine(BaseModel):
    text: str = ""
    start_sec: float
    end_sec: float
    words: list[LyricWord] = Field(min_length=1)


class SectionStyle(BaseModel):
    start_sec: float
    end_sec: float
    style: str = Field(pattern=r"^(sweep|pop|build)$")


class KineticLyricsParams(BaseModel):
    font_id: str
    style: str = Field(default="sweep", pattern=r"^(sweep|pop|build)$")
    section_styles: list[SectionStyle] = Field(default_factory=list)
    accent_color: str | None = None  # None => footage-adaptive
    mode: str = Field(default="aligned", pattern=r"^(aligned|transcribed)$")
    masking: str = Field(default="none", pattern=r"^none$")  # phase-2 slot
    lines: list[LyricLine] = Field(min_length=1)

    @field_validator("font_id")
    @classmethod
    def _known_font(cls, value: str) -> str:
        if value not in font_ids():
            raise ValueError(f"unknown font_id {value!r}")
        return value

    @field_validator("accent_color")
    @classmethod
    def _hex_accent(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("accent_color must be #RRGGBB")
        return value


def _line_end(params: KineticLyricsParams, index: int, duration_sec: float) -> float:
    """Where line ``index``'s last event may run to: its end plus a short
    hold, clamped to the next line's start and the reel end."""
    line = params.lines[index]
    end = line.end_sec + LINE_HOLD_SEC
    if index + 1 < len(params.lines):
        end = min(end, params.lines[index + 1].start_sec)
    return min(end, duration_sec)


def _row_starts(row_splits: tuple[int, ...]) -> frozenset[int]:
    """Word indices that begin a new visual row (the last split is the end)."""
    return frozenset(row_splits[:-1])


def _sweep_events(
    line: LyricLine, style_name: str, end_sec: float,
    row_splits: tuple[int, ...] = (),
) -> list[AssEvent]:
    words = [w.model_dump() for w in line.words]
    text = "{\\fad(120,160)}" + kf_line_text(
        words, line_start_sec=line.start_sec, row_breaks=_row_starts(row_splits)
    )
    return [AssEvent(start_sec=line.start_sec, end_sec=end_sec, style_name=style_name, text=text)]


def _pop_events(line: LyricLine, style_name: str, end_sec: float) -> list[AssEvent]:
    events = []
    for j, word in enumerate(line.words):
        if j + 1 < len(line.words):
            word_end = min(line.words[j + 1].start_sec, word.end_sec + POP_HOLD_SEC)
        else:
            word_end = min(word.end_sec + POP_HOLD_SEC, end_sec)
        clean = sanitize_ass_text(word.text)
        if not clean or word_end <= word.start_sec:
            continue
        text = "{\\fscx90\\fscy90\\t(0,80,\\fscx100\\fscy100)\\fad(40,60)}" + clean
        events.append(
            AssEvent(start_sec=word.start_sec, end_sec=word_end, style_name=style_name, text=text)
        )
    return events


def _build_events(
    line: LyricLine, style_name: str, end_sec: float, accent_ass: str,
    row_splits: tuple[int, ...] = (),
) -> list[AssEvent]:
    events = []
    clean_words = [sanitize_ass_text(w.text) for w in line.words]
    row_starts = _row_starts(row_splits)
    for j, word in enumerate(line.words):
        if not clean_words[j]:
            continue
        word_end = line.words[j + 1].start_sec if j + 1 < len(line.words) else end_sec
        if word_end <= word.start_sec:
            continue
        # One \fad per event — libass keeps only the last tag, so fade-in and
        # fade-out merge (a single-word line needs both at once).
        fade_in = 80 if j == 0 else 0
        fade_out = 120 if j == len(line.words) - 1 else 0
        fade = f"{{\\fad({fade_in},{fade_out})}}" if (fade_in or fade_out) else ""
        pieces: list[str] = []
        for k in range(j):
            if not clean_words[k]:
                continue
            if pieces:
                pieces.append("\\N" if k in row_starts else " ")
            pieces.append(clean_words[k])
        if pieces:
            pieces.append("\\N" if j in row_starts else " ")
        pieces.append(f"{{\\1c{accent_ass}}}{clean_words[j]}")
        events.append(
            AssEvent(start_sec=word.start_sec, end_sec=word_end,
                     style_name=style_name, text=fade + "".join(pieces))
        )
    return events


def build_ass_for_overlay(
    params: KineticLyricsParams,
    shot_stats: tuple[ShotStats, ...] | None,
    output_size: tuple[int, int],
    duration_sec: float,
) -> str:
    """Assemble the complete ASS document: per-line adaptive layout (band,
    palette, size), then style + events per treatment."""
    from .lyrics_ass import build_ass_document  # local to keep import cycles impossible

    width, height = output_size
    font = get_font(params.font_id)
    safe_width = width * (1 - 2 * SAFE_SIDE_FRAC)
    margin_side = round(width * SAFE_SIDE_FRAC)
    # Tracking widens every glyph cell; fold it into the width estimate.
    effective_wf = font.width_factor + font.spacing_frac

    layouts = plan_line_layouts(
        [line.model_dump() for line in params.lines],
        output_size=output_size,
        base_style=params.style,
        section_styles=[s.model_dump() for s in params.section_styles],
        shot_stats=shot_stats,
        base_size_px=round(height * SWEEP_SIZE_FRAC),
        width_factor=effective_wf,
        accent_override=params.accent_color,
        all_caps=font.all_caps,
    )

    # One pop size for the whole reel (a lone "go" popping comically larger
    # than its neighbors reads as a glitch); a line whose own longest word
    # can't fit at the shared size still shrinks individually.
    pop_base = round(height * POP_SIZE_FRAC)
    pop_fits: dict[int, int] = {}
    for i, (line, layout) in enumerate(zip(params.lines, layouts)):
        if layout.style == "pop":
            longest = max((sanitize_ass_text(w.text) for w in line.words), key=len, default="")
            pop_fits[i] = fit_font_size(
                longest, base_size_px=pop_base, safe_width_px=safe_width,
                width_factor=effective_wf, all_caps=font.all_caps,
            )
    shared_pop = max(min(pop_fits.values()), round(pop_base * POP_MIN_SCALE)) if pop_fits else pop_base

    def _style(name: str, size: int, *, primary: str, secondary: str,
               outline_colour: str, alignment: int, margin_v: int) -> AssStyle:
        return AssStyle(
            name=name, fontname=font.family, fontsize=size,
            primary=primary, secondary=secondary,
            outline_colour=outline_colour,
            back_colour=ass_color("#000000", alpha=SHADOW_ALPHA),
            outline=max(2.5, round(size * OUTLINE_FRAC, 1)),
            shadow=round(size * SHADOW_FRAC, 1),
            spacing=round(size * font.spacing_frac, 1),
            alignment=alignment,
            margin_l=margin_side, margin_r=margin_side, margin_v=margin_v,
        )

    styles: list[AssStyle] = []
    events: list[AssEvent] = []
    for i, (line, layout) in enumerate(zip(params.lines, layouts)):
        if line.start_sec >= duration_sec:
            continue
        end_sec = _line_end(params, i, duration_sec)
        if end_sec <= line.start_sec:
            continue
        style_name = f"L{i}"
        fill = ass_color(layout.fill)
        accent = ass_color(layout.accent)
        outline_colour = ass_color(layout.outline)

        if layout.style == "pop":
            styles.append(
                _style(style_name, min(shared_pop, pop_fits[i]),
                       primary=fill, secondary=accent,
                       outline_colour=outline_colour, alignment=5, margin_v=0)
            )
            events.extend(_pop_events(line, style_name, end_sec))
        elif layout.style == "build":
            styles.append(
                _style(style_name, layout.font_size,
                       primary=fill, secondary=accent,
                       outline_colour=outline_colour,
                       alignment=layout.alignment, margin_v=layout.margin_v)
            )
            events.extend(_build_events(line, style_name, end_sec, accent, layout.row_splits))
        else:  # sweep: text starts as fill and the accent sweeps through it
            styles.append(
                _style(style_name, layout.font_size,
                       primary=accent, secondary=fill,
                       outline_colour=outline_colour,
                       alignment=layout.alignment, margin_v=layout.margin_v)
            )
            events.extend(_sweep_events(line, style_name, end_sec, layout.row_splits))

    return build_ass_document(play_res=output_size, styles=styles, events=events)


class KineticLyrics(OverlaySkill):
    id = "lyrics.kinetic"
    kind = "lyrics"
    description = (
        "Word-synced kinetic lyrics burned over the whole reel: karaoke color "
        "sweeps, big word pops, or accumulating lines, with footage-adaptive "
        "placement and color. Selected via finish_edit's `lyrics` field."
    )
    params_model = KineticLyricsParams
    ffmpeg_supported = True
    wants_shot_stats = True
    singleton = True

    def ffmpeg_assets(self, overlay: ResolvedOverlay, ctx: RenderContext) -> dict[str, str]:
        params = self.params_model(**overlay.params)
        return {
            ASS_FILENAME: build_ass_for_overlay(
                params,
                shot_stats=ctx.shot_stats,
                output_size=ctx.output_size,
                duration_sec=overlay.timeline_end_sec,
            )
        }

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        if not ctx.asset_dir:
            raise ValueError("lyrics.kinetic requires ctx.asset_dir (skill assets not materialized)")
        ass_path = escape_drawtext_path(f"{ctx.asset_dir}/{ASS_FILENAME}")
        fragment = f"ass=filename={ass_path}"
        if ctx.fonts_dir:
            fragment += f":fontsdir={escape_drawtext_path(ctx.fonts_dir)}"
        return fragment

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        logger.info("lyrics.kinetic has no MoviePy path; skipping on fallback renderer")
        return []


register(KineticLyrics())
