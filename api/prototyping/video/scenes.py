from scenedetect import detect, ContentDetector

SCENE_CONTENT_THRESHOLD = 27.0


def detect_scenes(video_path, duration_sec):
    raw = detect(str(video_path), ContentDetector(threshold=SCENE_CONTENT_THRESHOLD))
    scenes = [(float(s.get_seconds()), float(e.get_seconds())) for s, e in raw]
    if not scenes:
        return [(0.0, float(duration_sec))]
    return scenes
