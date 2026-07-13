import pytest

from api.export_options import (
    resolve_export_options,
    trim_lyrics_timing,
    trim_song_analysis,
)


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


def test_resolve_export_options_maps_cinematic_reels_to_vertical_letterbox():
    options = resolve_export_options(
        {
            "format": "reels_cinematic",
            "audio_start_sec": 1.0,
            "audio_end_sec": 19.0,
        },
        max_duration_sec=None,
    )

    assert options.format == "reels_cinematic"
    assert options.output_size == (1080, 1920)
    assert options.crop == "letterbox"
    assert options.as_run_inputs()["export_format"] == "reels_cinematic"


def test_resolve_export_options_rejects_unknown_format():
    with pytest.raises(ValueError, match="export format must be"):
        resolve_export_options({"format": "imax_70mm"}, max_duration_sec=None)


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


def _lyrics_timing():
    return {
        "schema_version": 1,
        "source": {"duration_sec": 20.0},
        "mode": "aligned",
        "language": "en",
        "text_source": "synced_lrc",
        "model": "large-v3",
        "quality": {"word_count": 7},
        "lines": [
            {
                "line_idx": 0,
                "start_sec": 1.0,
                "end_sec": 4.0,
                "text": "before window",
                "words": [
                    {"word": "before", "start_sec": 1.0, "end_sec": 2.0, "confidence": 0.9},
                    {"word": "window", "start_sec": 2.0, "end_sec": 4.0, "confidence": 0.9},
                ],
            },
            {
                "line_idx": 1,
                "start_sec": 9.0,
                "end_sec": 12.0,
                "text": "straddles start",
                "words": [
                    {"word": "straddles", "start_sec": 9.0, "end_sec": 9.8, "confidence": 0.8},
                    {"word": "start", "start_sec": 9.5, "end_sec": 10.5, "confidence": 0.7},
                ],
            },
            {
                "line_idx": 2,
                "start_sec": 13.0,
                "end_sec": 15.0,
                "text": "fully inside",
                "words": [
                    {"word": "fully", "start_sec": 13.0, "end_sec": 14.0, "confidence": 0.95},
                    {"word": "inside", "start_sec": 14.0, "end_sec": 15.0, "confidence": 0.9},
                ],
            },
            {
                "line_idx": 3,
                "start_sec": 18.0,
                "end_sec": 19.5,
                "text": "after window",
                "words": [
                    {"word": "after", "start_sec": 18.0, "end_sec": 19.5, "confidence": 0.9},
                ],
            },
        ],
    }


def test_trim_lyrics_timing_clips_and_rebases_lines_and_words():
    trimmed = trim_lyrics_timing(_lyrics_timing(), start_sec=10.0, end_sec=16.0)

    assert trimmed["source"] == {
        "duration_sec": 6.0,
        "trim_start_sec": 10.0,
        "trim_end_sec": 16.0,
    }
    lines = trimmed["lines"]
    # Line 0 (1-4) and line 3 (18-19.5) fall outside the window entirely.
    assert [line["line_idx"] for line in lines] == [1, 2]

    straddler = lines[0]
    assert straddler["text"] == "straddles start"
    assert straddler["start_sec"] == 0.0
    assert straddler["end_sec"] == 2.0
    # "straddles" (9.0-9.8) ends before the window; "start" (9.5-10.5) overlaps
    # and is rebased + clamped into it.
    assert straddler["words"] == [
        {"word": "start", "start_sec": 0.0, "end_sec": 0.5, "confidence": 0.7},
    ]

    inside = lines[1]
    assert inside["start_sec"] == 3.0
    assert inside["end_sec"] == 5.0
    assert inside["words"][0] == {
        "word": "fully",
        "start_sec": 3.0,
        "end_sec": 4.0,
        "confidence": 0.95,
    }


def test_trim_lyrics_timing_keeps_overlapping_line_with_no_surviving_words():
    lyrics = _lyrics_timing()
    lyrics["lines"] = [
        {
            "line_idx": 0,
            "start_sec": 9.0,
            "end_sec": 10.5,
            "text": "sliver",
            "words": [
                {"word": "sliver", "start_sec": 9.0, "end_sec": 9.9, "confidence": 0.9},
            ],
        }
    ]

    trimmed = trim_lyrics_timing(lyrics, start_sec=10.0, end_sec=16.0)

    assert len(trimmed["lines"]) == 1
    assert trimmed["lines"][0]["text"] == "sliver"
    assert trimmed["lines"][0]["words"] == []


def test_trim_lyrics_timing_clamps_end_past_duration_instead_of_raising():
    # The window is validated against the music analysis; the whisper-measured
    # duration can differ, so a best-effort artifact must clamp rather than throw.
    trimmed = trim_lyrics_timing(_lyrics_timing(), start_sec=10.0, end_sec=25.0)

    assert trimmed["source"]["duration_sec"] == 10.0
    assert trimmed["source"]["trim_end_sec"] == 20.0
    assert [line["line_idx"] for line in trimmed["lines"]] == [1, 2, 3]


def test_trim_lyrics_timing_none_end_uses_full_duration():
    trimmed = trim_lyrics_timing(_lyrics_timing(), start_sec=5.0, end_sec=None)

    assert trimmed["source"]["duration_sec"] == 15.0
    assert [line["line_idx"] for line in trimmed["lines"]] == [1, 2, 3]


def test_trim_lyrics_timing_passes_through_metadata():
    trimmed = trim_lyrics_timing(_lyrics_timing(), start_sec=10.0, end_sec=16.0)

    assert trimmed["schema_version"] == 1
    assert trimmed["mode"] == "aligned"
    assert trimmed["language"] == "en"
    assert trimmed["text_source"] == "synced_lrc"
    assert trimmed["model"] == "large-v3"
    assert trimmed["quality"] == {"word_count": 7}


def test_trim_lyrics_timing_rejects_invalid_ranges():
    lyrics = _lyrics_timing()

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        trim_lyrics_timing(lyrics, start_sec=-1.0, end_sec=5.0)

    with pytest.raises(ValueError, match="after audio_start_sec"):
        trim_lyrics_timing(lyrics, start_sec=5.0, end_sec=5.0)
