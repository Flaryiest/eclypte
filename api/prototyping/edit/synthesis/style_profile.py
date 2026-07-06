"""Reference-derived style profiles.

Turns completed synthesis-reference metrics (how human editors cut viral
reels against their music — see reference/metrics.py) into overrides for the
rhythm engine: the early-cut lead and per-section pacing bands. Derived at
plan time from whatever references exist; nothing is persisted, so newly
ingested references shape the very next edit.

Pure module (no storage/Modal imports) — mirrors rhythm.py's testability.
"""
from __future__ import annotations

from .rhythm import _median

MAX_LEAD_SEC = 0.08
BEATS_PER_BAR = 4.0  # downbeat spacing assumed one bar
BAND_LO_FACTOR = 0.6
BAND_HI_FACTOR = 1.4
MIN_BAND_BEATS = 1.0
MAX_BAND_BEATS = 16.0


def derive_style_profile(metrics_list: list[dict]) -> dict:
    """Aggregate reference metrics into rhythm-engine overrides.

    Returns a dict with any of:
      - "cut_lead_sec": median of the references' cut-before-downbeat leads,
        clamped to [0, MAX_LEAD_SEC];
      - "pacing_bands_beats": {section label: (lo, hi) beats per shot} from
        the median cuts_per_downbeat per label;
      - "reference_count": how many references contributed.
    Keys are omitted when underivable; an empty dict means "no profile".
    """
    leads: list[float] = []
    beats_per_shot: dict[str, list[float]] = {}
    contributing: set[int] = set()

    for idx, metrics in enumerate(metrics_list or []):
        if not isinstance(metrics, dict):
            continue
        offsets = metrics.get("cut_offsets_to_downbeats")
        if isinstance(offsets, dict):
            median = offsets.get("median")
            if isinstance(median, (int, float)):
                # negative offsets (cut before the beat) become a positive lead
                leads.append(-float(median))
                contributing.add(idx)
        densities = metrics.get("cut_density_per_section")
        if isinstance(densities, dict):
            for label, stats in densities.items():
                if not isinstance(stats, dict):
                    continue
                cpd = stats.get("cuts_per_downbeat")
                if isinstance(cpd, (int, float)) and cpd > 0:
                    beats_per_shot.setdefault(str(label).lower(), []).append(
                        BEATS_PER_BAR / float(cpd)
                    )
                    contributing.add(idx)

    profile: dict = {}
    if leads:
        profile["cut_lead_sec"] = round(min(max(_median(leads), 0.0), MAX_LEAD_SEC), 3)
    bands = {}
    for label, values in beats_per_shot.items():
        median_beats = _median(values)
        bands[label] = (
            round(max(MIN_BAND_BEATS, BAND_LO_FACTOR * median_beats), 3),
            round(min(MAX_BAND_BEATS, BAND_HI_FACTOR * median_beats), 3),
        )
    if bands:
        profile["pacing_bands_beats"] = bands
    if profile:
        profile["reference_count"] = len(contributing)
    return profile
