import json
import sys
from types import SimpleNamespace
import urllib.error

from api.prototyping.progress_events import emit_progress


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


def test_emit_progress_scales_percent_range(monkeypatch):
    writes = []

    class FakeS3Client:
        def put_object(self, **kwargs):
            writes.append(kwargs)

    fake_boto3 = SimpleNamespace(client=lambda *_args, **_kwargs: FakeS3Client())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    emit_progress(
        {
            "r2_config": {
                "bucket": "test-bucket",
                "endpoint_url": "https://example.test",
                "access_key_id": "access",
                "secret_access_key": "secret",
            },
            "user_id": "user_123",
            "run_id": "run_parent",
            "stage": "timeline",
            "percent_start": 10,
            "percent_end": 35,
        },
        60,
        "Embedded frames",
    )

    body = json.loads(writes[0]["Body"].decode("utf-8"))
    assert body["payload"] == {
        "stage": "timeline",
        "percent": 25,
        "detail": "Embedded frames",
    }


def test_emit_progress_posts_to_internal_api_before_r2(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    fake_boto3 = SimpleNamespace(
        client=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("R2 fallback used"))
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr("api.prototyping.progress_events.urllib.request.urlopen", fake_urlopen)

    emit_progress(
        {
            "progress_api_url": "https://api.example.test/internal/progress",
            "progress_token": "secret-token",
            "r2_config": {
                "bucket": "test-bucket",
                "endpoint_url": "https://example.test",
                "access_key_id": "access",
                "secret_access_key": "secret",
            },
            "user_id": "user_123",
            "run_id": "run_parent",
            "stage": "render",
            "percent_start": 35,
            "percent_end": 95,
        },
        50,
        "Encoding MP4",
    )

    request, timeout = requests[0]
    body = json.loads(request.data.decode("utf-8"))
    assert timeout == 5
    assert request.full_url == "https://api.example.test/internal/progress"
    assert request.headers["X-eclypte-internal-token"] == "secret-token"
    assert body == {
        "user_id": "user_123",
        "run_id": "run_parent",
        "stage": "render",
        "percent": 65,
        "detail": "Encoding MP4",
    }


def test_emit_progress_falls_back_to_r2_when_internal_api_fails(monkeypatch):
    writes = []

    class FakeS3Client:
        def put_object(self, **kwargs):
            writes.append(kwargs)

    fake_boto3 = SimpleNamespace(client=lambda *_args, **_kwargs: FakeS3Client())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(
        "api.prototyping.progress_events.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("unavailable")
        ),
    )

    emit_progress(
        {
            "progress_api_url": "https://api.example.test/internal/progress",
            "progress_token": "secret-token",
            "r2_config": {
                "bucket": "test-bucket",
                "endpoint_url": "https://example.test",
                "access_key_id": "access",
                "secret_access_key": "secret",
            },
            "user_id": "user_123",
            "run_id": "run_parent",
            "stage": "video",
        },
        30,
        "Detecting scenes",
    )

    body = json.loads(writes[0]["Body"].decode("utf-8"))
    assert body["payload"] == {
        "stage": "video",
        "percent": 30,
        "detail": "Detecting scenes",
    }
