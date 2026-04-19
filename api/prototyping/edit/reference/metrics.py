"""
Pure metrics derived from (music_analysis, video_analysis) pair.

A viral AMV's video-analysis `scenes[i].start_sec` for i >= 1 are the
editor's cut timestamps (the very first scene start = 0 is not a cut).
Cross-referencing those cuts with the music analysis' downbeats and
segment labels gives us the behavioural ground truth used by consolidate
to propose pattern weight multipliers.

No Modal, no LLM, no numpy — pure Python so this is trivially testable.
"""
from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict

HIST_OFFSET_LO = -0.5
HIST_OFFSET_HI = 0.5
HIST_OFFSET_BINS = 20
HIST_MOTION_BINS = 10
HIST_LAG_LO = -0.5
HIST_LAG_HI = 0.5
HIST_LAG_BINS = 20


def compute_metrics(music: dict, video: dict) -> dict:
    downbeats = [float(d) for d in music.get("downbeats_sec") or []]
    segments = list(music.get("segments") or [])
    scenes = list(video.get("scenes") or [])

    cut_times = [float(s["start_sec"]) for s in scenes[1:]]

    return {
        "n_cuts": len(cut_times),
        "n_scenes": len(scenes),
        "n_downbeats": len(downbeats),
        "cut_offsets_to_downbeats": cut_offsets_to_downbeats(cut_times, downbeats),
        "cut_density_per_section": cut_density_per_section(cut_times, segments, downbeats),
        "motion_at_cuts": motion_at_cuts(scenes),
        "impact_to_cut_lag": impact_to_cut_lag(scenes, cut_times),
        "shot_duration_per_section": shot_duration_distribution_per_section(scenes, segments),
    }


def cut_offsets_to_downbeats(cut_times: list[float], downbeats: list[float]) -> dict:
    if not cut_times or not downbeats:
        return _empty_distribution(HIST_OFFSET_LO, HIST_OFFSET_HI, HIST_OFFSET_BINS)

    sorted_db = sorted(downbeats)
    offsets: list[float] = []
    for t in cut_times:
        nearest = _nearest(sorted_db, t)
        offsets.append(t - nearest)

    return _summary(offsets, HIST_OFFSET_LO, HIST_OFFSET_HI, HIST_OFFSET_BINS)


def cut_density_per_section(
    cut_times: list[float],
    segments: list[dict],
    downbeats: list[float],
) -> dict:
    out: dict[str, dict] = {}
    grouped: dict[str, list] = defaultdict(list)
    for seg in segments:
        label = str(seg.get("label", "unknown"))
        start = float(seg["start_sec"])
        end = float(seg["end_sec"])
        cuts_in = sum(1 for t in cut_times if start <= t < end)
        downbeats_in = sum(1 for d in downbeats if start <= d < end)
        duration = max(0.0, end - start)
        grouped[label].append((cuts_in, downbeats_in, duration))

    for label, rows in grouped.items():
        total_cuts = sum(r[0] for r in rows)
        total_db = sum(r[1] for r in rows)
        total_dur = sum(r[2] for r in rows)
        out[label] = {
            "cuts": total_cuts,
            "downbeats": total_db,
            "duration_sec": round(total_dur, 3),
            "cuts_per_downbeat": round(total_cuts / total_db, 4) if total_db > 0 else None,
            "cuts_per_sec": round(total_cuts / total_dur, 4) if total_dur > 0 else None,
        }
    return out


def motion_at_cuts(scenes: list[dict]) -> dict:
    if len(scenes) < 2:
        return _empty_distribution(0.0, 1.0, HIST_MOTION_BINS)

    values: list[float] = []
    for i in range(1, len(scenes)):
        prev_avg = float(scenes[i - 1].get("motion", {}).get("avg_intensity", 0.0))
        next_avg = float(scenes[i].get("motion", {}).get("avg_intensity", 0.0))
        values.append((prev_avg + next_avg) / 2.0)

    return _summary(values, 0.0, 1.0, HIST_MOTION_BINS)


def impact_to_cut_lag(scenes: list[dict], cut_times: list[float]) -> dict:
    if not cut_times:
        return _empty_distribution(HIST_LAG_LO, HIST_LAG_HI, HIST_LAG_BINS)

    sorted_cuts = sorted(cut_times)
    lags: list[float] = []
    for scene in scenes:
        for imp in (scene.get("impacts") or {}).get("impact_frames") or []:
            ts = float(imp.get("timestamp_sec", 0.0))
            nearest = _nearest(sorted_cuts, ts)
            lags.append(nearest - ts)

    if not lags:
        return _empty_distribution(HIST_LAG_LO, HIST_LAG_HI, HIST_LAG_BINS)
    return _summary(lags, HIST_LAG_LO, HIST_LAG_HI, HIST_LAG_BINS)


def shot_duration_distribution_per_section(
    scenes: list[dict],
    segments: list[dict],
) -> dict:
    grouped: dict[str, list[float]] = defaultdict(list)
    for sc in scenes:
        center = (float(sc["start_sec"]) + float(sc["end_sec"])) / 2.0
        label = _label_for(center, segments)
        grouped[label].append(float(sc["duration_sec"]))

    out: dict[str, dict] = {}
    for label, values in grouped.items():
        out[label] = {
            "count": len(values),
            "mean": round(statistics.fmean(values), 4) if values else 0.0,
            "median": round(statistics.median(values), 4) if values else 0.0,
            "stdev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
            "min": round(min(values), 4) if values else 0.0,
            "max": round(max(values), 4) if values else 0.0,
        }
    return out


def _label_for(t: float, segments: list[dict]) -> str:
    for seg in segments:
        if float(seg["start_sec"]) <= t < float(seg["end_sec"]):
            return str(seg.get("label", "unknown"))
    return "unknown"


def _nearest(sorted_values: list[float], t: float) -> float:
    idx = bisect.bisect_left(sorted_values, t)
    if idx == 0:
        return sorted_values[0]
    if idx == len(sorted_values):
        return sorted_values[-1]
    before = sorted_values[idx - 1]
    after = sorted_values[idx]
    return before if (t - before) <= (after - t) else after


def _summary(values: list[float], lo: float, hi: float, bins: int) -> dict:
    if not values:
        return _empty_distribution(lo, hi, bins)
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p25": round(_percentile(ordered, 0.25), 4),
        "p75": round(_percentile(ordered, 0.75), 4),
        "stdev": round(statistics.pstdev(ordered), 4) if n > 1 else 0.0,
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
        "histogram": _histogram(ordered, lo, hi, bins),
    }


def _empty_distribution(lo: float, hi: float, bins: int) -> dict:
    return {
        "n": 0,
        "mean": 0.0,
        "median": 0.0,
        "p25": 0.0,
        "p75": 0.0,
        "stdev": 0.0,
        "min": 0.0,
        "max": 0.0,
        "histogram": {
            "bin_edges": [round(lo + (hi - lo) * i / bins, 4) for i in range(bins + 1)],
            "counts": [0] * bins,
        },
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    lo_i = int(math.floor(pos))
    hi_i = int(math.ceil(pos))
    if lo_i == hi_i:
        return sorted_values[lo_i]
    frac = pos - lo_i
    return sorted_values[lo_i] + frac * (sorted_values[hi_i] - sorted_values[lo_i])


def _histogram(values: list[float], lo: float, hi: float, bins: int) -> dict:
    counts = [0] * bins
    width = (hi - lo) / bins
    for v in values:
        if v < lo:
            counts[0] += 1
        elif v >= hi:
            counts[-1] += 1
        else:
            idx = int((v - lo) / width)
            if idx >= bins:
                idx = bins - 1
            counts[idx] += 1
    return {
        "bin_edges": [round(lo + width * i, 4) for i in range(bins + 1)],
        "counts": counts,
    }
