import pytest

from api.prototyping.video.credits import decide_content_end


def _samples(duration, texty_ranges, *, fps=1.0, texty_words=20, base_words=1):
    """Build [(timestamp_sec, word_count)] at `fps`, high word counts inside ranges."""
    out = []
    n = int(round(duration * fps))
    for i in range(n + 1):
        ts = round(i / fps, 3)
        wc = base_words
        for start, end in texty_ranges:
            if start <= ts < end:
                wc = texty_words
                break
        out.append((ts, wc))
    return out


def test_clear_end_credits_trims_30s_before():
    samples = _samples(600.0, [(540.0, 600.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is True
    assert result["credits_start_sec"] == pytest.approx(540.0, abs=1.5)
    assert result["content_end_sec"] == pytest.approx(510.0, abs=1.5)


def test_no_text_means_no_trim():
    samples = _samples(600.0, [])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is False
    assert result["content_end_sec"] == pytest.approx(600.0)


def test_brief_end_title_is_not_credits():
    # Only the last 10s has text — shorter than MIN_CREDITS_SEC.
    samples = _samples(600.0, [(590.0, 600.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is False
    assert result["content_end_sec"] == pytest.approx(600.0)


def test_midfilm_text_block_is_ignored():
    # Text mid-film, none near the end -> not credits.
    samples = _samples(600.0, [(200.0, 280.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is False
    assert result["content_end_sec"] == pytest.approx(600.0)


def test_black_gaps_within_credits_are_bridged():
    # Credits with a short non-text gap (black between credit cards).
    samples = _samples(600.0, [(540.0, 560.0), (566.0, 598.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is True
    assert result["credits_start_sec"] == pytest.approx(540.0, abs=1.5)
    assert result["content_end_sec"] == pytest.approx(510.0, abs=1.5)


def test_credits_starting_too_early_are_distrusted():
    # Texty from the midpoint -> below the 0.6*duration guardrail -> no trim.
    samples = _samples(600.0, [(300.0, 600.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is False
    assert result["content_end_sec"] == pytest.approx(600.0)


def test_content_end_never_below_floor():
    # credits_start - 30 would fall below 0.5*duration -> clamped to the floor.
    samples = _samples(100.0, [(62.0, 100.0)])
    result = decide_content_end(samples, 100.0)
    assert result["credits_detected"] is True
    assert result["content_end_sec"] == pytest.approx(50.0)


def test_black_tail_after_credits_still_detected():
    # Credits 540-592, then a black tail with no text to the end.
    samples = _samples(600.0, [(540.0, 592.0)])
    result = decide_content_end(samples, 600.0)
    assert result["credits_detected"] is True
    assert result["content_end_sec"] == pytest.approx(510.0, abs=1.5)


def test_empty_samples_no_trim():
    result = decide_content_end([], 600.0)
    assert result["credits_detected"] is False
    assert result["content_end_sec"] == pytest.approx(600.0)
