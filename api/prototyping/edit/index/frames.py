import cv2
import numpy as np


def extract_frames(video_path: str, fps: int = 1) -> list[tuple[float, np.ndarray]]:
    """
    Extract frames from a video at the specified fps rate.
    Returns a list of tuples (timestamp_sec, frame_bgr_array).

    Decodes sequentially and keeps every Nth frame where
    N = round(source_fps / fps). Much faster than per-frame seeking
    on long videos.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video {video_path}")

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not source_fps or source_fps != source_fps:  # 0 or NaN
        source_fps = float(fps)

    step = max(1, round(source_fps / fps))

    frames = []
    counter = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if counter % step == 0:
            frames.append((counter / source_fps, frame))
        counter += 1

    cap.release()
    return frames
