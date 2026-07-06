"""Pure musicality helpers for the timeline adapter — the "rhythm engine".

Mirrors the credits.py / poster.py pure-decision pattern: no Modal, moviepy,
or numpy imports, so everything here is unit-testable without media. The
adapter composes these into its pipeline; constants are hand-tuned defaults
(reference-derived style profiles can parameterize them later).
"""

from bisect import bisect_left

from .timeline_schema import Shot, ShotSource, Transition

# Cuts land slightly BEFORE the beat: human editors cut ~1 frame early so the
# incoming shot is already visible when the beat hits (the ingested reference
# reels show a negative-median cut offset).
CUT_LEAD_SEC = 0.04

IMPACT_SHIFT_BUDGET_SEC = 0.75
IMPACT_ALIGN_TOLERANCE_SEC = 0.08
SOURCE_UNIQUENESS_SEC = 1.0

# Pacing backstop: only fast sections get shots force-split, and only when a
# shot overruns its band by this factor.
SPLIT_TRIGGER_FACTOR = 2.0
SPLIT_JUMP_SEC = 2.0
IMPACT_JUMP_MIN_SEC = 1.0
IMPACT_JUMP_MAX_SEC = 8.0
FAST_SECTION_LABELS = frozenset({"chorus", "drop"})

DEFAULT_TEMPO_BPM = 120.0
PACING_BANDS_BEATS = {
    "chorus": (2.0, 4.0),
    "drop": (2.0, 4.0),
    "verse": (4.0, 8.0),
    "bridge": (4.0, 8.0),
    "intro": (4.0, 8.0),
    "outro": (4.0, 8.0),
}
DEFAULT_PACING_BAND_BEATS = (3.0, 8.0)

# Sync-report windows: on-beat allows the lead plus ~1 frame of drift.
ON_BEAT_WINDOW_SEC = 0.05
ON_DOWNBEAT_WINDOW_SEC = 0.08


def _nearest(sorted_values: list[float], t: float) -> float | None:
    if not sorted_values:
        return None
    i = bisect_left(sorted_values, t)
    candidates = sorted_values[max(0, i - 1):i + 1]
    return min(candidates, key=lambda v: abs(v - t))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 3)


def _impact_frames(video: dict | None) -> list[tuple[float, float]]:
    """Flatten (timestamp_sec, intensity) impact frames from a video analysis."""
    frames: list[tuple[float, float]] = []
    for scene in (video or {}).get("scenes") or []:
        for frame in (scene.get("impacts") or {}).get("impact_frames") or []:
            try:
                frames.append(
                    (float(frame["timestamp_sec"]), float(frame.get("intensity", 0.0)))
                )
            except (KeyError, TypeError, ValueError):
                continue
    return frames


def _label_for(t: float, sections: list[dict]) -> str:
    for section in sections or []:
        try:
            if float(section["start_sec"]) <= t < float(section["end_sec"]):
                return str(section.get("label", "")).lower()
        except (KeyError, TypeError, ValueError):
            continue
    return ""


def pick_snap_beat(
    boundary: float,
    beats_sec: list[float],
    downbeats_sec: list[float],
    *,
    tolerance_sec: float = 0.15,
    lead_sec: float = CUT_LEAD_SEC,
) -> tuple[float, float] | None:
    """Choose the musical anchor for a cut boundary.

    Returns (target_position, anchor_beat) where target_position is the anchor
    minus the early-cut lead, or None when no anchor is within tolerance.
    A downbeat within tolerance always wins over a nearer plain beat.
    """
    for series in (downbeats_sec, beats_sec):
        values = sorted(v for v in (series or []) if v > 0)
        anchor = _nearest(values, boundary + lead_sec)
        if anchor is None:
            continue
        target = round(anchor - lead_sec, 3)
        if abs(target - boundary) <= tolerance_sec:
            return target, anchor
    return None


def pacing_bands_for(tempo_bpm: float | None) -> dict[str, tuple[float, float]]:
    """Per-section shot-duration bands in seconds, derived from the tempo."""
    bpm = float(tempo_bpm or 0.0)
    if bpm <= 0:
        bpm = DEFAULT_TEMPO_BPM
    spb = 60.0 / bpm
    bands = {
        label: (round(lo * spb, 3), round(hi * spb, 3))
        for label, (lo, hi) in PACING_BANDS_BEATS.items()
    }
    lo, hi = DEFAULT_PACING_BAND_BEATS
    bands["default"] = (round(lo * spb, 3), round(hi * spb, 3))
    return bands


def register_impacts_to_downbeats(
    shots: list[Shot],
    video: dict | None,
    downbeats_sec: list[float],
    *,
    effective_source_end: float,
    budget_sec: float = IMPACT_SHIFT_BUDGET_SEC,
    tolerance_sec: float = IMPACT_ALIGN_TOLERANCE_SEC,
    uniqueness_sec: float = SOURCE_UNIQUENESS_SEC,
) -> tuple[list[Shot], list[dict]]:
    """Shift shots' source windows so a visual impact lands on a musical downbeat.

    Timeline positions never move — only the source window slides (by at most
    `budget_sec`), so boundaries stay beat-snapped. The strongest impact wins.
    A shot whose impact already lands within `tolerance_sec` of a downbeat is
    recorded with shift 0. Shifts that would leave [0, effective_source_end]
    or come within `uniqueness_sec` of another shot's source start are skipped.
    """
    impacts = sorted(_impact_frames(video), key=lambda item: -item[1])
    downs = sorted(d for d in (downbeats_sec or []) if d >= 0)
    if not impacts or not downs:
        return shots, []

    out = list(shots)
    registrations: list[dict] = []
    for i, shot in enumerate(out):
        if shot.speed != 1.0:
            continue
        in_downs = [
            d for d in downs
            if shot.timeline_start_sec <= d < shot.timeline_end_sec - 0.05
        ]
        if not in_downs:
            continue
        src = shot.source
        chosen: tuple[float, float, float, float] | None = None
        for impact_ts, intensity in impacts:
            if not (src.start_sec - budget_sec <= impact_ts <= src.end_sec + budget_sec):
                continue
            landing = shot.timeline_start_sec + (impact_ts - src.start_sec)
            downbeat = min(in_downs, key=lambda d: abs(landing - d))
            delta = round(landing - downbeat, 3)
            if abs(delta) <= tolerance_sec:
                chosen = (impact_ts, downbeat, 0.0, intensity)
                break
            if abs(delta) > budget_sec:
                continue
            new_start = round(src.start_sec + delta, 3)
            new_end = round(src.end_sec + delta, 3)
            if new_start < 0 or new_end > effective_source_end:
                continue
            other_starts = [o.source.start_sec for j, o in enumerate(out) if j != i]
            if any(abs(new_start - other) <= uniqueness_sec for other in other_starts):
                continue
            chosen = (impact_ts, downbeat, delta, intensity)
            break
        if chosen is None:
            continue
        impact_ts, downbeat, delta, intensity = chosen
        if delta != 0.0:
            out[i] = shot.model_copy(update={
                "source": ShotSource(
                    start_sec=round(src.start_sec + delta, 3),
                    end_sec=round(src.end_sec + delta, 3),
                ),
            })
        registrations.append({
            "shot_index": shot.index,
            "impact_sec": round(impact_ts, 3),
            "downbeat_sec": round(downbeat, 3),
            "shift_sec": delta,
            "intensity": round(intensity, 3),
        })
    return out, registrations


def split_overlong_section_shots(
    shots: list[Shot],
    sections: list[dict],
    downbeats_sec: list[float],
    bands: dict[str, tuple[float, float]],
    *,
    video: dict | None = None,
    effective_source_end: float,
    uniqueness_sec: float = SOURCE_UNIQUENESS_SEC,
) -> tuple[list[Shot], list[dict]]:
    """Deterministic pacing backstop: split shots that badly overrun a fast
    section's duration band, cutting at downbeats.

    Later pieces jump their source window forward (next impact frame if one is
    within reach, else +SPLIT_JUMP_SEC) so the split reads as a real cut, not a
    seamless continuation. Any bounds/uniqueness violation aborts the whole
    split (the original shot is kept) — this is a backstop, not a rewrite.
    """
    downs = sorted(d for d in (downbeats_sec or []) if d >= 0)
    if not downs or not sections:
        return shots, []
    impact_times = sorted(ts for ts, _ in _impact_frames(video)) if video else []

    out: list[Shot] = []
    records: list[dict] = []
    all_starts = [s.source.start_sec for s in shots]
    for shot in shots:
        midpoint = (shot.timeline_start_sec + shot.timeline_end_sec) / 2.0
        label = _label_for(midpoint, sections)
        band = bands.get(label)
        if (
            label not in FAST_SECTION_LABELS
            or band is None
            or shot.speed != 1.0
            or shot.effects
        ):
            out.append(shot)
            continue
        band_lo, band_hi = band
        if shot.duration_sec <= SPLIT_TRIGGER_FACTOR * band_hi:
            out.append(shot)
            continue

        cuts: list[float] = []
        piece_start = shot.timeline_start_sec
        while True:
            window = [
                d for d in downs
                if piece_start + band_lo < d <= piece_start + band_hi
                and shot.timeline_end_sec - d >= band_lo
            ]
            if not window:
                break
            cuts.append(window[-1])
            piece_start = window[-1]
        if not cuts:
            out.append(shot)
            continue

        boundaries = [shot.timeline_start_sec] + cuts + [shot.timeline_end_sec]
        pieces: list[Shot] = []
        aborted = False
        for k in range(len(boundaries) - 1):
            t0, t1 = boundaries[k], boundaries[k + 1]
            duration = round(t1 - t0, 3)
            if k == 0:
                src_start = shot.source.start_sec
            else:
                origin = shot.source.start_sec + (t0 - shot.timeline_start_sec)
                candidates = [
                    ts for ts in impact_times
                    if origin + IMPACT_JUMP_MIN_SEC < ts <= origin + IMPACT_JUMP_MAX_SEC
                ][:1] + [round(origin + SPLIT_JUMP_SEC, 3)]
                src_start = None
                for candidate in candidates:
                    if candidate < 0 or candidate + duration > effective_source_end:
                        continue
                    taken = (
                        [x for x in all_starts if x != shot.source.start_sec]
                        + [p.source.start_sec for p in pieces]
                    )
                    if any(abs(candidate - other) <= uniqueness_sec for other in taken):
                        continue
                    src_start = candidate
                    break
                if src_start is None:
                    aborted = True
                    break
            pieces.append(Shot(
                index=shot.index,
                timeline_start_sec=round(t0, 3),
                timeline_end_sec=round(t1, 3),
                source=ShotSource(
                    start_sec=round(src_start, 3),
                    end_sec=round(src_start + duration, 3),
                ),
                speed=shot.speed,
                transition_in=shot.transition_in if k == 0 else Transition(),
            ))
        if aborted:
            out.append(shot)
            continue
        out.extend(pieces)
        records.append({
            "shot_index": shot.index,
            "pieces": len(pieces),
            "cut_at_sec": [round(c, 3) for c in cuts],
        })

    if records:
        out = [s.model_copy(update={"index": i}) for i, s in enumerate(out)]
    return out, records


ACCENT_PRE_SEC = 0.05
ACCENT_POST_SEC = 0.40
MAX_AUTO_ACCENTS = 2


def auto_accent_overlays(
    registrations: list[dict],
    duration_sec: float,
    *,
    max_accents: int = MAX_AUTO_ACCENTS,
) -> list[dict]:
    """Deterministic accent floor: shake windows on the strongest registered
    impact+downbeat coincidences, as raw overlay dicts for the adapter's
    normal overlay resolution. Used only when the agent placed no moment
    skills itself."""
    ranked = sorted(registrations, key=lambda r: -(r.get("intensity") or 0.0))
    accents: list[dict] = []
    for reg in ranked[:max_accents]:
        downbeat = float(reg["downbeat_sec"])
        start = max(0.0, round(downbeat - ACCENT_PRE_SEC, 3))
        end = min(float(duration_sec), round(downbeat + ACCENT_POST_SEC, 3))
        if end - start <= 0:
            continue
        accents.append({"skill_id": "impact.shake", "start_time": start, "end_time": end})
    return accents


def sync_report(shots: list[Shot], song: dict, video: dict | None) -> dict:
    """JSON-safe musicality summary of a final shot list (telemetry, not control)."""
    beats = sorted(b for b in (song.get("beats_sec") or []) if b > 0)
    downs = sorted(d for d in (song.get("downbeats_sec") or []) if d >= 0)
    interior = [s.timeline_start_sec for s in shots[1:]]

    offsets: list[float] = []
    on_beat = 0
    on_downbeat = 0
    for t in interior:
        nearest_beat = _nearest(beats, t)
        if nearest_beat is not None:
            offsets.append(round(t - nearest_beat, 3))
            if abs(t - nearest_beat) <= ON_BEAT_WINDOW_SEC:
                on_beat += 1
        nearest_down = _nearest(downs, t)
        if nearest_down is not None and abs(t - nearest_down) <= ON_DOWNBEAT_WINDOW_SEC:
            on_downbeat += 1

    impact_times = [ts for ts, _ in _impact_frames(video)]
    impact_shots = 0
    for shot in shots:
        for ts in impact_times:
            if shot.source.start_sec <= ts <= shot.source.end_sec:
                landing = shot.timeline_start_sec + (ts - shot.source.start_sec)
                nearest_down = _nearest(downs, landing)
                if (
                    nearest_down is not None
                    and abs(landing - nearest_down) <= IMPACT_ALIGN_TOLERANCE_SEC
                ):
                    impact_shots += 1
                    break

    bands = pacing_bands_for(song.get("tempo_bpm"))
    durations_by_label: dict[str, list[float]] = {}
    for shot in shots:
        midpoint = (shot.timeline_start_sec + shot.timeline_end_sec) / 2.0
        label = _label_for(midpoint, song.get("segments") or [])
        if label:
            durations_by_label.setdefault(label, []).append(shot.duration_sec)
    sections_out = {}
    for label, durations in durations_by_label.items():
        band = bands.get(label, bands["default"])
        within = sum(1 for d in durations if band[0] <= d <= band[1])
        sections_out[label] = {
            "mean_shot_sec": round(sum(durations) / len(durations), 3),
            "band_sec": [band[0], band[1]],
            "within_band_pct": round(100.0 * within / len(durations), 1),
        }

    n = len(interior)
    return {
        "interior_cut_count": n,
        "cuts_on_beat_pct": round(100.0 * on_beat / n, 1) if n else 0.0,
        "cuts_on_downbeat_pct": round(100.0 * on_downbeat / n, 1) if n else 0.0,
        "cut_offset_median_sec": _median(offsets),
        "impact_on_downbeat_shots": impact_shots,
        "shot_count": len(shots),
        "sections": sections_out,
    }
