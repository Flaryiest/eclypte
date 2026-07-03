import uuid
from datetime import datetime, timezone

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
from api.storage.models import PublishingPostRecord
from api.storage.refs import FileRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingBufferClient:
    def __init__(self):
        self.calls = []
        self.channel_calls = []
        self.post_calls = []

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

    def get_post(self, *, post_id):
        self.post_calls.append(post_id)
        return BufferPostResult(
            post_id=post_id,
            status="sent",
            post_url="https://instagram.com/reel/abc123",
        )


class QueuedBufferClient(RecordingBufferClient):
    """createPost returns no permalink yet (queued); get_post back-fills it later."""

    def create_video_post(self, **kwargs):
        self.calls.append(kwargs)
        return BufferPostResult(post_id="buf_777", status="queued", post_url=None)


class LaggingPermalinkBufferClient(RecordingBufferClient):
    """Buffer reports the post sent right away, but the Instagram permalink only
    appears on a later poll — the realistic case the status mapping must handle."""

    def create_video_post(self, **kwargs):
        self.calls.append(kwargs)
        return BufferPostResult(post_id="buf_lag", status="buffer", post_url=None)

    def get_post(self, *, post_id):
        self.post_calls.append(post_id)
        if len(self.post_calls) == 1:
            return BufferPostResult(
                post_id=post_id,
                status="sent",
                post_url=None,
                sent_at="2026-06-14T10:00:00Z",
            )
        return BufferPostResult(
            post_id=post_id,
            status="sent",
            post_url="https://instagram.com/reel/lag123",
            sent_at="2026-06-14T10:00:00Z",
        )


class GetPostErrorBufferClient(RecordingBufferClient):
    """Buffer can't resolve the stored post id (e.g. stale/unqueryable) — get_post
    raises, which must degrade gracefully instead of 502ing the request."""

    def create_video_post(self, **kwargs):
        self.calls.append(kwargs)
        return BufferPostResult(post_id="buf_err", status="queued", post_url=None)

    def get_post(self, *, post_id):
        self.post_calls.append(post_id)
        raise BufferClientError("Buffer HTTP 404: post not found")


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


def test_caption_input_includes_source_and_song(monkeypatch):
    client = FakeOpenAIClient()
    generate_caption_draft(
        render_name="run_1.mp4",
        collection_slug="ghibli",
        source_name="Spirited Away",
        song_name="Unravel",
        openai_client=client,
        model="gpt-test",
    )
    sent = client.calls[0]["input"]
    assert "Spirited Away" in sent
    assert "Unravel" in sent


def test_fallback_hashtags_are_derived_from_names(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    draft = generate_caption_draft(
        render_name="run_1.mp4",
        source_name="Spirited Away",
        song_name="Unravel",
    )
    assert draft.caption_source == "fallback"
    assert "#spirited_away" in draft.hashtags
    assert "#unravel" in draft.hashtags
    assert "#amv" in draft.hashtags


def test_caption_draft_is_punchy_and_collection_aware(monkeypatch):
    # Force the deterministic fallback (no live OpenAI call) so the test is
    # not sensitive to OPENAI_API_KEY being present in the environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
        "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}},
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


def test_send_buffer_post_now_schedules_immediate_due_at(monkeypatch):
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
    # "post now" needs no scheduled_at — the server computes a near-future dueAt itself.
    sent = client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "now"},
    )

    assert sent.status_code == 200
    assert sent.json()["status"] == "scheduled"
    assert sent.json()["buffer_post_id"] == "buf_123"

    assert len(buffer.calls) == 1
    call = buffer.calls[0]
    assert call["mode"] == "customScheduled"
    # dueAt is a near-future UTC timestamp, not None and not in the past (Buffer rejects
    # past times), so the post bypasses the queue slot and publishes right away.
    assert call["due_at"]
    due_at = datetime.strptime(call["due_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert due_at > datetime.now(timezone.utc)
    assert sent.json()["scheduled_at"] == call["due_at"]


def test_refresh_status_backfills_post_url_from_buffer(monkeypatch):
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    buffer = QueuedBufferClient()
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    post_id = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    ).json()["post_id"]
    queued = client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    ).json()

    assert queued["status"] == "queued"
    assert queued["post_url"] is None
    assert queued["buffer_post_id"] == "buf_777"

    refreshed = client.post(
        f"/v1/publishing/posts/{post_id}/refresh-status",
        headers={"X-User-Id": "user_123"},
    ).json()

    assert buffer.post_calls == ["buf_777"]
    assert refreshed["post_url"] == "https://instagram.com/reel/abc123"
    assert refreshed["buffer_status"] == "sent"
    assert refreshed["status"] == "published"
    assert refreshed["posted_at"]


def test_refresh_status_publishes_on_sent_then_backfills_url(monkeypatch):
    # A sent post must move to "published" as soon as Buffer reports it sent, even
    # before the Instagram permalink exists; the permalink then back-fills on a later
    # poll without disturbing the published status or posted_at.
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    buffer = LaggingPermalinkBufferClient()
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    post_id = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    ).json()["post_id"]
    client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    )

    first = client.post(
        f"/v1/publishing/posts/{post_id}/refresh-status",
        headers={"X-User-Id": "user_123"},
    ).json()

    # Sent with no permalink yet → already published, posted_at from Buffer's sentAt.
    assert first["status"] == "published"
    assert first["buffer_status"] == "sent"
    assert first["posted_at"] == "2026-06-14T10:00:00Z"
    assert first["post_url"] is None

    second = client.post(
        f"/v1/publishing/posts/{post_id}/refresh-status",
        headers={"X-User-Id": "user_123"},
    ).json()

    # Permalink arrives later; status stays published and posted_at is unchanged.
    assert second["status"] == "published"
    assert second["post_url"] == "https://instagram.com/reel/lag123"
    assert second["posted_at"] == "2026-06-14T10:00:00Z"


def test_refresh_status_records_error_without_502(monkeypatch):
    # A Buffer lookup that fails for one post must not 502 the request; it records
    # the reason on the post (surfaced inline) and leaves the status untouched.
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    buffer = GetPostErrorBufferClient()
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    post_id = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    ).json()["post_id"]
    client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    )

    response = client.post(
        f"/v1/publishing/posts/{post_id}/refresh-status",
        headers={"X-User-Id": "user_123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["last_error"] == "Buffer HTTP 404: post not found"
    assert buffer.post_calls == ["buf_err"]


def test_mark_posted_override_moves_post_to_published(monkeypatch):
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "channel_instagram")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    render = _publish_render(repo, body=b"render-video")
    buffer = QueuedBufferClient()
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=buffer,
        )
    )

    post_id = client.post(
        "/v1/publishing/posts",
        headers={"X-User-Id": "user_123"},
        json={"render_output": render},
    ).json()["post_id"]
    client.post(
        f"/v1/publishing/posts/{post_id}/send-buffer",
        headers={"X-User-Id": "user_123"},
        json={"mode": "queue"},
    )

    marked = client.post(
        f"/v1/publishing/posts/{post_id}/mark-posted",
        headers={"X-User-Id": "user_123"},
        json={"post_url": "https://instagram.com/reel/manual"},
    ).json()

    assert marked["status"] == "published"
    assert marked["posted_at"]
    assert marked["post_url"] == "https://instagram.com/reel/manual"
    assert marked["last_error"] is None


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


def test_create_post_resolves_movie_and_song_names_from_render_lineage():
    from api.storage.refs import FileRef, RunRef

    store = InMemoryObjectStore()
    repo = StorageRepository(store)

    # Source video + song assets, named after their media.
    video_ref = FileRef(user_id="user_123", file_id="file_video")
    repo.create_file_manifest(file_ref=video_ref, kind="source_video", display_name="Spirited Away.mp4")
    song_ref = FileRef(user_id="user_123", file_id="file_song")
    repo.create_file_manifest(file_ref=song_ref, kind="song_audio", display_name="Unravel.wav")

    # The render run that produced the output carries the source/song file IDs.
    run = repo.create_run(
        user_id="user_123",
        workflow_type="render",
        inputs={"source_video_file_id": "file_video", "audio_file_id": "file_song"},
        steps=["render"],
    )

    # Render output whose source_run_id points at that run.
    render_ref = FileRef(user_id="user_123", file_id="file_render")
    repo.create_file_manifest(
        file_ref=render_ref, kind="render_output", display_name="run.mp4", source_run_id=run.run_id
    )
    version = repo.publish_bytes(
        file_ref=render_ref, body=b"mp4", content_type="video/mp4",
        original_filename="run.mp4", created_by_step="render",
        derived_from_step="render", input_file_version_ids=[],
    )

    post = create_publish_post_for_render(
        repo,
        user_id="user_123",
        render_output={"file_id": "file_render", "version_id": version.version_id},
    )

    assert post.source_name == "Spirited Away"
    assert post.song_name == "Unravel"


def test_regenerate_caption_passes_persisted_names(monkeypatch):
    """Regenerate-caption must forward the post's stored source/song names to the draft generator."""
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        from api.publishing import CaptionDraft
        return CaptionDraft(caption="ok", hashtags=["#amv"], notes="", caption_source="openai")

    monkeypatch.setattr("api.app.generate_caption_draft", fake_generate)

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    client = TestClient(
        create_app(
            store=store,
            workflow_runner=NoopWorkflowRunner(),
            buffer_client=RecordingBufferClient(),
        )
    )

    now = "2026-01-01T00:00:00Z"
    post_id = f"post_{uuid.uuid4().hex[:8]}"
    record = PublishingPostRecord(
        post_id=post_id,
        owner_user_id="user_123",
        status="ready",
        render_file_id="file_render",
        render_version_id="ver_render",
        render_display_name="run.mp4",
        source_name="Spirited Away",
        song_name="Unravel",
        created_at=now,
        updated_at=now,
    )
    repo.save_publishing_post(record)

    resp = client.post(
        f"/v1/publishing/posts/{post_id}/regenerate-caption",
        headers={"X-User-Id": "user_123"},
    )
    assert resp.status_code == 200
    assert captured.get("source_name") == "Spirited Away"
    assert captured.get("song_name") == "Unravel"


def test_create_post_captures_render_poster_ref_from_source_run():
    from api.storage.refs import FileRef, RunRef

    store = InMemoryObjectStore()
    repo = StorageRepository(store)

    run = repo.create_run(
        user_id="user_123",
        workflow_type="render",
        inputs={},
        steps=["render"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=run.run_id),
        status="completed",
        outputs={
            "render_output_file_id": "file_render",
            "render_output_version_id": "ver_x",
            "render_poster_file_id": "file_poster",
            "render_poster_version_id": "ver_poster",
        },
    )
    render_ref = FileRef(user_id="user_123", file_id="file_render")
    repo.create_file_manifest(
        file_ref=render_ref, kind="render_output", display_name="run.mp4", source_run_id=run.run_id
    )
    version = repo.publish_bytes(
        file_ref=render_ref, body=b"mp4", content_type="video/mp4",
        original_filename="run.mp4", created_by_step="render",
        derived_from_step="render", input_file_version_ids=[],
    )

    post = create_publish_post_for_render(
        repo,
        user_id="user_123",
        render_output={"file_id": "file_render", "version_id": version.version_id},
    )

    assert post.render_poster_file_id == "file_poster"
    assert post.render_poster_version_id == "ver_poster"
