"""Tests for the native-ffmpeg executor: the pure progress parser (always) and
a guarded end-to-end render that runs real ffmpeg when it is available."""
import shutil
import subprocess
from pathlib import Path

import pytest

from api.prototyping.edit.render.ffmpeg_run import progress_percent, render_with_ffmpeg
from api.prototyping.edit.synthesis.timeline_schema import (
    AudioSpec,
    OutputSpec,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
    Transition,
)


def test_progress_percent_from_frame_line():
    assert progress_percent("frame=50", 200) == 25


def test_progress_percent_clamps_over_total():
    assert progress_percent("frame=250", 200) == 100


def test_progress_percent_ignores_non_frame_lines():
    assert progress_percent("out_time_us=4100000", 200) is None
    assert progress_percent("progress=end", 200) is None


def test_progress_percent_zero_total_is_safe():
    assert progress_percent("frame=10", 0) is None


# --- guarded end-to-end render (real ffmpeg) -------------------------------

def _ffmpeg():
    return shutil.which("ffmpeg") or _imageio_ffmpeg()


def _imageio_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


have_ffmpeg = pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg not available")


@have_ffmpeg
def test_render_with_ffmpeg_produces_mp4_and_poster(tmp_path):
    exe = _ffmpeg()
    source = tmp_path / "source.mp4"
    audio = tmp_path / "audio.wav"
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
                    "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                    str(audio)], check=True, capture_output=True)

    shots = [
        Shot(index=0, timeline_start_sec=0.0, timeline_end_sec=1.0,
             source=ShotSource(start_sec=1.0, end_sec=2.0), transition_in=Transition(type="cut")),
        Shot(index=1, timeline_start_sec=1.0, timeline_end_sec=2.5,
             source=ShotSource(start_sec=4.0, end_sec=5.5), transition_in=Transition(type="cut")),
    ]
    timeline = Timeline(
        source=SourceRef(video=str(source), audio=str(audio)),
        output=OutputSpec(width=256, height=256, fps=30, duration_sec=2.5, crop="letterbox"),
        audio=AudioSpec(path=str(audio), start_sec=0.0),
        shots=shots,
    )
    out = tmp_path / "out.mp4"
    poster = tmp_path / "poster.jpg"
    seen = []
    render_with_ffmpeg(timeline, source=source, audio=audio, out_path=out,
                       progress_callback=lambda p, d: seen.append(p), poster_path=poster)

    assert out.exists() and out.stat().st_size > 0
    assert poster.exists() and poster.stat().st_size > 0
    assert seen and seen[-1] == 100


def test_render_timeline_routes_cuts_only_to_native_ffmpeg(tmp_path, monkeypatch):
    pytest.importorskip("moviepy")  # renderer imports moviepy at module top
    from api.prototyping.edit.render import renderer

    used = {}

    def fake(timeline, **kw):
        used["called"] = True
        Path(kw["out_path"]).write_bytes(b"stub")
        return Path(kw["out_path"])

    monkeypatch.setattr(renderer, "render_with_ffmpeg", fake)

    tl = Timeline(
        source=SourceRef(video="/s.mp4", audio="/a.wav"),
        output=OutputSpec(width=1080, height=1920, fps=30, duration_sec=4.0, crop="letterbox"),
        audio=AudioSpec(path="/a.wav", start_sec=0.0),
        shots=[
            Shot(index=0, timeline_start_sec=0.0, timeline_end_sec=2.0,
                 source=ShotSource(start_sec=80.0, end_sec=82.0), transition_in=Transition(type="cut")),
            Shot(index=1, timeline_start_sec=2.0, timeline_end_sec=4.0,
                 source=ShotSource(start_sec=200.0, end_sec=202.0), transition_in=Transition(type="cut")),
        ],
    )
    tl_path = tmp_path / "tl.json"
    tl_path.write_text(tl.model_dump_json())
    out = tmp_path / "o.mp4"

    renderer.render_timeline(tl_path, out)

    assert used.get("called") is True
    assert out.read_bytes() == b"stub"
