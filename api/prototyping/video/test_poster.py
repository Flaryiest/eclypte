from api.prototyping.video.poster import (
    POSTER_SAMPLE_EVERY_SEC,
    PosterPicker,
    score_poster_candidate,
)


def test_rejects_dark_flat_and_blown_out_frames():
    assert score_poster_candidate(0.2, brightness=10.0, detail=50.0) is None  # near-black
    assert score_poster_candidate(0.2, brightness=240.0, detail=50.0) is None  # blown out / credits-white
    assert score_poster_candidate(0.2, brightness=120.0, detail=5.0) is None  # flat / title card


def test_prefers_frames_near_the_target_fraction():
    early = score_poster_candidate(0.06, brightness=120.0, detail=40.0)
    on_target = score_poster_candidate(0.20, brightness=120.0, detail=40.0)
    late = score_poster_candidate(0.44, brightness=120.0, detail=40.0)
    assert on_target is not None and early is not None and late is not None
    assert on_target > early
    assert on_target > late


def test_ignores_frames_outside_the_window():
    assert score_poster_candidate(0.01, brightness=120.0, detail=40.0) is None
    assert score_poster_candidate(0.80, brightness=120.0, detail=40.0) is None


def test_picker_keeps_the_best_candidate_across_a_stream():
    picker = PosterPicker(duration_sec=100.0)
    assert picker.consider(10.0, brightness=120.0, detail=20.0) is True  # first acceptable
    assert picker.consider(15.0, brightness=15.0, detail=60.0) is False  # too dark
    assert picker.consider(20.0, brightness=130.0, detail=45.0) is True  # better: on target + detailed
    assert picker.consider(30.0, brightness=130.0, detail=30.0) is False  # worse than current best
    assert picker.best_ts_sec == 20.0


def test_picker_with_no_acceptable_frames_has_no_best():
    picker = PosterPicker(duration_sec=100.0)
    assert picker.consider(20.0, brightness=5.0, detail=2.0) is False
    assert picker.best_ts_sec is None


def test_sample_interval_is_positive():
    assert POSTER_SAMPLE_EVERY_SEC > 0
