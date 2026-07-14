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


# --- skill asset materialization -------------------------------------------

def _lyrics_timeline(n_overlays=1):
    from api.prototyping.edit.synthesis.timeline_schema import Overlay

    overlay = Overlay(
        skill_id="lyrics.kinetic",
        timeline_start_sec=0.0,
        timeline_end_sec=2.0,
        params={
            "font_id": "anton",
            "style": "sweep",
            "lines": [
                {
                    "text": "hold me",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "words": [
                        {"text": "hold", "start_sec": 0.0, "end_sec": 0.5},
                        {"text": "me", "start_sec": 0.5, "end_sec": 1.0},
                    ],
                }
            ],
        },
    )
    return Timeline(
        source=SourceRef(video="/s.mp4", audio="/a.wav"),
        output=OutputSpec(width=1080, height=1920, fps=30, duration_sec=2.0, crop="letterbox"),
        audio=AudioSpec(path="/a.wav", start_sec=0.0),
        shots=[
            Shot(index=0, timeline_start_sec=0.0, timeline_end_sec=2.0,
                 source=ShotSource(start_sec=1.0, end_sec=3.0), transition_in=Transition(type="cut")),
        ],
        overlays=[overlay] * n_overlays,
    )


def test_write_skill_assets_materializes_ass_document(tmp_path):
    from api.prototyping.edit.render.ffmpeg_run import write_skill_assets
    from api.prototyping.edit.skills.base import RenderContext

    ctx = RenderContext(output_size=(1080, 1920), fps=30, font_path="",
                        asset_dir=str(tmp_path))
    written = write_skill_assets(_lyrics_timeline(), tmp_path, ctx)

    assert [p.name for p in written] == ["lyrics_kinetic.ass"]
    content = (tmp_path / "lyrics_kinetic.ass").read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "Dialogue:" in content


def test_write_skill_assets_raises_on_filename_collision(tmp_path):
    from api.prototyping.edit.render.ffmpeg_run import write_skill_assets
    from api.prototyping.edit.skills.base import RenderContext

    ctx = RenderContext(output_size=(1080, 1920), fps=30, font_path="",
                        asset_dir=str(tmp_path))
    with pytest.raises(ValueError, match="collide"):
        write_skill_assets(_lyrics_timeline(n_overlays=2), tmp_path, ctx)


def test_write_skill_assets_noop_for_assetless_skills(tmp_path):
    from api.prototyping.edit.render.ffmpeg_run import write_skill_assets
    from api.prototyping.edit.skills.base import RenderContext
    from api.prototyping.edit.synthesis.timeline_schema import Overlay

    tl = _lyrics_timeline()
    tl.overlays = [Overlay(skill_id="mask.vignette", timeline_start_sec=0.0,
                           timeline_end_sec=2.0, params={})]
    ctx = RenderContext(output_size=(1080, 1920), fps=30, font_path="",
                        asset_dir=str(tmp_path))
    assert write_skill_assets(tl, tmp_path, ctx) == []


# --- renderer wiring: fonts_dir + shot_stats --------------------------------

def test_render_timeline_passes_fonts_dir_and_shot_stats_for_lyrics(tmp_path, monkeypatch):
    pytest.importorskip("moviepy")
    from api.prototyping.edit.render import renderer
    from api.prototyping.edit.skills.base import ShotStats, ZoneStats

    sentinel_stats = [ShotStats(start_sec=0.0, end_sec=2.0,
                                zones=(ZoneStats(0.2, 0.1),) * 3,
                                dominant_hue_deg=200.0, saturation=0.5)]
    used = {}

    def fake_render(timeline, **kw):
        used.update(kw)
        Path(kw["out_path"]).write_bytes(b"stub")
        return Path(kw["out_path"])

    monkeypatch.setattr(renderer, "render_with_ffmpeg", fake_render)
    monkeypatch.setattr(renderer, "_sample_shot_stats_safe",
                        lambda timeline, size: sentinel_stats)
    monkeypatch.setattr(renderer, "_resolve_lyrics_fonts_dir", lambda: "/fonts/kinetic")

    tl_path = tmp_path / "tl.json"
    tl_path.write_text(_lyrics_timeline().model_dump_json())
    renderer.render_timeline(tl_path, tmp_path / "o.mp4")

    assert used["fonts_dir"] == "/fonts/kinetic"
    assert used["shot_stats"] == sentinel_stats


def test_render_timeline_survives_sampling_failure(tmp_path, monkeypatch):
    pytest.importorskip("moviepy")
    from api.prototyping.edit.render import renderer

    used = {}

    def fake_render(timeline, **kw):
        used.update(kw)
        Path(kw["out_path"]).write_bytes(b"stub")
        return Path(kw["out_path"])

    def boom(timeline, size):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(renderer, "render_with_ffmpeg", fake_render)
    monkeypatch.setattr(renderer.footage_stats, "sample_shot_stats", boom)

    tl_path = tmp_path / "tl.json"
    tl_path.write_text(_lyrics_timeline().model_dump_json())
    renderer.render_timeline(tl_path, tmp_path / "o.mp4")

    assert used["shot_stats"] is None
    assert (tmp_path / "o.mp4").read_bytes() == b"stub"


# --- guarded end-to-end lyrics render (real ffmpeg + libass) -----------------

def _ffmpeg_has_ass():
    exe = _ffmpeg()
    if exe is None:
        return False
    try:
        out = subprocess.run([exe, "-hide_banner", "-filters"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:
        return False
    return any(line.split()[1:2] == ["ass"] for line in out.splitlines())


have_libass = pytest.mark.skipif(not _ffmpeg_has_ass(), reason="ffmpeg lacks the ass filter")


@have_libass
def test_render_with_ffmpeg_burns_kinetic_lyrics(tmp_path):
    from api.prototyping.edit.synthesis.timeline_schema import Overlay

    exe = _ffmpeg()
    source = tmp_path / "source.mp4"
    audio = tmp_path / "audio.wav"
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=30:duration=6",
                    "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    str(audio)], check=True, capture_output=True)

    def timeline(overlays):
        return Timeline(
            source=SourceRef(video=str(source), audio=str(audio)),
            output=OutputSpec(width=270, height=480, fps=30, duration_sec=4.0, crop="letterbox"),
            audio=AudioSpec(path=str(audio), start_sec=0.0),
            shots=[
                Shot(index=0, timeline_start_sec=0.0, timeline_end_sec=4.0,
                     source=ShotSource(start_sec=0.5, end_sec=4.5),
                     transition_in=Transition(type="cut")),
            ],
            overlays=overlays,
        )

    lyrics = Overlay(
        skill_id="lyrics.kinetic",
        timeline_start_sec=0.0,
        timeline_end_sec=4.0,
        params={
            "font_id": "anton",
            "style": "sweep",
            "lines": [
                {"text": "hold me close", "start_sec": 0.5, "end_sec": 2.4,
                 "words": [
                     {"text": "hold", "start_sec": 0.5, "end_sec": 1.1},
                     {"text": "me", "start_sec": 1.1, "end_sec": 1.7},
                     {"text": "close", "start_sec": 1.7, "end_sec": 2.4},
                 ]},
            ],
        },
    )

    plain_out = tmp_path / "plain.mp4"
    lyric_out = tmp_path / "lyrics.mp4"
    render_with_ffmpeg(timeline([]), source=source, audio=audio, out_path=plain_out)
    # no fonts_dir on purpose: libass falls back to a system font — the text
    # must still burn in (a fontsdir miss must never blank the lyrics).
    render_with_ffmpeg(timeline([lyrics]), source=source, audio=audio, out_path=lyric_out)

    assert lyric_out.exists() and lyric_out.stat().st_size > 0

    def frame_at(video, t):
        png = tmp_path / f"{video.stem}_{t}.png"
        subprocess.run([exe, "-y", "-ss", str(t), "-i", str(video),
                        "-frames:v", "1", str(png)], check=True, capture_output=True)
        return png.read_bytes()

    # mid-word frame differs between the two renders => text was drawn
    assert frame_at(lyric_out, 1.3) != frame_at(plain_out, 1.3)
    # frame in the wordless tail should be (near-)identical encodes; we only
    # assert the lyric frames differ, tail equality is not guaranteed by x264
