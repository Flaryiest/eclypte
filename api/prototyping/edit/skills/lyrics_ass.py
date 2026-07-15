"""Pure ASS (Advanced SubStation Alpha) document serializer for kinetic lyrics.

String building only — no I/O, no heavy imports — so the whole karaoke/timing
math is unit-testable. Consumed by ``lyrics_kinetic.build_ass_for_overlay``;
the render executor writes the returned document next to the ffmpeg process.

ASS gotchas encoded here:
- colors are ``&HAABBGGRR`` (alpha first, BGR byte order; alpha 00 = opaque)
- timestamps are ``H:MM:SS.CC`` (centiseconds)
- ``\\kf`` karaoke durations are centiseconds and advance a cumulative clock,
  so a textless ``{\\kf N}`` is a timing gap (vocal pause) with nothing swept
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

# A real override block contains backslash tags ({\b1}); stray braces in a
# lyric word (he{y}) are just junk punctuation to strip, keeping the letters.
_OVERRIDE_BLOCK_RE = re.compile(r"\{\\[^}]*\}")


def ass_color(hex_rgb: str, alpha: float = 0.0) -> str:
    """``#RRGGBB`` (+ 0..1 transparency) -> ``&HAABBGGRR``."""
    rgb = hex_rgb.lstrip("#")
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    aa = round(max(0.0, min(1.0, alpha)) * 255)
    return f"&H{aa:02X}{b.upper()}{g.upper()}{r.upper()}"


def ass_timestamp(sec: float) -> str:
    """Seconds -> ``H:MM:SS.CC``, rounding to centiseconds with carry."""
    total_cs = max(0, round(sec * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def sanitize_ass_text(text: str) -> str:
    """Neutralize ASS override syntax: ``{...}`` blocks are dropped whole
    (their contents are tags, not lyric words); stray braces and ``\\``
    controls are stripped."""
    cleaned = _OVERRIDE_BLOCK_RE.sub("", text)
    cleaned = cleaned.replace("{", "").replace("}", "").replace("\\", "")
    return " ".join(cleaned.split())


def kf_line_text(
    words: Sequence[Mapping],
    line_start_sec: float,
    row_breaks: frozenset[int] | set[int] = frozenset(),
) -> str:
    """Karaoke-fill text for one line: ``{\\kf<cs>}word`` runs.

    Durations come from differences of cumulatively rounded centisecond
    boundaries, so the karaoke clock total exactly spans first-word start to
    last-word end (per-word rounding would drift up to 1cs per word). Vocal
    pauses become bare textless ``{\\kf}`` tags. A word index in
    ``row_breaks`` starts a new visual row: its separator is a hard ``\\N``
    line break instead of a space (the layout pre-wraps; WrapStyle 2)."""
    parts: list[str] = []
    cursor_cs = 0
    last = len(words) - 1
    for i, word in enumerate(words):
        start_cs = round((float(word["start_sec"]) - line_start_sec) * 100)
        end_cs = round((float(word["end_sec"]) - line_start_sec) * 100)
        gap = start_cs - cursor_cs
        if gap > 0:
            parts.append(f"{{\\kf{gap}}}")
        duration = max(0, end_cs - max(start_cs, cursor_cs))
        clean = sanitize_ass_text(str(word["text"]))
        if clean:
            if i == last:
                trailing = ""
            elif (i + 1) in row_breaks:
                trailing = "\\N"
            else:
                trailing = " "
            parts.append(f"{{\\kf{duration}}}{clean}{trailing}")
        elif duration > 0:
            parts.append(f"{{\\kf{duration}}}")
        cursor_cs = max(cursor_cs, end_cs)
    return "".join(parts)


@dataclass(frozen=True)
class AssStyle:
    name: str
    fontname: str
    fontsize: int
    primary: str          # fill (post-sweep color for \kf)
    secondary: str        # pre-sweep color for \kf
    outline_colour: str
    back_colour: str
    bold: bool = False
    outline: float = 3.0
    shadow: float = 0.0
    spacing: float = 0.0  # letter-spacing (tracking) in px
    alignment: int = 2    # numpad: 2 = bottom-center, 5 = middle-center, 8 = top-center
    margin_l: int = 60
    margin_r: int = 60
    margin_v: int = 120


@dataclass(frozen=True)
class AssEvent:
    start_sec: float
    end_sec: float
    style_name: str
    text: str             # pre-tagged (already sanitized/karaoke'd by the caller)
    layer: int = 0


_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def _style_line(style: AssStyle) -> str:
    return (
        f"Style: {style.name},{style.fontname},{style.fontsize},"
        f"{style.primary},{style.secondary},{style.outline_colour},{style.back_colour},"
        f"{-1 if style.bold else 0},0,0,0,100,100,{style.spacing:g},0,1,"
        f"{style.outline},{style.shadow},{style.alignment},"
        f"{style.margin_l},{style.margin_r},{style.margin_v},1"
    )


def _event_line(event: AssEvent) -> str:
    return (
        f"Dialogue: {event.layer},{ass_timestamp(event.start_sec)},"
        f"{ass_timestamp(event.end_sec)},{event.style_name},,0,0,0,,{event.text}"
    )


def build_ass_document(
    *,
    play_res: tuple[int, int],
    styles: Sequence[AssStyle],
    events: Sequence[AssEvent],
) -> str:
    """Assemble a complete .ass document (PlayRes matched to the output size,
    WrapStyle 2 — the layout module pre-fits lines, libass must not re-wrap)."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res[0]}",
        f"PlayResY: {play_res[1]}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        *[_style_line(s) for s in styles],
        "",
        "[Events]",
        _EVENT_FORMAT,
        *[_event_line(e) for e in events],
    ]
    return "\n".join(lines) + "\n"
