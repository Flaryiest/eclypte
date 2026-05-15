import pytest


def test_parse_import_candidate_accepts_collection_song_and_normalizes_output_name():
    from api.auto_import import parse_import_candidate

    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/mario/songs/Hero Theme.MP3",
        etag="abc123",
        size_bytes=1234,
    )

    assert candidate.collection_slug == "mario"
    assert candidate.media_role == "song"
    assert candidate.kind == "song_audio"
    assert candidate.source_key == "incoming/collections/mario/songs/Hero Theme.MP3"
    assert candidate.output_filename == "Hero Theme.wav"
    assert candidate.output_content_type == "audio/wav"
    assert candidate.run_inputs()["source_etag"] == "abc123"


def test_parse_import_candidate_accepts_collection_video_and_normalizes_output_name():
    from api.auto_import import parse_import_candidate

    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/mario/videos/episode 01.mkv",
        etag="def456",
        size_bytes=9876,
    )

    assert candidate.collection_slug == "mario"
    assert candidate.media_role == "video"
    assert candidate.kind == "source_video"
    assert candidate.output_filename == "episode 01.mp4"
    assert candidate.output_content_type == "video/mp4"


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("incoming/random/song.mp3", "incoming/collections"),
        ("incoming/collections/mario/images/frame.jpg", "songs/ or videos/"),
        ("incoming/collections/mario/songs/readme.txt", "unsupported audio suffix"),
        ("incoming/collections/mario/videos/source.avi", "unsupported video suffix"),
    ],
)
def test_parse_import_candidate_rejects_unsupported_keys(key, message):
    from api.auto_import import UnsupportedImportObject, parse_import_candidate

    with pytest.raises(UnsupportedImportObject, match=message):
        parse_import_candidate(
            bucket="eclypte",
            key=key,
            etag="etag",
            size_bytes=1,
        )
