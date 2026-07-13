import pytest

from api.prototyping.music import lyrics_align
from api.prototyping.music.lyrics_align import (
    MIN_TRANSCRIBED_WORDS,
    alignment_quality,
    assemble_lyrics_timing,
    is_alignment_acceptable,
    is_transcription_acceptable,
    lrc_plain_text,
    parse_lrc,
    produce_lyrics_timing,
)


# ---- parse_lrc (reinstated from the removed synthesis/lyrics.py) ----

def test_parse_basic_lines():
    lrc = "[00:12.50]Hello world\n[00:15.00]Second line"
    assert parse_lrc(lrc) == [(12.5, "Hello world"), (15.0, "Second line")]


def test_parse_skips_metadata_tags():
    lrc = "[ar:Artist]\n[ti:Title]\n[offset:+100]\n[00:01.00]Line one"
    assert parse_lrc(lrc) == [(1.0, "Line one")]


def test_parse_expands_multiple_timestamps_per_line():
    lrc = "[00:10.00][00:20.00]Repeated"
    assert parse_lrc(lrc) == [(10.0, "Repeated"), (20.0, "Repeated")]


def test_parse_skips_empty_text_lines():
    lrc = "[00:05.00]\n[00:06.00]   \n[00:07.00]Real"
    assert parse_lrc(lrc) == [(7.0, "Real")]


def test_parse_sorts_ascending():
    lrc = "[00:20.00]B\n[00:10.00]A"
    assert parse_lrc(lrc) == [(10.0, "A"), (20.0, "B")]


def test_parse_three_digit_milliseconds():
    assert parse_lrc("[00:12.500]X") == [(12.5, "X")]


def test_parse_empty_and_none():
    assert parse_lrc("") == []
    assert parse_lrc(None) == []


# ---- lrc_plain_text ----

def test_plain_text_joins_lines_in_time_order():
    lrc = "[00:20.00]B line\n[00:10.00]A line"
    assert lrc_plain_text(lrc) == "A line\nB line"


def test_plain_text_repeats_chorus_per_sung_occurrence():
    # A multi-timestamp chorus line must appear once per occurrence, in sung
    # order — forced alignment needs the text to match everything that is sung.
    lrc = "[00:10.00][00:30.00]Chorus\n[00:20.00]Verse"
    assert lrc_plain_text(lrc) == "Chorus\nVerse\nChorus"


def test_plain_text_none_for_unsynced_or_empty():
    assert lrc_plain_text(None) is None
    assert lrc_plain_text("") is None
    assert lrc_plain_text("just some plain lyrics\nwith no timestamps") is None


# ---- quality metrics + acceptance gates ----

def _result(words_by_segment, language="en"):
    """Build a whisper-style to_dict() payload from [(text, [(word, start, end, prob)])]."""
    segments = []
    for text, words in words_by_segment:
        segments.append(
            {
                "start": words[0][1] if words else 0.0,
                "end": words[-1][2] if words else 0.0,
                "text": text,
                "words": [
                    {"word": w, "start": s, "end": e, "probability": p}
                    for (w, s, e, p) in words
                ],
            }
        )
    return {"language": language, "segments": segments}


def test_alignment_quality_metrics():
    result = _result(
        [
            ("one two", [("one", 10.0, 10.5, 0.8), ("two", 10.5, 11.0, 0.6)]),
            ("three four", [("three", 12.0, 12.0, 0.9), ("four", 12.5, 13.0, 0.7)]),
        ]
    )
    quality = alignment_quality(result, duration_sec=20.0)
    assert quality["word_count"] == 4
    assert quality["avg_word_probability"] == pytest.approx(0.75)
    assert quality["zero_duration_word_ratio"] == pytest.approx(0.25)
    # (last word end 13.0 - first word start 10.0) / 20.0
    assert quality["coverage_ratio"] == pytest.approx(0.15)


def test_alignment_quality_empty_result():
    quality = alignment_quality({"segments": []}, duration_sec=20.0)
    assert quality["word_count"] == 0
    assert quality["avg_word_probability"] == 0.0
    assert quality["coverage_ratio"] == 0.0


def _quality(word_count=100, avg=0.8, zero_ratio=0.0, coverage=0.9):
    return {
        "word_count": word_count,
        "avg_word_probability": avg,
        "zero_duration_word_ratio": zero_ratio,
        "coverage_ratio": coverage,
    }


def test_alignment_gate_accepts_good_quality():
    assert is_alignment_acceptable(_quality()) is True


def test_alignment_gate_rejects_no_words():
    assert is_alignment_acceptable(_quality(word_count=0, avg=0.0)) is False


def test_alignment_gate_rejects_mass_zero_duration_words():
    assert is_alignment_acceptable(_quality(zero_ratio=0.21)) is False
    assert is_alignment_acceptable(_quality(zero_ratio=0.20)) is True


def test_alignment_gate_rejects_low_probability():
    assert is_alignment_acceptable(_quality(avg=0.44)) is False


def test_alignment_gate_coverage_only_enforced_for_long_texts():
    # Wrong-lyrics signature: many words crammed into a sliver of the song.
    assert is_alignment_acceptable(_quality(word_count=100, coverage=0.1)) is False
    # Short texts (<= 30 words) legitimately cover little of the song.
    assert is_alignment_acceptable(_quality(word_count=20, coverage=0.1)) is True


def test_transcription_gate():
    assert is_transcription_acceptable(_quality(word_count=MIN_TRANSCRIBED_WORDS)) is True
    assert is_transcription_acceptable(_quality(word_count=MIN_TRANSCRIBED_WORDS - 1)) is False
    assert is_transcription_acceptable(_quality(avg=0.44)) is False


# ---- assemble_lyrics_timing ----

def test_assemble_schema_shape_and_rounding():
    result = _result(
        [
            (" Hello world ", [(" Hello", 1.23456, 1.5, 0.91234), ("world", 1.5, 2.0, 0.8)]),
            ("Next", [("Next", 3.0, 3.5, 0.7)]),
        ]
    )
    quality = alignment_quality(result, duration_sec=10.0)
    payload = assemble_lyrics_timing(
        duration_sec=10.0,
        mode="aligned",
        language="en",
        text_source="synced_lrc",
        model_name="large-v3",
        quality=quality,
        segments=result["segments"],
    )
    assert payload["schema_version"] == 1
    assert payload["source"] == {"duration_sec": 10.0}
    assert payload["mode"] == "aligned"
    assert payload["language"] == "en"
    assert payload["text_source"] == "synced_lrc"
    assert payload["model"] == "large-v3"
    assert payload["quality"]["word_count"] == 3

    lines = payload["lines"]
    assert [line["line_idx"] for line in lines] == [0, 1]
    first = lines[0]
    assert first["text"] == "Hello world"
    assert first["start_sec"] == pytest.approx(1.235)
    assert first["end_sec"] == pytest.approx(2.0)
    word = first["words"][0]
    assert word == {
        "word": "Hello",
        "start_sec": 1.235,
        "end_sec": 1.5,
        "confidence": 0.912,
    }


def test_assemble_skips_empty_text_segments():
    result = _result([("   ", []), ("Real", [("Real", 1.0, 1.5, 0.9)])])
    payload = assemble_lyrics_timing(
        duration_sec=10.0,
        mode="transcribed",
        language="en",
        text_source="none",
        model_name="large-v3",
        quality=_quality(),
        segments=result["segments"],
    )
    assert [line["text"] for line in payload["lines"]] == ["Real"]
    assert payload["lines"][0]["line_idx"] == 0


# ---- produce_lyrics_timing decision flow (seams monkeypatched, no torch) ----

GOOD_ALIGNED = _result(
    [("Hello world", [("Hello", 10.0, 10.5, 0.9), ("world", 10.5, 11.0, 0.9)])]
)
GOOD_TRANSCRIBED = _result(
    [
        (
            "ten good words in here for the gate to pass",
            [(f"w{i}", 10.0 + i, 10.5 + i, 0.9) for i in range(12)],
        )
    ],
    language="ja",
)
BAD_ALIGNED = _result(
    [("Hello world", [("Hello", 10.0, 10.0, 0.2), ("world", 10.0, 10.0, 0.2)])]
)


@pytest.fixture
def seams(monkeypatch):
    calls = {"align": 0, "transcribe": 0, "detect": 0}
    monkeypatch.setattr(lyrics_align, "_load_model", lambda name: object())
    monkeypatch.setattr(lyrics_align, "_audio_duration", lambda path: 200.0)

    def detect(model, path):
        calls["detect"] += 1
        return "en"

    monkeypatch.setattr(lyrics_align, "_detect_language", detect)
    return calls


def _set_align(monkeypatch, calls, result):
    def run(model, path, text, language):
        calls["align"] += 1
        return result

    monkeypatch.setattr(lyrics_align, "_run_align", run)


def _set_transcribe(monkeypatch, calls, result):
    def run(model, path):
        calls["transcribe"] += 1
        return result

    monkeypatch.setattr(lyrics_align, "_run_transcribe", run)


def test_produce_aligned_accepted(monkeypatch, seams):
    _set_align(monkeypatch, seams, GOOD_ALIGNED)
    _set_transcribe(monkeypatch, seams, GOOD_TRANSCRIBED)
    payload = produce_lyrics_timing("song.wav", "Hello world")
    assert payload["mode"] == "aligned"
    assert payload["text_source"] == "synced_lrc"
    assert payload["language"] == "en"
    assert seams["transcribe"] == 0


def test_produce_align_abort_falls_back_to_transcription(monkeypatch, seams):
    _set_align(monkeypatch, seams, None)
    _set_transcribe(monkeypatch, seams, GOOD_TRANSCRIBED)
    payload = produce_lyrics_timing("song.wav", "Hello world")
    assert payload["mode"] == "transcribed"
    assert payload["text_source"] == "none"
    assert payload["language"] == "ja"
    assert seams["align"] == 1


def test_produce_poor_alignment_falls_back_to_transcription(monkeypatch, seams):
    _set_align(monkeypatch, seams, BAD_ALIGNED)
    _set_transcribe(monkeypatch, seams, GOOD_TRANSCRIBED)
    payload = produce_lyrics_timing("song.wav", "Hello world")
    assert payload["mode"] == "transcribed"


def test_produce_no_text_goes_straight_to_transcription(monkeypatch, seams):
    _set_align(monkeypatch, seams, GOOD_ALIGNED)
    _set_transcribe(monkeypatch, seams, GOOD_TRANSCRIBED)
    payload = produce_lyrics_timing("song.wav", None)
    assert payload["mode"] == "transcribed"
    assert seams["align"] == 0
    assert seams["detect"] == 0


def test_produce_align_crash_falls_back_to_transcription(monkeypatch, seams):
    # A raising aligner (stable-ts TypeError on language=None, CUDA OOM, internal
    # errors) must behave like a rejected alignment, not abort the whole function.
    def crash(model, path, text, language):
        seams["align"] += 1
        raise TypeError("expected argument for language")

    monkeypatch.setattr(lyrics_align, "_run_align", crash)
    _set_transcribe(monkeypatch, seams, GOOD_TRANSCRIBED)
    payload = produce_lyrics_timing("song.wav", "Hello world")
    assert payload["mode"] == "transcribed"
    assert seams["align"] == 1


def test_assemble_tolerates_words_missing_timestamps():
    # The quality gate tolerates keyless words (counts them zero-duration), so
    # the assembler must not crash on the same shapes.
    segments = [
        {
            "start": 1.0,
            "end": 2.0,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "start": 1.0, "end": 1.4, "probability": 0.9},
                {"word": "world"},
            ],
        }
    ]
    payload = assemble_lyrics_timing(
        duration_sec=10.0,
        mode="aligned",
        language="en",
        text_source="synced_lrc",
        model_name="large-v3",
        quality=_quality(),
        segments=segments,
    )
    words = payload["lines"][0]["words"]
    assert words[1] == {"word": "world", "start_sec": 0.0, "end_sec": 0.0, "confidence": 0.0}


def test_produce_instrumental_returns_none(monkeypatch, seams):
    few_words = _result([("hm", [("hm", 10.0, 10.5, 0.9)])])
    _set_align(monkeypatch, seams, None)
    _set_transcribe(monkeypatch, seams, few_words)
    assert produce_lyrics_timing("song.wav", "some lyrics") is None


def test_produce_low_confidence_transcription_returns_none(monkeypatch, seams):
    noisy = _result(
        [("blah", [(f"w{i}", 10.0 + i, 10.5 + i, 0.2) for i in range(12)])]
    )
    _set_align(monkeypatch, seams, None)
    _set_transcribe(monkeypatch, seams, noisy)
    assert produce_lyrics_timing("song.wav", "some lyrics") is None
