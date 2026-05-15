from api.prototyping.edit.synthesis import planner


def test_plan_preserves_export_output_and_explicit_audio_start(monkeypatch):
    song = {
        "source": {"duration_sec": 4.0},
        "tempo_bpm": 120.0,
        "downbeats_sec": [0.0, 2.0, 4.0],
        "segments": [{"start_sec": 0.0, "end_sec": 4.0, "label": "chorus"}],
    }
    video = {
        "source": {"duration_sec": 60.0},
        "scenes": [{"index": 0, "start_sec": 10.0, "end_sec": 30.0}],
    }

    monkeypatch.setattr(
        planner,
        "query_ranges",
        lambda *args, **kwargs: [{"scene_index": 0, "start_sec": 10.0, "end_sec": 30.0}],
    )
    monkeypatch.setattr(planner.registry, "ids", lambda patterns: {"micro.beat_cut_on_downbeat"})

    timeline = planner.plan(
        song,
        video,
        source_video_path="source.mp4",
        audio_path="song.wav",
        patterns=[],
        output_size=(1080, 1920),
        output_crop="fill",
        crop_focus_x=0.25,
        audio_start_sec=9.5,
    )

    assert timeline.output.width == 1080
    assert timeline.output.height == 1920
    assert timeline.output.crop == "fill"
    assert timeline.output.crop_focus_x == 0.25
    assert timeline.audio.start_sec == 9.5
    assert timeline.output.duration_sec == 4.0


def test_plan_clamps_source_ranges_to_source_duration(monkeypatch):
    song = {
        "source": {"duration_sec": 4.0},
        "tempo_bpm": 120.0,
        "downbeats_sec": [0.0, 4.0],
        "segments": [{"start_sec": 0.0, "end_sec": 4.0, "label": "chorus"}],
    }
    video = {
        "source": {"duration_sec": 20.0},
        "scenes": [{"index": 0, "start_sec": 18.5, "end_sec": 20.0}],
    }

    monkeypatch.setattr(
        planner,
        "query_ranges",
        lambda *args, **kwargs: [{"scene_index": 0, "start_sec": 18.5, "end_sec": 20.0}],
    )
    monkeypatch.setattr(planner.registry, "ids", lambda patterns: {"micro.beat_cut_on_downbeat"})

    timeline = planner.plan(
        song,
        video,
        source_video_path="source.mp4",
        audio_path="song.wav",
        patterns=[],
    )

    assert timeline.shots[0].source.end_sec == 20.0
    assert timeline.shots[0].source.start_sec == 16.0
