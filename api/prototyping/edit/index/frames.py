import cv2
import numpy as np

def extract_frames(video_path: str, fps: int = 1) -> list[tuple[float, np.ndarray]]:
    """
    Extract frames from a video at the specified fps rate.
    Returns a list of tuples (timestamp_sec, frame_bgr_array).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video {video_path}")
        
    frames = []
    
    # We will grab frames at 1-second intervals
    # Since we don't know the exact duration easily, we iterate until False
    # Actually, a better way is to iterate by setting CAP_PROP_POS_MSEC
    
    sec = 0.0
    while True:
        # Set position in ms
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000.0)
        ret, frame = cap.read()
        
        if not ret:
            break
            
        frames.append((float(sec), frame))
        sec += 1.0 / fps
        
    cap.release()
    return frames
