"""End-credit detection by OCR text density from the tail of a film.

`decide_content_end` is the pure decision (unit-tested, no OpenCV/Tesseract):
given per-frame word counts it locates the dense-text credits block anchored at
the end and returns a conservative `content_end_sec = credits_start - 30s`.
`detect_content_end` does the tail decode + OCR and feeds it. This module stays
Modal-free (like scenes.py/motion.py) and imports cv2/pytesseract lazily.
"""
from __future__ import annotations

# --- decision thresholds (pure) ---
MIN_WORDS = 8                  # "a fair amount of clearly visible text"
CREDIT_BUFFER_SEC = 30.0       # cut this far BEFORE credits begin
MIN_CREDITS_SEC = 20.0         # a shorter text run is an end-title, not credits
GAP_SEC = 8.0                  # bridge short non-text gaps (black between cards)
END_TAIL_TOLERANCE_SEC = 60.0  # credits must reach within this of the end
MIN_CREDITS_START_FRAC = 0.6   # distrust credits that start before this fraction
MIN_CONTENT_FRAC = 0.5         # never trim below this fraction of the film

# --- detection (integration) ---
TAIL_SCAN_SEC = 900.0          # scan at most the last 15 min
SAMPLE_FPS = 1.0
MIN_CONF = 60                  # Tesseract per-word confidence
DOWNSCALE_WIDTH = 1280


def _no_trim(duration_sec: float) -> dict:
    return {
        "credits_detected": False,
        "credits_start_sec": None,
        "content_end_sec": round(float(duration_sec), 3),
    }


def decide_content_end(samples, duration_sec: float) -> dict:
    """Locate the end-credits block from `[(timestamp_sec, word_count), ...]`.

    Returns {credits_detected, credits_start_sec, content_end_sec}. Falls back to
    no trim (content_end_sec = duration) when no trustworthy credits block is found.
    """
    duration_sec = float(duration_sec)
    if not samples or duration_sec <= 0:
        return _no_trim(duration_sec)

    texty = [wc >= MIN_WORDS for _, wc in samples]
    last_texty = next((i for i in range(len(samples) - 1, -1, -1) if texty[i]), None)
    if last_texty is None:
        return _no_trim(duration_sec)

    block_end_ts = samples[last_texty][0]
    # Credits must sit at the tail (allowing a short black outro after the text).
    if block_end_ts < duration_sec - END_TAIL_TOLERANCE_SEC:
        return _no_trim(duration_sec)

    # Walk backward from the last texty frame, bridging short non-text gaps.
    block_start_idx = last_texty
    last_texty_ts = samples[last_texty][0]
    for i in range(last_texty - 1, -1, -1):
        ts = samples[i][0]
        if texty[i]:
            block_start_idx = i
            last_texty_ts = ts
        elif last_texty_ts - ts > GAP_SEC:
            break
    credits_start_sec = samples[block_start_idx][0]

    if block_end_ts - credits_start_sec < MIN_CREDITS_SEC:
        return _no_trim(duration_sec)
    if credits_start_sec < MIN_CREDITS_START_FRAC * duration_sec:
        return _no_trim(duration_sec)

    floor = MIN_CONTENT_FRAC * duration_sec
    content_end_sec = max(floor, credits_start_sec - CREDIT_BUFFER_SEC)
    return {
        "credits_detected": True,
        "credits_start_sec": round(credits_start_sec, 3),
        "content_end_sec": round(content_end_sec, 3),
    }


def detect_content_end(
    video_path,
    duration_sec: float,
    fps_hz: float,
    *,
    tail_scan_sec: float = TAIL_SCAN_SEC,
    sample_fps: float = SAMPLE_FPS,
) -> dict:
    """OCR-scan the tail of the film and decide where content ends.

    Seeks once to the start of the scan window then reads sequentially (never
    per-frame seeking). Counts confident Tesseract word boxes per sampled frame
    as the text-density signal.
    """
    import cv2
    import pytesseract
    from pytesseract import Output

    src_fps = float(fps_hz) or SAMPLE_FPS
    cap = cv2.VideoCapture(str(video_path))
    try:
        probe_fps = cap.get(cv2.CAP_PROP_FPS)
        if probe_fps and probe_fps == probe_fps:  # not 0/NaN
            src_fps = float(probe_fps)
        start_sec = max(0.0, float(duration_sec) - tail_scan_sec)
        start_frame = int(start_sec * src_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        step = max(1, round(src_fps / sample_fps))

        samples: list[tuple[float, int]] = []
        i = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if i % step == 0:
                ts = (start_frame + i) / src_fps
                samples.append((round(ts, 3), _count_words(frame, cv2, pytesseract, Output)))
            i += 1
    finally:
        cap.release()

    return decide_content_end(samples, duration_sec)


def _count_words(frame, cv2, pytesseract, Output) -> int:
    h, w = frame.shape[:2]
    if w > DOWNSCALE_WIDTH:
        scale = DOWNSCALE_WIDTH / w
        frame = cv2.resize(frame, (DOWNSCALE_WIDTH, int(h * scale)))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(gray, output_type=Output.DICT)
    count = 0
    for text, conf in zip(data["text"], data["conf"]):
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            continue
        if confidence >= MIN_CONF and len(text.strip()) >= 2:
            count += 1
    return count
