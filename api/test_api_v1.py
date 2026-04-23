from api.storage.keys import file_version_blob_key
from api.storage.refs import FileRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingWorkflowRunner:
    def __init__(self):
        self.calls = []

    def run_music_analysis(self, **kwargs):
        self.calls.append(("music", kwargs))

    def run_video_analysis(self, **kwargs):
        self.calls.append(("video", kwargs))

    def run_timeline_plan(self, **kwargs):
        self.calls.append(("timeline", kwargs))

    def run_render(self, **kwargs):
        self.calls.append(("render", kwargs))


def build_client():
    from fastapi.testclient import TestClient
    from api.app import create_app

    store = InMemoryObjectStore()
    runner = RecordingWorkflowRunner()
    app = create_app(
        store=store,
        workflow_runner=runner,
        cors_origins=["https://eclypte.vercel.app", "http://localhost:3000"],
    )
    return TestClient(app), store, runner


def publish_artifact(repo, *, user_id, file_id, kind, filename, body=b"data", content_type="application/octet-stream"):
    file_ref = FileRef(user_id=user_id, file_id=file_id)
    repo.create_file_manifest(file_ref=file_ref, kind=kind, display_name=filename)
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=body,
        content_type=content_type,
        original_filename=filename,
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    return {"file_id": file_id, "version_id": version_ref.version_id}


def test_health_and_cors_allow_vercel_origin():
    client, _, _ = build_client()

    health = client.get("/healthz")
    preflight = client.options(
        "/v1/uploads",
        headers={
            "Origin": "https://eclypte.vercel.app",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert health.json() == {"ok": True}
    assert preflight.headers["access-control-allow-origin"] == "https://eclypte.vercel.app"


def test_direct_upload_create_complete_metadata_and_download_url():
    client, store, _ = build_client()

    created = client.post(
        "/v1/uploads",
        headers={"X-User-Id": "user_123"},
        json={
            "kind": "song_audio",
            "filename": "song.wav",
            "content_type": "audio/wav",
            "size_bytes": 4,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["upload_url"].startswith("memory://put/")
    assert body["required_headers"]["Content-Type"] == "audio/wav"

    blob_key = file_version_blob_key(
        user_id="user_123",
        file_id=body["file_id"],
        version_id=body["version_id"],
    )
    store.put_bytes(blob_key, b"song", content_type="audio/wav")

    completed = client.post(
        f"/v1/uploads/{body['upload_id']}/complete",
        headers={"X-User-Id": "user_123"},
        json={"sha256": "b" * 64},
    )
    meta = client.get(
        f"/v1/files/{body['file_id']}/versions/{body['version_id']}",
        headers={"X-User-Id": "user_123"},
    )
    download = client.get(
        f"/v1/files/{body['file_id']}/versions/{body['version_id']}/download-url",
        headers={"X-User-Id": "user_123"},
    )

    assert completed.status_code == 200
    assert meta.json()["sha256"] == "b" * 64
    assert download.json()["download_url"].startswith("memory://get/")


def test_completing_upload_before_object_exists_returns_clear_error():
    client, _, _ = build_client()

    created = client.post(
        "/v1/uploads",
        headers={"X-User-Id": "user_123"},
        json={
            "kind": "source_video",
            "filename": "source.mp4",
            "content_type": "video/mp4",
        },
    )
    response = client.post(
        f"/v1/uploads/{created.json()['upload_id']}/complete",
        headers={"X-User-Id": "user_123"},
        json={"sha256": "c" * 64},
    )

    assert response.status_code == 400
    assert "has not been uploaded" in response.json()["detail"]


def test_workflow_endpoints_create_runs_and_schedule_background_tasks():
    client, store, runner = build_client()
    repo = StorageRepository(store)
    audio = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_audio",
        kind="song_audio",
        filename="song.wav",
        content_type="audio/wav",
    )
    video = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        content_type="video/mp4",
    )
    music_analysis = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_music_analysis",
        kind="music_analysis",
        filename="song.json",
        body=b"{}",
        content_type="application/json",
    )
    video_analysis = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video_analysis",
        kind="video_analysis",
        filename="source.json",
        body=b'{"scenes":[]}',
        content_type="application/json",
    )
    timeline_artifact = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_timeline",
        kind="timeline",
        filename="timeline.json",
        body=b"{}",
        content_type="application/json",
    )

    music = client.post(
        "/v1/music/analyses",
        headers={"X-User-Id": "user_123"},
        json={"audio": audio},
    )
    video_resp = client.post(
        "/v1/video/analyses",
        headers={"X-User-Id": "user_123"},
        json={"source_video": video},
    )
    timeline = client.post(
        "/v1/timelines",
        headers={"X-User-Id": "user_123"},
        json={
            "audio": audio,
            "source_video": video,
            "music_analysis": music_analysis,
            "video_analysis": video_analysis,
        },
    )
    render = client.post(
        "/v1/renders",
        headers={"X-User-Id": "user_123"},
        json={
            "timeline": timeline_artifact,
            "audio": audio,
            "source_video": video,
        },
    )

    assert music.status_code == 202
    assert video_resp.status_code == 202
    assert timeline.status_code == 202
    assert render.status_code == 202
    assert [call[0] for call in runner.calls] == ["music", "video", "timeline", "render"]
    run = client.get(f"/v1/runs/{music.json()['run_id']}", headers={"X-User-Id": "user_123"})
    events = client.get(
        f"/v1/runs/{music.json()['run_id']}/events",
        headers={"X-User-Id": "user_123"},
    )
    assert run.json()["status"] == "running"
    assert events.json()[0]["event_type"] == "run_created"


def test_missing_storage_configuration_returns_503(monkeypatch):
    import api.app
    from fastapi.testclient import TestClient
    from api.app import create_app

    monkeypatch.setattr(api.app, "get_object_store", lambda *, required=False: None)

    client = TestClient(create_app(workflow_runner=RecordingWorkflowRunner()))

    response = client.post(
        "/v1/uploads",
        json={
            "kind": "song_audio",
            "filename": "song.wav",
            "content_type": "audio/wav",
        },
    )

    assert response.status_code == 503


def test_invalid_artifact_kind_is_rejected_for_music_analysis():
    client, store, _ = build_client()
    repo = StorageRepository(store)
    video = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        content_type="video/mp4",
    )

    response = client.post(
        "/v1/music/analyses",
        headers={"X-User-Id": "user_123"},
        json={"audio": video},
    )

    assert response.status_code == 400
    assert "expected song_audio" in response.json()["detail"]
