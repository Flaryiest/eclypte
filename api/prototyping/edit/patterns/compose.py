from .registry import by_id, filter_applicable
from .schema import Pattern


def pick_macro(patterns: list[Pattern], *, bpm: float) -> Pattern | None:
    candidates = filter_applicable(patterns, layer="macro", bpm=bpm)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.weight)


def pick_meso_for_section(
    patterns: list[Pattern],
    *,
    section_label: str,
    avg_energy: float,
    bpm: float,
) -> Pattern | None:
    candidates = filter_applicable(
        patterns,
        layer="meso",
        section_label=section_label,
        energy=avg_energy,
        bpm=bpm,
    )
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.weight)


def expand_micro(
    patterns: list[Pattern],
    meso: Pattern,
    *,
    section_label: str,
    avg_energy: float,
    bpm: float,
) -> list[Pattern]:
    required_ids = set(meso.composes_with.requires)
    forbidden_ids = set(meso.composes_with.forbids)
    pool = filter_applicable(
        patterns,
        section_label=section_label,
        energy=avg_energy,
        bpm=bpm,
    )
    chosen: list[Pattern] = []
    for p in pool:
        if p.layer not in ("micro", "transition", "shot_move"):
            continue
        if p.id in forbidden_ids:
            continue
        if required_ids and p.id not in required_ids:
            continue
        chosen.append(p)

    for rid in required_ids:
        if not any(c.id == rid for c in chosen):
            try:
                chosen.append(by_id(patterns, rid))
            except KeyError:
                pass
    return chosen
