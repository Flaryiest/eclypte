from pathlib import Path

import yaml

from .schema import Layer, Pattern

DEFAULT_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent / "knowledge" / "patterns.yaml"
)


def load(path: Path | str | None = None) -> list[Pattern]:
    p = Path(path) if path else DEFAULT_PATTERNS_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [Pattern.model_validate(item) for item in raw]


def by_id(patterns: list[Pattern], pattern_id: str) -> Pattern:
    for p in patterns:
        if p.id == pattern_id:
            return p
    raise KeyError(f"no pattern with id={pattern_id!r}")


def filter_applicable(
    patterns: list[Pattern],
    *,
    layer: Layer | None = None,
    section_label: str | None = None,
    energy: float | None = None,
    bpm: float | None = None,
    motion_intensity: float | None = None,
    camera_movement: str | None = None,
) -> list[Pattern]:
    out: list[Pattern] = []
    for p in patterns:
        if layer is not None and p.layer != layer:
            continue
        aw = p.applies_when
        if section_label is not None and aw.section_labels:
            if section_label not in aw.section_labels:
                continue
        if energy is not None and energy < aw.min_energy:
            continue
        if bpm is not None:
            lo, hi = aw.tempo_range_bpm
            if not (lo <= bpm <= hi):
                continue
        if motion_intensity is not None:
            lo, hi = aw.motion_intensity
            if not (lo <= motion_intensity <= hi):
                continue
        if camera_movement is not None and aw.camera_movements:
            if camera_movement not in aw.camera_movements:
                continue
        out.append(p)
    return out


def ids(patterns: list[Pattern]) -> set[str]:
    return {p.id for p in patterns}
