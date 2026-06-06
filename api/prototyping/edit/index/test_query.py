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
