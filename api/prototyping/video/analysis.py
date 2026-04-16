from pathlib import Path
import json

import cv2

from scenes import detect_scenes
from motion import motion_per_scene
from impact import impacts_per_scene

SCHEMA_VERSION = 1


def analyze(video_path, out_path=None):
    video_path = Path(video_path)
    src_meta = _video_metadata(video_path)
    fps_hz = src_meta["fps_hz"]

    scenes = detect_scenes(video_path, src_meta["duration_sec"])

    scene_dicts = []
    for i, (start_sec, end_sec) in enumerate(scenes):
        motion = motion_per_scene(video_path, (start_sec, end_sec), fps_hz)
        impacts = impacts_per_scene((start_sec, end_sec), motion, fps_hz)
        scene_dicts.append(_assemble_scene(i, start_sec, end_sec, motion, impacts))

    result = {
        "schema_version": SCHEMA_VERSION,
        "source": src_meta,
        "scenes": scene_dicts,
    }

    if out_path is None:
        out_path = video_path.with_suffix(".json")
    Path(out_path).write_text(json.dumps(result, indent=2))
    return result


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


if __name__ == "__main__":
    analyze("./content/output.mp4", "./content/output.json")
