from unittest.mock import MagicMock, patch

from api.prototyping.edit.index import query as query_module


def test_query_clips():
    query_module._QUERY_FUNC = None
    with patch("api.prototyping.edit.index.query.modal.Function.from_name") as mock_lookup:
        mock_func = MagicMock()
        mock_lookup.return_value = mock_func

        mock_func.remote.return_value = [
            {"timestamp": 12.0, "score": 0.95},
            {"timestamp": 15.0, "score": 0.85},
        ]

        results = query_module.query_clips("test query", "dummy.mp4", top_k=2)
        assert len(results) == 2
        mock_func.remote.assert_called_with("test query", "dummy.mp4", 2)
        assert mock_lookup.call_count == 1


def test_query_ranges_time_window_filters_by_position():
    scenes = [
        {"index": 0, "start_sec": 0.0, "end_sec": 10.0, "duration_sec": 10.0,
         "motion": {"avg_intensity": 0.5}},
        {"index": 1, "start_sec": 90.0, "end_sec": 100.0, "duration_sec": 10.0,
         "motion": {"avg_intensity": 0.5}},
    ]

    # A window near the end of the source must only return the late scene,
    # which is how the planner spans the full source for short songs.
    late = query_module.query_ranges(
        scenes, section={}, query_text="", energy_target=0.5, time_window=(80.0, 110.0)
    )
    assert [r["scene_index"] for r in late] == [1]

    # No window keeps the original position-blind behavior (both scenes).
    both = query_module.query_ranges(
        scenes, section={}, query_text="", energy_target=0.5
    )
    assert {r["scene_index"] for r in both} == {0, 1}


def test_rank_with_content_filter_excludes_dead_frames():
    timestamps = [0.0, 1.0, 2.0, 3.0]
    # Frame 1 has the top similarity but is near-black; frame 2 is high-sim but flat
    # (a title card). Both must be dropped; the real frames (0 and 3) survive.
    similarities = [0.5, 0.99, 0.95, 0.6]
    brightness = [120.0, 4.0, 200.0, 90.0]  # frame 1 black
    detail = [40.0, 35.0, 3.0, 30.0]  # frame 2 flat/solid

    results = query_module.rank_with_content_filter(
        timestamps, similarities, brightness, detail, top_k=3
    )
    returned = [r["timestamp"] for r in results]

    assert 1.0 not in returned  # black frame dropped despite top similarity
    assert 2.0 not in returned  # flat title card dropped
    assert set(returned) == {3.0, 0.0}
    assert returned[0] == 3.0  # best surviving frame first


def test_rank_with_content_filter_without_signals_keeps_all():
    # Older index lacking brightness/detail → no filtering, pure similarity order.
    results = query_module.rank_with_content_filter(
        [0.0, 1.0], [0.3, 0.9], None, None, top_k=2
    )
    assert [r["timestamp"] for r in results] == [1.0, 0.0]
