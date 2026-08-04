import json

import pytest

from api.instagram_graph import (
    GraphApiError,
    GraphConfig,
    GraphConfigError,
    GraphPublisher,
    build_reel_container_params,
    parse_insights,
)


def test_reel_container_params_minimal():
    params = build_reel_container_params(
        video_url="https://cdn.example/reel.mp4", caption="hi\n#tag"
    )
    assert params == {
        "media_type": "REELS",
        "video_url": "https://cdn.example/reel.mp4",
        "caption": "hi\n#tag",
        "share_to_feed": "true",
    }


def test_reel_container_params_full():
    params = build_reel_container_params(
        video_url="https://cdn.example/reel.mp4",
        caption="c",
        cover_url="https://cdn.example/poster.jpg",
        audio_name="Song — Artist",
        audio_config={"audio_id": "123"},
    )
    assert params["cover_url"] == "https://cdn.example/poster.jpg"
    assert params["audio_name"] == "Song — Artist"
    assert json.loads(params["audio_configuration"]) == {"audio_id": "123"}


def test_graph_config_requires_env(monkeypatch):
    monkeypatch.delenv("ECLYPTE_IG_USER_ID", raising=False)
    monkeypatch.delenv("ECLYPTE_IG_ACCESS_TOKEN", raising=False)
    with pytest.raises(GraphConfigError):
        GraphConfig.from_env()


def test_graph_config_from_env(monkeypatch):
    monkeypatch.setenv("ECLYPTE_IG_USER_ID", "1789")
    monkeypatch.setenv("ECLYPTE_IG_ACCESS_TOKEN", "tok")
    monkeypatch.delenv("ECLYPTE_GRAPH_API_BASE", raising=False)
    config = GraphConfig.from_env()
    assert config.ig_user_id == "1789"
    assert config.access_token == "tok"
    assert config.api_base.startswith("https://graph.facebook.com/")


class RecordingPublisher(GraphPublisher):
    """GraphPublisher with the HTTP layer replaced by a scripted transport."""

    def __init__(self, responses):
        super().__init__(GraphConfig(ig_user_id="1789", access_token="tok"))
        self.requests = []
        self._responses = list(responses)

    def _request(self, method, path, params):
        self.requests.append((method, path, dict(params)))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_create_poll_publish_flow():
    publisher = RecordingPublisher(
        [
            {"id": "container_1"},
            {"status_code": "IN_PROGRESS", "copyright_check_status": {"status": "in_progress"}},
            {
                "status_code": "FINISHED",
                "copyright_check_status": {"status": "completed", "matches_found": False},
            },
            {"id": "media_1"},
        ]
    )

    container_id = publisher.create_reel_container(
        video_url="https://cdn.example/reel.mp4", caption="c"
    )
    assert container_id == "container_1"
    status = publisher.wait_for_container(container_id, timeout_sec=30, sleep=lambda _s: None)
    assert status["status_code"] == "FINISHED"
    media_id = publisher.publish_container(container_id)
    assert media_id == "media_1"

    methods_paths = [(m, p) for m, p, _ in publisher.requests]
    assert methods_paths[0] == ("POST", "/1789/media")
    assert methods_paths[-1] == ("POST", "/1789/media_publish")
    # The publish call references the finished container.
    assert publisher.requests[-1][2]["creation_id"] == "container_1"


def test_wait_for_container_raises_on_error_status():
    publisher = RecordingPublisher([{"status_code": "ERROR"}])
    with pytest.raises(GraphApiError):
        publisher.wait_for_container("c1", timeout_sec=30, sleep=lambda _s: None)


def test_parse_insights_tolerant_absent_is_never_zero():
    payload = {
        "data": [
            {"name": "views", "values": [{"value": 1200}]},
            {"name": "likes", "total_value": {"value": 88}},
            {"name": "reach", "values": []},  # malformed/empty -> skipped
            {"values": [{"value": 5}]},  # nameless -> skipped
        ]
    }
    metrics = parse_insights(payload)
    assert metrics == {"views": 1200.0, "likes": 88.0}
    assert "reach" not in metrics
