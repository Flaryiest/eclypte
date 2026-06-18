"""LRC parsing + windowed lyric-overlay expansion (pure, control-plane safe).

`parse_lrc` turns a synced-lyrics LRC string into ascending `(start_sec, text)`
lines. `expand_lyrics_overlays` offsets/clips those lines into the trimmed audio
window and emits `text.lyric` overlay dicts ready for `adapt(overlays=...)`.
No moviepy/heavy imports.
"""
from __future__ import annotations

import re

# [mm:ss] / [mm:ss.xx] / [mm:ss.xxx] — minutes 1-3 digits, fractional 1-3 digits.
_TS_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")

LYRIC_SKILL_ID = "text.lyric"
DEFAULT_MAX_LINE_SEC = 5.0


def parse_lrc(lrc: str | None) -> list[tuple[float, str]]:
    """Parse an LRC string into ascending `[(start_sec, line_text)]`.

    Lines without a timestamp (metadata like `[ar:...]`/`[ti:...]`) and lines with
    empty text are skipped. A line with multiple timestamps expands to one entry
    per timestamp. Exact `(time, text)` duplicates are removed.
    """
    if not lrc:
        return []

    entries: list[tuple[float, str]] = []
    for line in lrc.splitlines():
        stamps = list(_TS_RE.finditer(line))
        if not stamps:
            continue
        text = line[stamps[-1].end():].strip()
        if not text:
            continue
        for m in stamps:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            frac = m.group(3)
            total = minutes * 60 + seconds
            if frac:
                total += int(frac) / (10 ** len(frac))
            entries.append((round(total, 3), text))

    entries.sort(key=lambda pair: pair[0])
    deduped: list[tuple[float, str]] = []
    seen: set[tuple[float, str]] = set()
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped


def expand_lyrics_overlays(
    lines: list[tuple[float, str]],
    audio_start_sec: float,
    audio_end_sec: float | None,
    *,
    max_line_sec: float = DEFAULT_MAX_LINE_SEC,
) -> list[dict]:
    """Emit `text.lyric` overlay dicts for lyric lines inside the audio window.

    Each line whose start falls in `[audio_start_sec, audio_end_sec)` becomes one
    overlay, timed relative to the window start and ending at the earliest of: the
    next line, `max_line_sec`, or the window end.
    """
    start_bound = float(audio_start_sec)
    end_bound = float("inf") if audio_end_sec is None else float(audio_end_sec)

    overlays: list[dict] = []
    count = len(lines)
    for i, (line_start, text) in enumerate(lines):
        if not (start_bound <= line_start < end_bound):
            continue
        next_start = lines[i + 1][0] if i + 1 < count else float("inf")
        line_end = min(next_start, line_start + max_line_sec, end_bound)
        timeline_start = line_start - start_bound
        timeline_end = line_end - start_bound
        if timeline_end - timeline_start <= 0:
            continue
        overlays.append(
            {
                "skill_id": LYRIC_SKILL_ID,
                "text": text,
                "start_time": round(timeline_start, 3),
                "end_time": round(timeline_end, 3),
            }
        )
    return overlays
