"""Guarded end-to-end render of a timeline carrying overlays.

Skips cleanly without moviepy or a usable font. Uses its own tempdir rather
than the pytest `tmp_path` fixture to avoid environment-specific temp issues.
"""
import json
import tempfile
import wave
from pathlib import Path

import pytest

pytest.importorskip("moviepy")

from api.prototyping.edit.render.renderer import _resolve_font_path, render_timeline


def _make_source_video(path: Path, size=(240, 180), duration=3.0, fps=24) -> None:
    from moviepy import ColorClip

    clip = ColorClip(size=size, color=(20, 60, 120)).with_duration(duration)
    clip.write_videofile(str(path), fps=fps, codec="libx264", audio=False, logger=None)
    clip.close()


def _make_silent_wav(path: Path, duration=3.0, rate=44100) -> None:
    frames = int(duration * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)


def test_render_with_text_and_vignette_overlays():
    try:
        _resolve_font_path()
    except FileNotFoundError:
        pytest.skip("no overlay font available")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        src = work / "src.mp4"
        aud = work / "a.wav"
        _make_source_video(src)
        _make_silent_wav(aud)

        timeline = {
            "schema_version": 1,
            "source": {"video": str(src), "audio": str(aud)},
            "output": {"width": 240, "height": 180, "fps": 24, "duration_sec": 2.0, "crop": "letterbox"},
            "audio": {"path": str(aud), "start_sec": 0.0},
            "shots": [
                {
                    "index": 0,
                    "timeline_start_sec": 0.0,
                    "timeline_end_sec": 2.0,
                    "source": {"start_sec": 0.0, "end_sec": 2.0},
                }
            ],
            "overlays": [
                {"skill_id": "text.hook", "timeline_start_sec": 0.0, "timeline_end_sec": 1.5, "params": {"text": "no way"}},
                {"skill_id": "mask.vignette", "timeline_start_sec": 0.0, "timeline_end_sec": 2.0, "params": {"strength": 0.6}},
            ],
        }
        tl_path = work / "timeline.json"
        tl_path.write_text(json.dumps(timeline), encoding="utf-8")

        out = work / "out.mp4"
        poster = work / "poster.jpg"
        render_timeline(tl_path, out, poster_path=poster)

        assert out.exists() and out.stat().st_size > 0
        assert poster.exists() and poster.stat().st_size > 0
