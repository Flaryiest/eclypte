"""End-of-reel fades for the MoviePy fallback renderer.

Audio fade-out + video fade-to-black over the final seconds, mirroring the
afade/fade filters the native ffmpeg path emits (ffmpeg_filtergraph.build_command).
Implemented with clip.transform — the same low-level pattern transitions.py uses —
to avoid depending on moviepy effect-class APIs.
"""
from __future__ import annotations

import numpy as np


def video_fade_out(clip, fade_sec: float):
    fade = min(float(fade_sec), float(clip.duration or 0.0))
    if fade <= 0:
        return clip
    duration = float(clip.duration)
    start = duration - fade

    def dim(get_frame, t):
        frame = get_frame(t)
        if t <= start:
            return frame
        gain = max(0.0, (duration - t) / fade)
        return (frame.astype(np.float32) * gain).astype("uint8")

    return clip.transform(dim)


def audio_fade_out(clip, fade_sec: float):
    fade = min(float(fade_sec), float(clip.duration or 0.0))
    if fade <= 0:
        return clip
    duration = float(clip.duration)
    start = duration - fade

    def fade_fn(get_frame, t):
        frame = np.asarray(get_frame(t), dtype=np.float32)
        tt = np.asarray(t, dtype=np.float32)
        gain = np.clip((duration - tt) / fade, 0.0, 1.0)
        gain = np.where(tt <= start, 1.0, gain)
        if frame.ndim == 2:  # (n_samples, n_channels)
            gain = np.reshape(gain, (-1, 1))
        return frame * gain

    return clip.transform(fade_fn, keep_duration=True)
