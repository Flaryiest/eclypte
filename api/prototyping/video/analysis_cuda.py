from pathlib import Path
import json

import cv2
import numpy as np

from scenes import detect_scenes
from motion import build_motion_dict, flow_stats, to_gray_small
from impact import impacts_per_scene

SCHEMA_VERSION = 1


def analyze_cuda(video_path, out_path=None):
    video_path = Path(video_path)
    src_meta = _video_metadata(video_path)
    fps_hz = src_meta["fps_hz"]
    if fps_hz <= 0:
        raise ValueError(f"could not read fps from {video_path}")

    print(f"[analysis_cuda] {video_path.name}: {src_meta['duration_sec']:.1f}s "
          f"@ {fps_hz}fps, {src_meta['resolution']}")

    scenes = detect_scenes(video_path, src_meta["duration_sec"])
    print(f"[analysis_cuda] detected {len(scenes)} scenes")

    farneback = cv2.cuda.FarnebackOpticalFlow.create(
        numLevels=3, pyrScale=0.5, winSize=15, numIters=3,
        polyN=5, polySigma=1.2, flags=0,
    )
    scene_accs = [_SceneAccumulator() for _ in scenes]

    cap = cv2.VideoCapture(str(video_path))
    prev_gpu = None
    prev_gray = None
    cur_idx = 0
    fi = 0
    total_frames = int(src_meta["duration_sec"] * fps_hz)
    report_every = max(1, total_frames // 20)
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            ts = fi / fps_hz
            while cur_idx < len(scenes) and ts >= scenes[cur_idx][1]:
                cur_idx += 1
                prev_gpu = None
                prev_gray = None
            if cur_idx >= len(scenes):
                break

            gray = to_gray_small(frame)
            gpu = cv2.cuda_GpuMat()
            gpu.upload(gray)

            if prev_gpu is not None:
                flow_gpu = farneback.calc(prev_gpu, gpu, None)
                flow = flow_gpu.download()
                m, vx, vy, rad = flow_stats(flow)
                diff = float(np.mean(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16))))
                scene_accs[cur_idx].push(m, vx, vy, rad, diff)

            prev_gpu = gpu
            prev_gray = gray
            fi += 1
            if fi % report_every == 0:
                print(f"[analysis_cuda] {fi}/{total_frames} frames "
                      f"(scene {cur_idx + 1}/{len(scenes)})")
    finally:
        cap.release()

    scene_dicts = []
    for i, (start_sec, end_sec) in enumerate(scenes):
        acc = scene_accs[i]
        motion = build_motion_dict(
            acc.mags, acc.vxs, acc.vys, acc.rads, acc.diffs, start_sec, fps_hz,
        )
        impacts = impacts_per_scene((start_sec, end_sec), motion, fps_hz)
        scene_dicts.append(_assemble_scene(i, start_sec, end_sec, motion, impacts))

    result = {"schema_version": SCHEMA_VERSION, "source": src_meta, "scenes": scene_dicts}
    if out_path:
        Path(out_path).write_text(json.dumps(result, indent=2))
    return result


class _SceneAccumulator:
    def __init__(self):
        self.mags = []
        self.vxs = []
        self.vys = []
        self.rads = []
        self.diffs = []

    def push(self, m, vx, vy, rad, diff):
        self.mags.append(m)
        self.vxs.append(vx)
        self.vys.append(vy)
        self.rads.append(rad)
        self.diffs.append(diff)


def _video_metadata(video_path):
    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    finally:
        cap.release()
    codec = "".join(chr((fourcc_int >> (8 * k)) & 0xFF) for k in range(4)).strip("\x00 ")
    duration_sec = frame_count / fps if fps > 0 else 0.0
    return {
        "path": str(video_path),
        "duration_sec": round(duration_sec, 3),
        "resolution": [width, height],
        "fps_hz": round(fps, 3),
        "codec": codec,
    }


def _assemble_scene(index, start_sec, end_sec, motion, impacts):
    public_motion = {k: v for k, v in motion.items() if not k.startswith("_")}
    return {
        "index": index,
        "start_sec": round(float(start_sec), 3),
        "end_sec": round(float(end_sec), 3),
        "duration_sec": round(float(end_sec - start_sec), 3),
        "motion": public_motion,
        "impacts": impacts,
    }
