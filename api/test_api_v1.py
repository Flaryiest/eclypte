from api.storage.keys import file_version_blob_key
from api.storage.refs import FileRef, RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingWorkflowRunner:
    def __init__(self):
        self.calls = []

    def run_music_analysis(self, **kwargs):
        self.calls.append(("music", kwargs))

    def run_youtube_song_import(self, **kwargs):
        self.calls.append(("youtube_song_import", kwargs))

    def run_video_analysis(self, **kwargs):
        self.calls.append(("video", kwargs))

    def run_timeline_plan(self, **kwargs):
        self.calls.append(("timeline", kwargs))

    def run_render(self, **kwargs):
        self.calls.append(("render", kwargs))

    def run_synthesis_reference_ingest(self, **kwargs):
        self.calls.append(("synthesis_reference", kwargs))

    def run_synthesis_consolidation(self, **kwargs):
        self.calls.append(("synthesis_consolidation", kwargs))


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

    assert health.json() == {"ok": True, "youtube_cookies_configured": False}
    assert preflight.headers["access-control-allow-origin"] == "https://eclypte.vercel.app"


def test_health_reports_youtube_cookies_configuration(monkeypatch):
    monkeypatch.setenv("ECLYPTE_YOUTUBE_COOKIES_B64", "abc123")
    client, _, _ = build_client()

    health = client.get("/healthz")

    assert health.status_code == 200
    assert health.json()["youtube_cookies_configured"] is True


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


def test_timeline_endpoint_defaults_to_agent_planning_and_accepts_creative_brief():
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
        content_type="application/json",
    )
    video_analysis = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video_analysis",
        kind="video_analysis",
        filename="source.json",
        content_type="application/json",
    )

    response = client.post(
        "/v1/timelines",
        headers={"X-User-Id": "user_123"},
        json={
            "audio": audio,
            "source_video": video,
            "music_analysis": music_analysis,
            "video_analysis": video_analysis,
            "creative_brief": "Open with the strongest action beat.",
        },
    )

    assert response.status_code == 202
    assert response.json()["workflow_type"] == "timeline_agent_plan"
    assert [step["name"] for step in response.json()["steps"]] == [
        "ensure_clip_index",
        "agent_plan_timeline",
        "publish_timeline",
    ]
    assert runner.calls[-1][0] == "timeline"
    assert runner.calls[-1][1]["planning_mode"] == "agent"
    assert runner.calls[-1][1]["creative_brief"] == "Open with the strongest action beat."


def test_timeline_endpoint_supports_deterministic_opt_out():
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
        content_type="application/json",
    )
    video_analysis = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video_analysis",
        kind="video_analysis",
        filename="source.json",
        content_type="application/json",
    )

    response = client.post(
        "/v1/timelines",
        headers={"X-User-Id": "user_123"},
        json={
            "audio": audio,
            "source_video": video,
            "music_analysis": music_analysis,
            "video_analysis": video_analysis,
            "planning_mode": "deterministic",
            "creative_brief": "Ignored in deterministic mode.",
        },
    )

    assert response.status_code == 202
    assert response.json()["workflow_type"] == "timeline_plan"
    assert [step["name"] for step in response.json()["steps"]] == [
        "plan_timeline",
        "publish_timeline",
    ]
    assert runner.calls[-1][1]["planning_mode"] == "deterministic"


def test_youtube_song_import_endpoint_creates_run_and_schedules_background_task():
    client, _, runner = build_client()

    response = client.post(
        "/v1/music/youtube-imports",
        headers={"X-User-Id": "user_123"},
        json={"url": "https://www.youtube.com/watch?v=abc123"},
    )

    assert response.status_code == 202
    assert response.json()["workflow_type"] == "youtube_song_import"
    assert response.json()["inputs"]["youtube_url"] == "https://www.youtube.com/watch?v=abc123"
    assert [call[0] for call in runner.calls] == ["youtube_song_import"]
    assert runner.calls[0][1]["url"] == "https://www.youtube.com/watch?v=abc123"


def test_youtube_song_import_rejects_non_youtube_url():
    client, _, runner = build_client()

    response = client.post(
        "/v1/music/youtube-imports",
        headers={"X-User-Id": "user_123"},
        json={"url": "https://example.com/audio"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "expected a YouTube URL"
    assert runner.calls == []


def test_assets_list_marks_youtube_imported_song_ready_with_analysis():
    client, store, _ = build_client()
    repo = StorageRepository(store)
    audio = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_audio",
        kind="song_audio",
        filename="Imported Song.wav",
        content_type="audio/wav",
    )
    analysis = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_analysis",
        kind="music_analysis",
        filename="Imported Song.wav.json",
        body=b"{}",
        content_type="application/json",
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="youtube_song_import",
        inputs={"youtube_url": "https://www.youtube.com/watch?v=abc123"},
        steps=["download_youtube_audio", "publish_audio", "analyze_music", "publish_analysis"],
    )
    repo.update_run_status(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        status="completed",
        outputs={
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "music_analysis_file_id": analysis["file_id"],
            "music_analysis_version_id": analysis["version_id"],
        },
    )

    response = client.get(
        "/v1/assets?kind=song_audio",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 200
    assert response.json()[0]["analysis"] == analysis
    assert response.json()[0]["latest_run"]["workflow_type"] == "youtube_song_import"


def test_assets_list_returns_current_version_metadata_and_kind_filter():
    client, store, _ = build_client()
    repo = StorageRepository(store)
    audio = publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_audio",
        kind="song_audio",
        filename="song.wav",
        body=b"song",
        content_type="audio/wav",
    )
    publish_artifact(
        repo,
        user_id="user_123",
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        body=b"video",
        content_type="video/mp4",
    )

    response = client.get(
        "/v1/assets?kind=song_audio",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "file_id": "file_audio",
            "kind": "song_audio",
            "display_name": "song.wav",
            "current_version_id": audio["version_id"],
            "created_at": response.json()[0]["created_at"],
            "updated_at": response.json()[0]["updated_at"],
            "source_run_id": None,
            "tags": [],
            "current_version": {
                "version_id": audio["version_id"],
                "file_id": "file_audio",
                "owner_user_id": "user_123",
                "content_type": "audio/wav",
                "size_bytes": 4,
                "sha256": response.json()[0]["current_version"]["sha256"],
                "original_filename": "song.wav",
                "created_at": response.json()[0]["current_version"]["created_at"],
                "created_by_step": "test",
                "storage_key": response.json()[0]["current_version"]["storage_key"],
                "derived_from": response.json()[0]["current_version"]["derived_from"],
            },
            "latest_run": None,
            "analysis": None,
        }
    ]


def test_runs_list_supports_workflow_and_status_filters():
    client, store, _ = build_client()
    repo = StorageRepository(store)
    music = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": "ver_audio"},
        steps=["analyze_music", "publish_analysis"],
    )
    repo.create_run(
        user_id="user_123",
        workflow_type="render",
        inputs={"timeline_version_id": "ver_timeline"},
        steps=["render", "publish_render"],
    )

    response = client.get(
        "/v1/runs?workflow_type=music_analysis&status=running",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 200
    assert [run["run_id"] for run in response.json()] == [music.run_id]


def test_synthesis_reference_submission_persists_queue_records_and_schedules_ingest():
    client, _, runner = build_client()

    response = client.post(
        "/v1/synthesis/references",
        headers={"X-User-Id": "user_123"},
        json={"urls": ["https://www.instagram.com/reel/example/"]},
    )
    listed = client.get(
        "/v1/synthesis/references",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 201
    assert response.json()[0]["url"] == "https://www.instagram.com/reel/example/"
    assert response.json()[0]["status"] == "queued"
    assert listed.json()[0]["reference_id"] == response.json()[0]["reference_id"]
    assert runner.calls[-1][0] == "synthesis_reference"
    assert runner.calls[-1][1]["reference_id"] == response.json()[0]["reference_id"]


def test_synthesis_prompt_versions_can_be_saved_and_activated():
    client, _, _ = build_client()

    default_state = client.get(
        "/v1/synthesis/prompt",
        headers={"X-User-Id": "user_123"},
    )
    saved = client.post(
        "/v1/synthesis/prompt/versions",
        headers={"X-User-Id": "user_123"},
        json={
            "label": "Sharper hook",
            "prompt_text": "Open with a fast, clear hook.",
            "source_reference_ids": ["ref_001"],
        },
    )
    version_id = saved.json()["active_version_id"]
    reverted = client.post(
        f"/v1/synthesis/prompt/versions/{default_state.json()['active_version_id']}/activate",
        headers={"X-User-Id": "user_123"},
    )

    assert default_state.status_code == 200
    assert default_state.json()["active_version_id"] == "default"
    assert saved.status_code == 201
    assert saved.json()["active_prompt"]["version_id"] == version_id
    assert saved.json()["active_prompt"]["prompt_text"] == "Open with a fast, clear hook."
    assert reverted.status_code == 200
    assert reverted.json()["active_version_id"] == "default"


def test_synthesis_consolidation_creates_run_and_schedules_prompt_update():
    client, _, runner = build_client()

    response = client.post(
        "/v1/synthesis/consolidations",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 202
    assert response.json()["workflow_type"] == "synthesis_consolidation"
    assert runner.calls[-1][0] == "synthesis_consolidation"
    assert runner.calls[-1][1]["run_id"] == response.json()["run_id"]


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
