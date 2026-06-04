from fastapi.testclient import TestClient

from api.app import create_app
from api.publishing import (
    BufferClientError,
    BufferPostResult,
    build_buffer_create_post_payload,
    create_publish_post_for_render,
    generate_caption_draft,
    prepare_public_media_copy,
)
from api.storage.refs import FileRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingBufferClient:
    def __init__(self):
        self.calls = []
        self.channel_calls = []

    def create_video_post(self, *, channel_id, text, media_url, mode, due_at=None):
        self.calls.append(
            {
                "channel_id": channel_id,
                "text": text,
                "media_url": media_url,
                "mode": mode,
                "due_at": due_at,
            }
        )
        return BufferPostResult(
            post_id="buf_123",
            status="buffer",
            post_url="https://publish.buffer.com/post/buf_123",
        )

    def get_channel(self, *, channel_id):
        self.channel_calls.append(channel_id)
        return {
            "id": channel_id,
            "name": "Eclypte IG",
            "service": "instagram",
            "display_name": "@eclypte",
            "is_disconnected": False,
            "is_locked": False,
            "external_link": "https://instagram.com/eclypte",
        }


class FailingBufferClient(RecordingBufferClient):
    def create_video_post(self, **kwargs):
        raise BufferClientError("Buffer rejected the media URL")

    def get_channel(self, *, channel_id):
        raise BufferClientError("Buffer channel lookup failed")


class FakeCaptionResponse:
    output_text = '{"caption":"This final clash goes wild.","hashtags":["#amv","#finalbattle"],"notes":"Generated from render metadata."}'


class FakeOpenAIClient:
    def __init__(self):
        self.responses = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCaptionResponse()


class NoopWorkflowRunner:
    def run_music_analysis(self, **kwargs): ...
    def run_youtube_song_import(self, **kwargs): ...
    def run_video_analysis(self, **kwargs): ...
    def run_timeline_plan(self, **kwargs): ...
    def run_render(self, **kwargs): ...
    def run_edit_pipeline(self, **kwargs): ...
    def run_synthesis_reference_ingest(self, **kwargs): ...
    def run_synthesis_consolidation(self, **kwargs): ...


def test_caption_draft_is_punchy_and_collection_aware():
    draft = generate_caption_draft(
        render_name="run_auto_123.mp4",
        collection_slug="mario",
    )

    assert "mario" in draft.caption.lower()
    assert len(draft.caption) <= 2200
    assert "#amv" in draft.hashtags
    assert "#edit" in draft.hashtags
    assert "#mario" in draft.hashtags
    assert len(draft.hashtags) <= 30


def test_openai_caption_generation_uses_responses_api_and_records_provenance():
    client = FakeOpenAIClient()

    draft = generate_caption_draft(
        render_name="final-battle.mp4",
        collection_slug="mario",
        openai_client=client,
        model="gpt-test",
    )

    assert draft.caption == "This final clash goes wild."
    assert draft.hashtags == ["#amv", "#finalbattle"]
    assert draft.notes == "Generated from render metadata."
    assert draft.caption_source == "openai"
    assert draft.caption_error is None
    assert client.calls[0]["model"] == "gpt-test"
    assert client.calls[0]["store"] is False
    assert "mario" in client.calls[0]["input"]


def test_caption_generation_falls_back_when_openai_fails():
    class BrokenOpenAIClient:
        class Responses:
            def create(self, **_kwargs):
                raise RuntimeError("model unavailable")

        responses = Responses()

    draft = generate_caption_draft(
        render_name="run_auto_123.mp4",
        collection_slug="mario",
        openai_client=BrokenOpenAIClient(),
        model="gpt-test",
    )

    assert draft.caption_source == "fallback"
    assert draft.caption_error == "model unavailable"
    assert "mario" in draft.caption.lower()


def test_buffer_video_post_payload_targets_queue_with_public_media_url():
    payload = build_buffer_create_post_payload(
        channel_id="channel_instagram",
        text="A fast AMV drop. #amv",
        media_url="https://media.example.com/publishing/post_123/render.mp4",
        mode="addToQueue",
    )

    assert "mutation CreatePost" in payload["query"]
    assert payload["variables"]["input"] == {
        "text": "A fast AMV drop. #amv",
        "channelId": "channel_instagram",
        "schedulingType": "automatic",
        "mode": "addToQueue",
        "assets": [
            {
                "video": {
                    "url": "https://media.example.com/publishing/post_123/render.mp4",
                },
            }
        ],
    }


def test_public_media_copy_uses_stable_publishing_key_and_url():
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"mp4-bytes")
    post = create_publish_post_for_render(
        repo,
        user_id="user_123",
        render_output=render,
        collection_slug="mario",
        auto_created=True,
    )

    updated = prepare_public_media_copy(
        repo,
        store=store,
        post=post,
        public_base_url="https://media.example.com",
    )

    assert updated.public_media_key == (
        f"public/publishing/user_123/{post.post_id}/{render['version_id']}.mp4"
    )
    assert updated.public_media_url == (
        f"https://media.example.com/public/publishing/user_123/{post.post_id}/{render['version_id']}.mp4"
    )
    assert store.get_bytes(updated.public_media_key) == b"mp4-bytes"


def test_publishing_api_prepares_updates_and_queues_buffer_post(monkeypatch):
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    buffer = RecordingBufferClient()
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    prepared = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    )
    post_id = prepared.json()["post_id"]
    updated = client.patch(
        f"/v1/publishing/posts/{post_id}",
        headers={"X-User-Id": "user_123"},
        json={
            "caption": "Big drop energy.",
            "hashtags": ["#amv", "#animeedit"],
            "notes": "Use this one for Friday.",
        },
    )
    queued = client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    )
    listed = client.get(
        "/v1/publishing/posts?status=queued",
        headers={"X-User-Id": "user_123"},
    )

    assert prepared.status_code == 201
    assert prepared.json()["status"] == "ready"
    assert updated.json()["caption"] == "Big drop energy."
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert queued.json()["caption_source"] in {"fallback", "openai"}
    assert queued.json()["buffer_post_id"] == "buf_123"
    assert queued.json()["public_media_url"].startswith("https://media.example.com/")
    assert buffer.calls == [
        {
            "channel_id": "channel_instagram",
            "text": "Big drop energy.\n\n#amv #animeedit",
            "media_url": queued.json()["public_media_url"],
            "mode": "addToQueue",
            "due_at": None,
        }
    ]
    assert [item["post_id"] for item in listed.json()] == [post_id]


def test_publishing_config_reports_non_secret_setup_and_buffer_channel(monkeypatch):
    monkeypatch.setenv("BUFFER_API_KEY", "buf_secret")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("ECLYPTE_CAPTION_MODEL", "gpt-test")
    buffer = RecordingBufferClient()
    client = TestClient(
        create_app(
            store=InMemoryObjectStore(),
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    response = client.get("/v1/publishing/config", headers={"X-User-Id": "user_123"})

    assert response.status_code == 200
    assert response.json() == {
        "buffer_api_key_configured": True,
        "buffer_channel_id_configured": True,
        "public_media_base_url_configured": True,
        "openai_api_key_configured": True,
        "caption_model": "gpt-test",
        "buffer_channel": {
            "id": "channel_instagram",
            "name": "Eclypte IG",
            "service": "instagram",
            "display_name": "@eclypte",
            "is_disconnected": False,
            "is_locked": False,
            "external_link": "https://instagram.com/eclypte",
            "last_error": None,
        },
    }
    assert buffer.channel_calls == ["channel_instagram"]


def test_publishing_config_records_buffer_channel_lookup_errors(monkeypatch):
    monkeypatch.setenv("BUFFER_API_KEY", "buf_secret")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    client = TestClient(
        create_app(
            store=InMemoryObjectStore(),
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=FailingBufferClient(),
        )
    )

    response = client.get("/v1/publishing/config", headers={"X-User-Id": "user_123"})

    assert response.status_code == 200
    assert response.json()["buffer_channel"]["last_error"] == "Buffer channel lookup failed"


def test_buffer_failure_persists_failed_status_and_error(monkeypatch):
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=FailingBufferClient(),
        )
    )
    prepared = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    )

    failed = client.post(
        f"/v1/publishing/posts/{prepared.json()['post_id']}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    )
    listed = client.get(
        "/v1/publishing/posts?status=failed",
        headers={"X-User-Id": "user_123"},
    )

    assert failed.status_code == 502
    assert listed.json()[0]["status"] == "failed"
    assert listed.json()[0]["last_error"] == "Buffer rejected the media URL"


def _publish_render(repo: StorageRepository, *, body=b"render"):
    file_ref = FileRef(user_id="user_123", file_id="file_render")
    repo.create_file_manifest(
        file_ref=file_ref,
        kind="render_output",
        display_name="auto-draft.mp4",
        source_run_id="run_auto",
    )
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=body,
        content_type="video/mp4",
        original_filename="auto-draft.mp4",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    return {"file_id": file_ref.file_id, "version_id": version_ref.version_id}
