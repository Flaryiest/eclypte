from api.prototyping.edit.index import query as query_module


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
