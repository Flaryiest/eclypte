import numpy as np

IMPACT_THRESHOLD_K = 3.0
MIN_IMPACT_INTENSITY = 0.15
COMBINED_IMPACT_WINDOW_FRAMES = 1
STILLNESS_HIGH = 0.60
STILLNESS_LOW = 0.10
VISUAL_ENERGY_FRAME_DIFF_WEIGHT = 0.5
VISUAL_ENERGY_FLOW_WEIGHT = 0.5
IMPACT_RADIAL_RATIO = 0.55


def impacts_per_scene(scene, motion, fps_hz):
    start_sec = scene[0]
    motion_curve = motion["motion_curve"]
    frame_diffs_raw = motion["_frame_diffs_raw"]
    flow_vx = motion["_flow_mean_vx"]
    flow_vy = motion["_flow_mean_vy"]
    flow_radial = motion["_flow_radial"]

    if len(motion_curve) < 2:
        return _empty_impacts(fps_hz)

    frame_diff_norm = _normalize(frame_diffs_raw)

    flow_peaks = _detect_peaks(motion_curve)
    flash_peaks = _detect_peaks(frame_diff_norm)

    impacts = _build_impacts(
        flow_peaks, flash_peaks, motion_curve, frame_diff_norm,
        flow_vx, flow_vy, flow_radial, start_sec, fps_hz,
    )
    stillness = _stillness_points(motion_curve, start_sec, fps_hz)
    visual_energy = _visual_energy(frame_diff_norm, motion_curve)

    return {
        "impact_frames": impacts,
        "stillness_points": stillness,
        "visual_energy": {
            "rate_hz": round(float(fps_hz), 3),
            "values": [round(float(v), 4) for v in visual_energy],
        },
    }


def _normalize(values):
    if not values:
        return []
    arr = np.asarray(values, dtype=np.float64)
    ref = float(arr.max())
    if ref <= 0:
        return [0.0] * len(values)
    return (arr / ref).tolist()


def _detect_peaks(signal):
    if len(signal) < 2:
        return []
    arr = np.asarray(signal, dtype=np.float64)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    threshold = med + IMPACT_THRESHOLD_K * mad
    if threshold <= 0 or mad == 0:
        return []

    peaks = []
    above = arr > threshold
    i = 0
    n = len(arr)
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            run = arr[i:j]
            peak_local = int(np.argmax(run))
            peaks.append((i + peak_local, j - i))
            i = j
        else:
            i += 1
    return peaks


def _build_impacts(flow_peaks, flash_peaks, motion_curve, frame_diff_norm,
                   flow_vx, flow_vy, flow_radial, start_sec, fps_hz):
    results = []
    flash_indices = [p[0] for p in flash_peaks]
    used_flash = set()

    for idx, dur in flow_peaks:
        intensity = motion_curve[idx]
        if intensity < MIN_IMPACT_INTENSITY:
            continue
        nearby_flash = _nearest_within_window(idx, flash_indices, COMBINED_IMPACT_WINDOW_FRAMES)
        direction = _classify_direction(flow_vx[idx], flow_vy[idx], flow_radial[idx])
        if nearby_flash is not None:
            impact_type = "combined"
            used_flash.add(nearby_flash)
        else:
            impact_type = "motion_spike"
        results.append({
            "timestamp_sec": round(start_sec + (idx + 1) / fps_hz, 3),
            "intensity": round(float(intensity), 4),
            "type": impact_type,
            "direction": direction,
            "duration_frames": int(dur),
        })

    for idx, dur in flash_peaks:
        if idx in used_flash:
            continue
        intensity = frame_diff_norm[idx]
        if intensity < MIN_IMPACT_INTENSITY:
            continue
        results.append({
            "timestamp_sec": round(start_sec + (idx + 1) / fps_hz, 3),
            "intensity": round(float(intensity), 4),
            "type": "flash",
            "direction": None,
            "duration_frames": int(dur),
        })

    results.sort(key=lambda r: r["timestamp_sec"])
    return results


def _nearest_within_window(idx, candidates, window):
    best = None
    best_dist = window + 1
    for c in candidates:
        d = abs(c - idx)
        if d <= window and d < best_dist:
            best = c
            best_dist = d
    return best


def _classify_direction(vx, vy, radial_ratio):
    if radial_ratio > IMPACT_RADIAL_RATIO:
        return "radial"
    return "horizontal" if abs(vx) >= abs(vy) else "vertical"


def _stillness_points(motion_curve, start_sec, fps_hz):
    points = []
    for i in range(1, len(motion_curve)):
        if motion_curve[i - 1] > STILLNESS_HIGH and motion_curve[i] < STILLNESS_LOW:
            points.append({
                "timestamp_sec": round(start_sec + (i + 1) / fps_hz, 3),
                "preceding_motion_intensity": round(float(motion_curve[i - 1]), 4),
            })
    return points


def _visual_energy(frame_diff_norm, motion_curve):
    n = len(motion_curve)
    if n == 0:
        return []
    fused = np.empty(n, dtype=np.float64)
    for i in range(n):
        fd = frame_diff_norm[i] if i < len(frame_diff_norm) else 0.0
        fused[i] = VISUAL_ENERGY_FRAME_DIFF_WEIGHT * fd + VISUAL_ENERGY_FLOW_WEIGHT * motion_curve[i]
    peak = float(fused.max())
    if peak > 0:
        fused = fused / peak
    return fused.tolist()


def _empty_impacts(fps_hz):
    return {
        "impact_frames": [],
        "stillness_points": [],
        "visual_energy": {
            "rate_hz": round(float(fps_hz), 3),
            "values": [],
        },
    }
