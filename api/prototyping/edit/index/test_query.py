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


def test_text_negative_sims_drop_title_card_frames():
    from api.prototyping.edit.index.query import TEXT_NEG_THRESHOLD, rank_with_content_filter

    timestamps = [10.0, 20.0, 30.0]
    sims = [0.30, 0.28, 0.26]
    # frame 1 is a bright title card: strongly similar to the negative text
    # prompts AND more "texty" than it is on-query -> dropped despite ranking
    # second by raw similarity.
    neg = [0.10, TEXT_NEG_THRESHOLD + 0.05, 0.12]
    results = rank_with_content_filter(
        timestamps, sims,
        brightness=[120.0, 200.0, 90.0], detail=[40.0, 60.0, 35.0],
        text_negative_sims=neg, top_k=3,
    )
    assert [r["timestamp"] for r in results] == [10.0, 30.0]


def test_text_negative_sims_keep_content_that_merely_mentions_text():
    from api.prototyping.edit.index.query import TEXT_NEG_THRESHOLD, rank_with_content_filter

    # A frame can be somewhat similar to the negative prompts but MORE similar
    # to the actual query (real content with incidental text) -> kept.
    results = rank_with_content_filter(
        [10.0], [0.35],
        brightness=[120.0], detail=[40.0],
        text_negative_sims=[TEXT_NEG_THRESHOLD + 0.02], top_k=1,
    )
    assert [r["timestamp"] for r in results] == [10.0]


def test_text_negative_sims_below_threshold_never_drop():
    from api.prototyping.edit.index.query import TEXT_NEG_THRESHOLD, rank_with_content_filter

    results = rank_with_content_filter(
        [10.0], [0.05],  # weak on-query match, but neg is below the floor
        brightness=[120.0], detail=[40.0],
        text_negative_sims=[TEXT_NEG_THRESHOLD - 0.05], top_k=1,
    )
    assert [r["timestamp"] for r in results] == [10.0]


def test_text_negative_sims_absent_keeps_old_behavior():
    from api.prototyping.edit.index.query import rank_with_content_filter

    results = rank_with_content_filter(
        [10.0, 20.0], [0.3, 0.2], brightness=[120.0, 120.0], detail=[40.0, 40.0], top_k=2
    )
    assert len(results) == 2
