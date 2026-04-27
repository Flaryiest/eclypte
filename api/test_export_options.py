import pytest

from api.export_options import resolve_export_options, trim_song_analysis


def _song_analysis():
    return {
        "schema_version": 1,
        "source": {
            "path": "song.wav",
            "duration_sec": 8.0,
            "sample_rate": 44100,
        },
        "tempo_bpm": 120.0,
        "beats_sec": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        "downbeats_sec": [0.0, 4.0],
        "energy": {
            "rate_hz": 2,
            "values": list(range(16)),
        },
        "segments": [
            {"start_sec": 0.0, "end_sec": 3.0, "label": "intro"},
            {"start_sec": 3.0, "end_sec": 8.0, "label": "chorus"},
        ],
    }


def test_resolve_export_options_defaults_to_legacy_horizontal_output():
    options = resolve_export_options(None, max_duration_sec=None)

    assert options.format == "youtube_16_9"
    assert options.output_size == (1920, 1080)
    assert options.crop == "letterbox"
    assert options.audio_start_sec == 0.0
    assert options.audio_end_sec is None
    assert options.crop_focus_x == 0.5


def test_resolve_export_options_maps_reels_to_vertical_fill_crop():
    options = resolve_export_options(
        {
            "format": "reels_9_16",
            "audio_start_sec": 2.5,
            "audio_end_sec": 17.5,
            "crop_focus_x": 0.25,
        },
        max_duration_sec=None,
    )

    assert options.output_size == (1080, 1920)
    assert options.crop == "fill"
    assert options.audio_start_sec == 2.5
    assert options.audio_end_sec == 17.5
    assert options.crop_focus_x == 0.25


def test_resolve_export_options_treats_legacy_max_duration_as_end_time():
    options = resolve_export_options(
        {"audio_start_sec": 5.0},
        max_duration_sec=12.0,
    )

    assert options.audio_start_sec == 5.0
    assert options.audio_end_sec == 17.0


def test_trim_song_analysis_clips_and_shifts_timing_data():
    trimmed = trim_song_analysis(_song_analysis(), start_sec=1.0, end_sec=5.0)

    assert trimmed["source"]["duration_sec"] == 4.0
    assert trimmed["beats_sec"] == [0.0, 1.0, 2.0, 3.0]
    assert trimmed["downbeats_sec"] == [3.0]
    assert trimmed["energy"] == {"rate_hz": 2, "values": list(range(2, 10))}
    assert trimmed["segments"] == [
        {"start_sec": 0.0, "end_sec": 2.0, "label": "intro"},
        {"start_sec": 2.0, "end_sec": 4.0, "label": "chorus"},
    ]


def test_trim_song_analysis_rejects_invalid_ranges():
    song = _song_analysis()

    with pytest.raises(ValueError, match="after audio_start_sec"):
        trim_song_analysis(song, start_sec=3.0, end_sec=3.0)

    with pytest.raises(ValueError, match="exceeds song duration"):
        trim_song_analysis(song, start_sec=1.0, end_sec=9.0)
