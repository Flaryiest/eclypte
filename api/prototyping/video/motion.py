import cv2
import numpy as np

FLOW_DOWNSAMPLE_WIDTH = 640
STATIC_FLOW_MAG = 0.15
WHIP_PAN_FLOW_MAG = 8.0
PAN_DIRECTION_CONSISTENCY = 0.70
RADIAL_RATIO = 0.55
FLOW_NORM_PERCENTILE = 95


def motion_per_scene(video_path, scene, fps_hz):
    start_sec, end_sec = scene
    start_frame = int(round(start_sec * fps_hz))
    end_frame = int(round(end_sec * fps_hz))

    mags, vxs, vys, rads, diffs = [], [], [], [], []
    prev = None
    for gray in _iter_gray_small(video_path, start_frame, end_frame):
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            m, vx, vy, rad = flow_stats(flow)
            mags.append(m)
            vxs.append(vx)
            vys.append(vy)
            rads.append(rad)
            diffs.append(float(np.mean(np.abs(gray.astype(np.int16) - prev.astype(np.int16)))))
        prev = gray

    return build_motion_dict(mags, vxs, vys, rads, diffs, start_sec, fps_hz)


def build_motion_dict(mags, vxs, vys, rads, diffs, start_sec, fps_hz):
    if not mags:
        return _empty_motion(fps_hz)

    motion_curve = _normalize(mags)
    peak_idx = int(np.argmax(motion_curve))
    avg_intensity = float(np.mean(motion_curve))
    peak_intensity = float(motion_curve[peak_idx])
    peak_timestamp_sec = start_sec + (peak_idx + 1) / fps_hz

    return {
        "motion_curve": [round(float(v), 4) for v in motion_curve],
        "avg_intensity": round(avg_intensity, 4),
        "peak_intensity": round(peak_intensity, 4),
        "peak_timestamp_sec": round(peak_timestamp_sec, 3),
        "motion_rate_hz": round(float(fps_hz), 3),
        "camera_movement": _classify_camera(mags, vxs, vys, rads),
        "stability_score": round(_stability_score(motion_curve), 4),
        "_frame_diffs_raw": list(diffs),
        "_flow_mean_vx": list(vxs),
        "_flow_mean_vy": list(vys),
        "_flow_radial": list(rads),
        "_motion_curve_raw": list(motion_curve),
    }


def flow_stats(flow):
    vx = flow[..., 0]
    vy = flow[..., 1]
    mag = np.sqrt(vx * vx + vy * vy)
    mean_mag = float(mag.mean())
    mean_vx = float(vx.mean())
    mean_vy = float(vy.mean())

    h, w = vx.shape
    cx, cy = w / 2.0, h / 2.0
    ys, xs = np.mgrid[0:h, 0:w]
    dx = xs - cx
    dy = ys - cy
    dist = np.sqrt(dx * dx + dy * dy) + 1e-6
    radial = (vx * dx + vy * dy) / dist
    radial_ratio = float(abs(radial.mean()) / (mean_mag + 1e-6))
    return mean_mag, mean_vx, mean_vy, radial_ratio


def to_gray_small(frame):
    h, w = frame.shape[:2]
    if w > FLOW_DOWNSAMPLE_WIDTH:
        scale = FLOW_DOWNSAMPLE_WIDTH / w
        new_w = FLOW_DOWNSAMPLE_WIDTH
        new_h = int(round(h * scale))
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _iter_gray_small(video_path, start_frame, end_frame):
    cap = cv2.VideoCapture(str(video_path))
    try:
        if start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        count = max(0, end_frame - start_frame)
        for _ in range(count):
            ret, frame = cap.read()
            if not ret:
                break
            yield to_gray_small(frame)
    finally:
        cap.release()


def _normalize(mags):
    arr = np.asarray(mags, dtype=np.float64)
    ref = float(np.percentile(arr, FLOW_NORM_PERCENTILE))
    if ref <= 0:
        return [0.0] * len(mags)
    return np.clip(arr / ref, 0.0, 1.0).tolist()


def _classify_camera(mags, vxs, vys, rads):
    mean_mag = float(np.mean(mags))
    if mean_mag < STATIC_FLOW_MAG:
        return "static"
    if float(np.mean(rads)) > RADIAL_RATIO:
        return "zoom"

    mean_vx = float(np.mean(vxs))
    mean_vy = float(np.mean(vys))
    abs_vx_mean = float(np.mean(np.abs(vxs))) + 1e-6
    abs_vy_mean = float(np.mean(np.abs(vys))) + 1e-6
    consistency_x = abs(mean_vx) / abs_vx_mean
    consistency_y = abs(mean_vy) / abs_vy_mean

    if consistency_x > PAN_DIRECTION_CONSISTENCY and abs(mean_vx) >= abs(mean_vy):
        return "whip_pan" if mean_mag > WHIP_PAN_FLOW_MAG else "pan"
    if consistency_y > PAN_DIRECTION_CONSISTENCY:
        return "whip_pan" if mean_mag > WHIP_PAN_FLOW_MAG else "tilt"
    return "handheld"


def _stability_score(curve):
    if len(curve) < 2:
        return 1.0
    v = float(np.var(curve))
    return max(0.0, min(1.0, 1.0 - v / 0.25))


def _empty_motion(fps_hz):
    return {
        "motion_curve": [],
        "avg_intensity": 0.0,
        "peak_intensity": 0.0,
        "peak_timestamp_sec": 0.0,
        "motion_rate_hz": round(float(fps_hz), 3),
        "camera_movement": "static",
        "stability_score": 1.0,
        "_frame_diffs_raw": [],
        "_flow_mean_vx": [],
        "_flow_mean_vy": [],
        "_flow_radial": [],
        "_motion_curve_raw": [],
    }
