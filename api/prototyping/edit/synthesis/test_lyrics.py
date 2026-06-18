import pytest

from api.prototyping.edit.synthesis.lyrics import expand_lyrics_overlays, parse_lrc


# ---- parse_lrc ----

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


# ---- expand_lyrics_overlays ----

def test_expand_offsets_lines_into_window():
    lines = [(10.0, "A"), (12.0, "B"), (14.0, "C")]
    overlays = expand_lyrics_overlays(lines, 10.0, 16.0, max_line_sec=5.0)
    assert overlays == [
        {"skill_id": "text.lyric", "text": "A", "start_time": 0.0, "end_time": 2.0},
        {"skill_id": "text.lyric", "text": "B", "start_time": 2.0, "end_time": 4.0},
        {"skill_id": "text.lyric", "text": "C", "start_time": 4.0, "end_time": 6.0},
    ]


def test_expand_excludes_lines_outside_window():
    lines = [(5.0, "before"), (11.0, "in"), (20.0, "after")]
    overlays = expand_lyrics_overlays(lines, 10.0, 15.0, max_line_sec=5.0)
    assert [o["text"] for o in overlays] == ["in"]
    assert overlays[0]["start_time"] == pytest.approx(1.0)
    assert overlays[0]["end_time"] == pytest.approx(5.0)  # clipped at window end


def test_expand_caps_line_duration():
    overlays = expand_lyrics_overlays([(10.0, "long")], 10.0, 30.0, max_line_sec=5.0)
    assert overlays[0]["end_time"] == pytest.approx(5.0)


def test_expand_empty_when_no_lines_in_window():
    assert expand_lyrics_overlays([(5.0, "x")], 10.0, 20.0) == []


def test_expand_no_lines():
    assert expand_lyrics_overlays([], 0.0, 10.0) == []
