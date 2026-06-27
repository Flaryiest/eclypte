"""Unit tests for the pure native-ffmpeg command builder.

The builder turns a validated Timeline into an ffmpeg argv list. It is pure
(no subprocess, no moviepy) so these run anywhere.
"""
from api.prototyping.edit.render.ffmpeg_filtergraph import (
    build_command,
    can_render_with_ffmpeg,
)
from api.prototyping.edit.synthesis.timeline_schema import (
    AudioSpec,
    Effect,
    OutputSpec,
    Overlay,
    Shot,
    ShotSource,
    SourceRef,
    Timeline,
    Transition,
)


def _shots(specs):
    """specs: list of (source_start, duration, speed, transition). Returns Shots
    with contiguous timeline times."""
    shots = []
    t = 0.0
    for i, (start, dur, speed, transition) in enumerate(specs):
        shots.append(
            Shot(
                index=i,
                timeline_start_sec=round(t, 3),
                timeline_end_sec=round(t + dur, 3),
                source=ShotSource(start_sec=start, end_sec=start + dur),
                speed=speed,
                transition_in=Transition(type=transition),
            )
        )
        t += dur
    return shots


def _timeline(specs, *, crop="letterbox", w=1080, h=1920, fps=30, focus_x=0.5,
              audio_start=0.0, gain_db=0.0, audio_fade=0.0, video_fade=0.0):
    shots = _shots(specs)
    total = sum(s.duration_sec for s in shots)
    return Timeline(
        source=SourceRef(video="SRC.mp4", audio="AUD.wav"),
        output=OutputSpec(width=w, height=h, fps=fps, duration_sec=total,
                          crop=crop, crop_focus_x=focus_x, fade_out_sec=video_fade),
        audio=AudioSpec(path="AUD.wav", start_sec=audio_start, gain_db=gain_db,
                        fade_out_sec=audio_fade),
        shots=shots,
    )


def _filter_complex(argv):
    return argv[argv.index("-filter_complex") + 1]


def test_single_shot_letterbox_builds_runnable_argv():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")])
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/out.mp4")

    assert argv[0] == "ffmpeg"
    # exactly one video input (the shot) + one audio input
    assert argv.count("/s.mp4") == 1
    assert argv.count("/a.wav") == 1
    # the shot is seeked, not full-decoded
    assert "-ss" in argv and "-t" in argv
    fc = _filter_complex(argv)
    # letterbox = scale-decrease + pad to the output size
    assert "force_original_aspect_ratio=decrease" in fc
    assert "pad=1080:1920" in fc
    # exact encode contract preserved
    for token in ["libx264", "-crf", "18", "-tune", "animation",
                  "-pix_fmt", "yuv420p", "+faststart", "aac", "192k"]:
        assert token in argv
    assert argv[-1] == "/out.mp4"


def test_three_cuts_use_a_single_concat():
    tl = _timeline([(80.0, 2.0, 1.0, "cut"),
                    (200.0, 3.0, 1.0, "cut"),
                    (400.0, 4.0, 1.0, "cut")])
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4")
    fc = _filter_complex(argv)
    assert argv.count("/s.mp4") == 3
    assert "concat=n=3:v=1" in fc
    assert "xfade" not in fc


def test_fill_crop_covers_and_honors_focus_x():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")], crop="fill", focus_x=0.0)
    fc = _filter_complex(build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4"))
    assert "force_original_aspect_ratio=increase" in fc
    assert "crop=1080:1920:(iw-1080)*0:" in fc


def test_speed_widens_input_window_and_retimes():
    tl = _timeline([(80.0, 2.0, 2.0, "cut")])
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4")
    # read 2.0*2.0 = 4.0s of source so setpts=PTS/2 yields a 2.0s shot
    assert "4.000" in argv
    assert "setpts=PTS/2" in _filter_complex(argv)


def test_audio_gain_applies_volume_filter():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")], gain_db=-3.0)
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4")
    assert "volume=-3.0dB" in _filter_complex(argv)
    assert "[aout]" in argv


def test_preview_overrides_size_and_fps():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")])
    fc = _filter_complex(build_command(tl, source="/s.mp4", audio="/a.wav",
                                       out_path="/o.mp4", size=(405, 720), fps=24))
    assert "scale=405:720" in fc
    assert "fps=24" in fc


def test_crossfade_uses_xfade_with_cumulative_offset():
    # 3 shots: shot1 crossfades from shot0 (d=0.25), shot2 is a hard cut.
    tl = _timeline([(80.0, 2.0, 1.0, "cut"),
                    (200.0, 3.0, 1.0, "crossfade"),
                    (400.0, 4.0, 1.0, "cut")])
    tl.shots[1].transition_in.duration_sec = 0.25
    fc = _filter_complex(build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4"))
    # xfade starts at acc_dur - d = 2.0 - 0.25 = 1.75
    assert "xfade=transition=fade:duration=0.25:offset=1.75" in fc
    # the trailing cut concatenates onto the crossfaded accumulator
    assert "concat=n=2:v=1" in fc


def test_crossfade_defaults_to_quarter_second_when_unset():
    tl = _timeline([(80.0, 2.0, 1.0, "cut"), (200.0, 3.0, 1.0, "crossfade")])
    fc = _filter_complex(build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4"))
    assert "duration=0.25:offset=1.75" in fc


def test_phase1_supports_cuts_crossfade_whip_speed():
    tl = _timeline([(80.0, 2.0, 1.5, "cut"),
                    (200.0, 3.0, 1.0, "crossfade"),
                    (400.0, 4.0, 1.0, "whip")])
    assert can_render_with_ffmpeg(tl) is True


def test_phase1_rejects_overlays():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")])
    tl.overlays.append(Overlay(skill_id="text.hook", timeline_start_sec=0.0,
                               timeline_end_sec=1.0, params={"text": "hi"}))
    assert can_render_with_ffmpeg(tl) is False


def test_phase1_rejects_effects():
    tl = _timeline([(80.0, 2.0, 1.0, "cut")])
    tl.shots[0].effects.append(Effect(type="freeze"))
    assert can_render_with_ffmpeg(tl) is False


def test_phase1_rejects_flash_transition():
    tl = _timeline([(80.0, 2.0, 1.0, "cut"), (200.0, 3.0, 1.0, "flash")])
    assert can_render_with_ffmpeg(tl) is False


def test_tail_fade_adds_afade_and_video_fade():
    tl = _timeline([(80.0, 10.0, 1.0, "cut")], audio_fade=2.5, video_fade=2.5)
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4")
    fc = _filter_complex(argv)
    # 10s reel, 2.5s fade -> starts at 7.5
    assert "afade=t=out:st=7.500:d=2.5" in fc
    assert "fade=t=out:st=7.500:d=2.5" in fc
    assert "[aout]" in argv


def test_no_fade_when_zero():
    tl = _timeline([(80.0, 10.0, 1.0, "cut")])
    fc = _filter_complex(build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4"))
    assert "afade" not in fc
    assert "fade=t=out" not in fc


def test_audio_gain_and_fade_chain_into_single_aout():
    tl = _timeline([(80.0, 10.0, 1.0, "cut")], gain_db=-3.0, audio_fade=2.5)
    argv = build_command(tl, source="/s.mp4", audio="/a.wav", out_path="/o.mp4")
    fc = _filter_complex(argv)
    # gain then fade, comma-chained into one [aout] entry (no ';' between them)
    assert "volume=-3.0dB,afade=t=out:st=7.500:d=2.5[aout]" in fc
    # exactly one [aout] label produced
    assert fc.count("[aout]") == 1
