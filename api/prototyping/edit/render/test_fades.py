import numpy as np
import pytest

moviepy = pytest.importorskip("moviepy")
from moviepy import AudioArrayClip, ColorClip  # noqa: E402

from api.prototyping.edit.render.fades import audio_fade_out, video_fade_out  # noqa: E402


def test_video_fade_out_darkens_only_the_tail():
    clip = ColorClip(size=(8, 8), color=(200, 200, 200)).with_duration(2.0)
    faded = video_fade_out(clip, 0.5)
    assert faded.get_frame(1.0).mean() == pytest.approx(200.0, abs=1.0)  # before fade: unchanged
    assert faded.get_frame(1.99).mean() < 60.0                            # tail: near black


def test_video_fade_out_zero_is_noop():
    clip = ColorClip(size=(8, 8), color=(200, 200, 200)).with_duration(2.0)
    assert video_fade_out(clip, 0.0) is clip


def test_audio_fade_out_drops_the_tail():
    arr = np.ones((44100, 2), dtype=np.float32)  # 1.0s stereo, full amplitude
    clip = AudioArrayClip(arr, fps=44100)
    faded = audio_fade_out(clip, 0.5)
    assert abs(faded.get_frame(0.1)).mean() == pytest.approx(1.0, abs=0.05)  # before fade
    assert abs(faded.get_frame(0.99)).mean() < 0.2                           # tail dropped
