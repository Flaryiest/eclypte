"""
Parse the `## Weighted Annotations` H2 section of references.md into a
{pattern_id: weight_multiplier} dict for the planner.

Tolerant by design: unknown ids logged and dropped, malformed lines
skipped, missing/empty section returns {}. Multipliers clamped to
[MIN_MULT, MAX_MULT] so the planner's `max(weight)` selection stays
well-behaved.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

MIN_MULT = 0.5
MAX_MULT = 1.5

_SECTION_HEADER = "## Weighted Annotations"
_LINE = re.compile(
    r"^- (?P<pid>[a-z_]+\.[a-z0-9_]+): weight_multiplier=(?P<w>\d+\.\d+)"
)


def parse_annotations(
    md_path: Path,
    *,
    known_pattern_ids: set[str],
) -> dict[str, float]:
    md_path = Path(md_path)
    if not md_path.exists():
        return {}

    text = md_path.read_text(encoding="utf-8")
    section = _extract_section(text, _SECTION_HEADER)
    if not section.strip():
        return {}

    out: dict[str, float] = {}
    for line in section.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        pid = m.group("pid")
        try:
            raw = float(m.group("w"))
        except ValueError:
            continue

        if pid not in known_pattern_ids:
            log.warning("annotation references unknown pattern_id %r; dropping", pid)
            continue

        clamped = max(MIN_MULT, min(MAX_MULT, raw))
        if clamped != raw:
            log.warning(
                "clamped weight_multiplier for %s: %.4f → %.4f (bounds [%.2f, %.2f])",
                pid, raw, clamped, MIN_MULT, MAX_MULT,
            )
        out[pid] = clamped

    return out


def _extract_section(text: str, header: str) -> str:
    start = text.find(header)
    if start < 0:
        return ""
    start = text.find("\n", start) + 1
    rest = text[start:]
    next_h2 = re.search(r"^## ", rest, flags=re.MULTILINE)
    if next_h2:
        return rest[: next_h2.start()]
    return rest
