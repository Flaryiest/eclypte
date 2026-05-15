import json
import sys
from pathlib import Path
from types import SimpleNamespace

from api.youtube_download import YoutubeDownloadAttempt, YoutubeDownloadResult
from api.storage.refs import FileRef
from api.storage.refs import FileVersionRef
from api.storage.refs import RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore
from api.workflows import DefaultWorkflowRunner


def _create_youtube_import_run(repo: StorageRepository):
    return repo.create_run(
        user_id="user_123",
        workflow_type="youtube_song_import",
        inputs={"youtube_url": "https://www.youtube.com/watch?v=abc123"},
        steps=["download_youtube_audio", "publish_audio", "analyze_music", "publish_analysis"],
    )


def _create_timeline_agent_run(repo: StorageRepository):
    return repo.create_run(
        user_id="user_123",
        workflow_type="timeline_agent_plan",
        inputs={
            "audio_version_id": "ver_audio",
            "source_video_version_id": "ver_video",
            "music_analysis_version_id": "ver_music",
            "video_analysis_version_id": "ver_video_analysis",
            "planning_mode": "agent",
        },
        steps=["ensure_clip_index", "agent_plan_timeline", "publish_timeline"],
    )


def _publish_artifact(
    repo: StorageRepository,
    *,
    file_id: str,
    kind: str,
    filename: str,
    body: bytes,
    content_type: str,
    input_file_version_ids: list[str] | None = None,
):
    file_ref = FileRef(user_id="user_123", file_id=file_id)
    repo.create_file_manifest(file_ref=file_ref, kind=kind, display_name=filename)
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=body,
        content_type=content_type,
        original_filename=filename,
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=input_file_version_ids or [],
    )
    return {"file_id": file_id, "version_id": version_ref.version_id}


def _publish_timeline_inputs(repo: StorageRepository):
    song = {
        "source": {"duration_sec": 4.0},
        "tempo_bpm": 120,
        "segments": [{"start_sec": 0.0, "end_sec": 4.0, "label": "chorus"}],
    }
    video = {
        "source": {"duration_sec": 12.0},
        "scenes": [{"index": 0, "start_sec": 0.0, "end_sec": 12.0, "duration_sec": 12.0}],
    }
    audio = _publish_artifact(
        repo,
        file_id="file_audio",
        kind="song_audio",
        filename="song.wav",
        body=b"wav",
        content_type="audio/wav",
    )
    source_video = _publish_artifact(
        repo,
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        body=b"mp4",
        content_type="video/mp4",
    )
    music_analysis = _publish_artifact(
        repo,
        file_id="file_music_analysis",
        kind="music_analysis",
        filename="song.json",
        body=json.dumps(song).encode("utf-8"),
        content_type="application/json",
    )
    video_analysis = _publish_artifact(
        repo,
        file_id="file_video_analysis",
        kind="video_analysis",
        filename="source.json",
        body=json.dumps(video).encode("utf-8"),
        content_type="application/json",
    )
    return audio, source_video, music_analysis, video_analysis


def _complete_analysis_run(
    repo: StorageRepository,
    *,
    run_id: str,
    file_id: str,
    kind: str,
    filename: str,
    file_key: str,
    version_key: str,
    body: bytes = b"{}",
):
    artifact = _publish_artifact(
        repo,
        file_id=file_id,
        kind=kind,
        filename=filename,
        body=body,
        content_type="application/json",
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=run_id),
        status="completed",
        current_step=None,
        outputs={
            file_key: artifact["file_id"],
            version_key: artifact["version_id"],
        },
    )
    return artifact


def _fake_timeline_runner(repo: StorageRepository):
    def run_timeline_plan(**kwargs):
        run_id = kwargs["run_id"]
        artifact = _publish_artifact(
            repo,
            file_id=f"file_timeline_{run_id}",
            kind="timeline",
            filename=f"{run_id}.timeline.json",
            body=b"{}",
            content_type="application/json",
        )
        repo.update_run_status(
            RunRef(user_id="user_123", run_id=run_id),
            status="completed",
            current_step=None,
            outputs={
                "timeline_file_id": artifact["file_id"],
                "timeline_version_id": artifact["version_id"],
            },
        )

    return run_timeline_plan


def _fake_render_runner(repo: StorageRepository):
    def run_render(**kwargs):
        run_id = kwargs["run_id"]
        artifact = _publish_artifact(
            repo,
            file_id=f"file_render_{run_id}",
            kind="render_output",
            filename=f"{run_id}.mp4",
            body=b"mp4",
            content_type="video/mp4",
        )
        repo.update_run_status(
            RunRef(user_id="user_123", run_id=run_id),
            status="completed",
            current_step=None,
            outputs={
                "render_output_file_id": artifact["file_id"],
                "render_output_version_id": artifact["version_id"],
            },
        )

    return run_render


def test_youtube_song_import_publishes_audio_and_analysis(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = _create_youtube_import_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    def fake_download(url, workdir):
        assert url == "https://www.youtube.com/watch?v=abc123"
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return YoutubeDownloadResult(
            title="Imported Song",
            wav_path=wav_path,
            attempts=[YoutubeDownloadAttempt("pytubefix", "succeeded", "downloaded audio stream")],
        )

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            assert audio_bytes == b"wav-bytes"
            assert filename == "Imported Song.wav"
            return {"source": {"title": "Imported Song"}}

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setitem(
        sys.modules,
        "modal",
        SimpleNamespace(
            Function=SimpleNamespace(from_name=lambda *_args: FakeAnalyze),
        ),
    )

    runner.run_youtube_song_import(
        user_id="user_123",
        run_id=run.run_id,
        url="https://www.youtube.com/watch?v=abc123",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["audio_file_id"] == f"file_audio_{run.run_id}"
    assert completed.outputs["music_analysis_file_id"] == f"file_music_analysis_{run.run_id}"


def test_youtube_song_import_records_download_attempt_events(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = _create_youtube_import_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))

    def fake_download(_url, workdir):
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return YoutubeDownloadResult(
            title="Imported Song",
            wav_path=wav_path,
            attempts=[
                YoutubeDownloadAttempt("pytubefix", "failed", "bot gate"),
                YoutubeDownloadAttempt("yt-dlp", "succeeded", "downloaded best audio"),
            ],
        )

    class FakeAnalyze:
        @staticmethod
        def remote(_audio_bytes, _filename):
            return {"source": {"title": "Imported Song"}}

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setitem(
        sys.modules,
        "modal",
        SimpleNamespace(
            Function=SimpleNamespace(from_name=lambda *_args: FakeAnalyze),
        ),
    )

    runner.run_youtube_song_import(
        user_id="user_123",
        run_id=run.run_id,
        url="https://www.youtube.com/watch?v=abc123",
    )

    events = repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
    attempts = [event for event in events if event.event_type == "youtube_download_attempt"]

    assert [attempt.payload["provider"] for attempt in attempts] == ["pytubefix", "yt-dlp"]
    assert [attempt.payload["status"] for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0].payload["detail"] == "bot gate"


def test_agent_timeline_reuses_existing_clip_index_and_active_prompt(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo)
    clip_index = _publish_artifact(
        repo,
        file_id="file_clip_index",
        kind="clip_index",
        filename="source.npz",
        body=b"npz",
        content_type="application/x-numpy-data",
        input_file_version_ids=[source_video["version_id"]],
    )
    prompt = repo.create_synthesis_prompt_version(
        user_id="user_123",
        label="Active agent prompt",
        prompt_text="CUSTOM SYSTEM PROMPT",
        activate=True,
    )
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})
    monkeypatch.setattr(
        "api.workflows._build_clip_index_r2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("clip index should be reused")),
    )

    captured = {}

    def fake_synthesis(**kwargs):
        captured.update(kwargs)
        return [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}]

    monkeypatch.setattr("api.workflows._run_agent_synthesis", fake_synthesis)

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        planning_mode="agent",
        creative_brief="Make it cinematic.",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["clip_index_file_id"] == clip_index["file_id"]
    assert completed.outputs["clip_index_version_id"] == clip_index["version_id"]
    assert completed.outputs["synthesis_prompt_version_id"] == prompt.version_id
    assert completed.outputs["timeline_file_id"] == f"file_timeline_{run.run_id}"
    assert captured["system_prompt"] == "CUSTOM SYSTEM PROMPT"
    assert captured["instructions"] == "Make it cinematic."


def test_agent_timeline_emits_parent_progress_milestones(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo)
    _publish_artifact(
        repo,
        file_id="file_clip_index",
        kind="clip_index",
        filename="source.npz",
        body=b"npz",
        content_type="application/x-numpy-data",
        input_file_version_ids=[source_video["version_id"]],
    )
    parent = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={"title": "Telemetry edit"},
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})
    monkeypatch.setattr(
        "api.workflows._build_clip_index_r2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("clip index should be reused")),
    )
    monkeypatch.setattr(
        "api.workflows._run_agent_synthesis",
        lambda **_kwargs: [
            {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 2.0},
            {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 8.0},
        ],
    )

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        planning_mode="agent",
        creative_brief="Use strong moments.",
        progress_context={
            "user_id": "user_123",
            "run_id": parent.run_id,
            "stage": "timeline",
        },
    )

    events = [
        event.payload
        for event in repo.list_run_events(RunRef(user_id="user_123", run_id=parent.run_id))
        if event.event_type == "progress" and event.payload.get("stage") == "timeline"
    ]
    assert [event["percent"] for event in events] == [10, 15, 25, 40, 55, 70, 75, 90]
    assert [event["detail"] for event in events] == [
        "Loading timeline inputs",
        "Checking CLIP index",
        "Reused existing CLIP index",
        "Loading active synthesis prompt",
        "Running agent timeline planner",
        "Adapting agent timeline",
        "Validating timeline coverage",
        "Publishing timeline",
    ]


def test_agent_timeline_builds_missing_clip_index(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo)
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})

    built = {}

    def fake_build(**kwargs):
        built.update(kwargs)
        return {
            "content_type": "application/x-numpy-data",
            "size_bytes": 7,
            "sha256": "a" * 64,
        }

    monkeypatch.setattr("api.workflows._build_clip_index_r2", fake_build)
    monkeypatch.setattr(
        "api.workflows._run_agent_synthesis",
        lambda **_kwargs: [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}],
    )

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        planning_mode="agent",
        creative_brief="",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["clip_index_file_id"].startswith("file_clip_index_")
    assert completed.outputs["clip_index_version_id"].startswith("ver_")
    assert built["filename"] == "source.mp4"
    assert built["source_key"].endswith(f"/versions/{source_video['version_id']}/blob")


def test_agent_timeline_failure_does_not_fallback_to_deterministic(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo)
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})
    monkeypatch.setattr(
        "api.workflows._build_clip_index_r2",
        lambda **_kwargs: {
            "content_type": "application/x-numpy-data",
            "size_bytes": 7,
            "sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        "api.workflows._run_agent_synthesis",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("agent failed")),
    )

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        planning_mode="agent",
        creative_brief="",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "failed"
    assert completed.last_error == "agent failed"


def test_edit_pipeline_reuses_existing_analyses_and_publishes_render(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo)
    music_run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music", "publish_analysis"],
    )
    video_run = repo.create_run(
        user_id="user_123",
        workflow_type="video_analysis",
        inputs={"source_video_version_id": source_video["version_id"]},
        steps=["analyze_video", "publish_analysis"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=music_run.run_id),
        status="completed",
        current_step=None,
        outputs={
            "music_analysis_file_id": music_analysis["file_id"],
            "music_analysis_version_id": music_analysis["version_id"],
        },
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=video_run.run_id),
        status="completed",
        current_step=None,
        outputs={
            "video_analysis_file_id": video_analysis["file_id"],
            "video_analysis_version_id": video_analysis["version_id"],
        },
    )
    parent = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={
            "title": "Reuse edit",
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "source_video_file_id": source_video["file_id"],
            "source_video_version_id": source_video["version_id"],
            "planning_mode": "agent",
            "creative_brief": "",
        },
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )
    monkeypatch.setattr(runner, "run_music_analysis", lambda **_: (_ for _ in ()).throw(AssertionError("music should be reused")))
    monkeypatch.setattr(runner, "run_video_analysis", lambda **_: (_ for _ in ()).throw(AssertionError("video should be reused")))
    monkeypatch.setattr(runner, "run_timeline_plan", _fake_timeline_runner(repo))
    monkeypatch.setattr(runner, "run_render", _fake_render_runner(repo))

    runner.run_edit_pipeline(
        user_id="user_123",
        run_id=parent.run_id,
        audio=audio,
        source_video=source_video,
        planning_mode="agent",
        creative_brief="",
        title="Reuse edit",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    events = repo.list_run_events(RunRef(user_id="user_123", run_id=parent.run_id))
    assert completed.status == "completed"
    assert completed.outputs["music_analysis_version_id"] == music_analysis["version_id"]
    assert completed.outputs["video_analysis_version_id"] == video_analysis["version_id"]
    assert completed.outputs["timeline_run_id"].startswith("run_")
    assert completed.outputs["render_output_file_id"].startswith("file_render_")
    assert any(event.event_type == "progress" and event.payload["stage"] == "render" for event in events)


def test_edit_pipeline_creates_missing_analysis_child_runs(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={
            "title": "Fresh edit",
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "source_video_file_id": source_video["file_id"],
            "source_video_version_id": source_video["version_id"],
            "planning_mode": "deterministic",
            "creative_brief": "",
        },
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )

    def run_music_analysis(**kwargs):
        _complete_analysis_run(
            repo,
            run_id=kwargs["run_id"],
            file_id=f"file_music_analysis_{kwargs['run_id']}",
            kind="music_analysis",
            filename="song.json",
            file_key="music_analysis_file_id",
            version_key="music_analysis_version_id",
        )

    def run_video_analysis(**kwargs):
        _complete_analysis_run(
            repo,
            run_id=kwargs["run_id"],
            file_id=f"file_video_analysis_{kwargs['run_id']}",
            kind="video_analysis",
            filename="source.json",
            file_key="video_analysis_file_id",
            version_key="video_analysis_version_id",
        )

    monkeypatch.setattr(runner, "run_music_analysis", run_music_analysis)
    monkeypatch.setattr(runner, "run_video_analysis", run_video_analysis)
    monkeypatch.setattr(runner, "run_timeline_plan", _fake_timeline_runner(repo))
    monkeypatch.setattr(runner, "run_render", _fake_render_runner(repo))

    runner.run_edit_pipeline(
        user_id="user_123",
        run_id=parent.run_id,
        audio=audio,
        source_video=source_video,
        planning_mode="deterministic",
        creative_brief="",
        title="Fresh edit",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert completed.status == "completed"
    assert completed.outputs["music_run_id"].startswith("run_")
    assert completed.outputs["video_run_id"].startswith("run_")
    assert completed.outputs["render_output_version_id"].startswith("ver_")


def test_edit_pipeline_fails_parent_when_child_run_fails(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={
            "title": "Broken edit",
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "source_video_file_id": source_video["file_id"],
            "source_video_version_id": source_video["version_id"],
            "planning_mode": "agent",
            "creative_brief": "",
        },
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )

    def run_music_analysis(**kwargs):
        repo.update_run_status(
            RunRef(user_id="user_123", run_id=kwargs["run_id"]),
            status="failed",
            last_error="music exploded",
        )

    monkeypatch.setattr(runner, "run_music_analysis", run_music_analysis)

    runner.run_edit_pipeline(
        user_id="user_123",
        run_id=parent.run_id,
        audio=audio,
        source_video=source_video,
        planning_mode="agent",
        creative_brief="",
        title="Broken edit",
    )

    failed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert failed.status == "failed"
    assert failed.current_step == "music"
    assert failed.last_error == "music exploded"
    assert "timeline_file_id" not in failed.outputs


def test_bucket_import_normalizes_publishes_asset_and_runs_analysis(monkeypatch):
    from api.auto_import import parse_import_candidate

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/mario/songs/song.mp3",
        etag="etag-song",
        size_bytes=9,
    )
    store.put_bytes(candidate.source_key, b"raw-audio", content_type="audio/mpeg")
    run = repo.create_run(
        user_id="user_123",
        workflow_type="bucket_import",
        inputs=candidate.run_inputs(),
        steps=["normalize_media", "publish_asset", "analyze_asset", "create_auto_draft"],
    )

    monkeypatch.setattr(
        "api.workflows._normalize_imported_media",
        lambda repo, candidate, progress_context=None: b"normalized-wav",
    )

    def run_music_analysis(**kwargs):
        _complete_analysis_run(
            repo,
            run_id=kwargs["run_id"],
            file_id=f"file_music_analysis_{kwargs['run_id']}",
            kind="music_analysis",
            filename="song.json",
            file_key="music_analysis_file_id",
            version_key="music_analysis_version_id",
        )

    monkeypatch.setattr(runner, "run_music_analysis", run_music_analysis)

    runner.run_bucket_import(
        user_id="user_123",
        run_id=run.run_id,
        candidate=candidate.model_dump(),
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    asset = repo.load_file_manifest(
        FileRef(user_id="user_123", file_id=completed.outputs["asset_file_id"])
    )
    version = repo.load_file_version_meta(
        FileVersionRef(
            user_id="user_123",
            file_id=asset.file_id,
            version_id=completed.outputs["asset_version_id"],
        )
    )
    assert store.get_bytes(version.storage_key) == b"normalized-wav"
    assert asset.kind == "song_audio"
    assert asset.tags == ["auto_import", "collection:mario"]
    assert version.content_type == "audio/wav"
    assert version.original_filename == "song.wav"
    assert completed.status == "completed"
    assert completed.outputs["analysis_run_id"].startswith("run_")
    assert completed.outputs["analysis_version_id"].startswith("ver_")


def test_bucket_import_creates_auto_draft_for_ready_collection_counterpart(monkeypatch):
    from api.auto_import import parse_import_candidate

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    song = _publish_artifact(
        repo,
        file_id="file_song_ready",
        kind="song_audio",
        filename="song.wav",
        body=b"wav",
        content_type="audio/wav",
    )
    song_manifest = repo.load_file_manifest(FileRef(user_id="user_123", file_id=song["file_id"]))
    repo.save_file_manifest(
        song_manifest.model_copy(update={"tags": ["auto_import", "collection:mario"]})
    )
    _complete_analysis_run(
        repo,
        run_id=repo.create_run(
            user_id="user_123",
            workflow_type="music_analysis",
            inputs={"audio_file_id": song["file_id"], "audio_version_id": song["version_id"]},
            steps=["analyze_music", "publish_analysis"],
        ).run_id,
        file_id="file_music_ready",
        kind="music_analysis",
        filename="song.json",
        file_key="music_analysis_file_id",
        version_key="music_analysis_version_id",
    )
    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/mario/videos/source.mkv",
        etag="etag-video",
        size_bytes=9,
    )
    store.put_bytes(candidate.source_key, b"raw-video", content_type="video/x-matroska")
    import_run = repo.create_run(
        user_id="user_123",
        workflow_type="bucket_import",
        inputs=candidate.run_inputs(),
        steps=["normalize_media", "publish_asset", "analyze_asset", "create_auto_draft"],
    )
    auto_draft_calls = []
    monkeypatch.setattr(
        "api.workflows._normalize_imported_media",
        lambda repo, candidate, progress_context=None: b"normalized-mp4",
    )

    def run_video_analysis(**kwargs):
        _complete_analysis_run(
            repo,
            run_id=kwargs["run_id"],
            file_id=f"file_video_analysis_{kwargs['run_id']}",
            kind="video_analysis",
            filename="source.json",
            file_key="video_analysis_file_id",
            version_key="video_analysis_version_id",
        )

    def run_auto_draft(**kwargs):
        auto_draft_calls.append(kwargs)

    monkeypatch.setattr(runner, "run_video_analysis", run_video_analysis)
    monkeypatch.setattr(runner, "run_auto_draft", run_auto_draft)

    runner.run_bucket_import(
        user_id="user_123",
        run_id=import_run.run_id,
        candidate=candidate.model_dump(),
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=import_run.run_id))
    draft_id = completed.outputs["auto_draft_run_id"]
    draft = repo.load_run_manifest(RunRef(user_id="user_123", run_id=draft_id))
    assert draft.workflow_type == "auto_draft"
    assert draft.inputs["audio_version_id"] == song["version_id"]
    assert draft.inputs["source_video_version_id"] == completed.outputs["asset_version_id"]
    assert draft.inputs["export_format"] == "reels_9_16"
    assert draft.inputs["audio_end_sec"] == "60.000"
    assert auto_draft_calls[0]["run_id"] == draft_id


def test_bucket_import_clamps_auto_draft_export_to_short_song_duration(monkeypatch):
    from api.auto_import import parse_import_candidate

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    song = _publish_artifact(
        repo,
        file_id="file_short_song",
        kind="song_audio",
        filename="short.wav",
        body=b"wav",
        content_type="audio/wav",
    )
    song_manifest = repo.load_file_manifest(FileRef(user_id="user_123", file_id=song["file_id"]))
    repo.save_file_manifest(
        song_manifest.model_copy(update={"tags": ["auto_import", "collection:shorts"]})
    )
    _complete_analysis_run(
        repo,
        run_id=repo.create_run(
            user_id="user_123",
            workflow_type="music_analysis",
            inputs={"audio_file_id": song["file_id"], "audio_version_id": song["version_id"]},
            steps=["analyze_music", "publish_analysis"],
        ).run_id,
        file_id="file_short_music_analysis",
        kind="music_analysis",
        filename="short.json",
        file_key="music_analysis_file_id",
        version_key="music_analysis_version_id",
        body=json.dumps({"source": {"duration_sec": 20.0}}).encode("utf-8"),
    )
    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/shorts/videos/source.mp4",
        etag="etag-video",
        size_bytes=9,
    )
    store.put_bytes(candidate.source_key, b"raw-video", content_type="video/mp4")
    import_run = repo.create_run(
        user_id="user_123",
        workflow_type="bucket_import",
        inputs=candidate.run_inputs(),
        steps=["normalize_media", "publish_asset", "analyze_asset", "create_auto_draft"],
    )
    auto_draft_calls = []
    monkeypatch.setattr(
        "api.workflows._normalize_imported_media",
        lambda repo, candidate, progress_context=None: b"normalized-mp4",
    )

    def run_video_analysis(**kwargs):
        _complete_analysis_run(
            repo,
            run_id=kwargs["run_id"],
            file_id=f"file_video_analysis_{kwargs['run_id']}",
            kind="video_analysis",
            filename="source.json",
            file_key="video_analysis_file_id",
            version_key="video_analysis_version_id",
        )

    def run_auto_draft(**kwargs):
        auto_draft_calls.append(kwargs)

    monkeypatch.setattr(runner, "run_video_analysis", run_video_analysis)
    monkeypatch.setattr(runner, "run_auto_draft", run_auto_draft)

    runner.run_bucket_import(
        user_id="user_123",
        run_id=import_run.run_id,
        candidate=candidate.model_dump(),
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=import_run.run_id))
    draft = repo.load_run_manifest(
        RunRef(user_id="user_123", run_id=completed.outputs["auto_draft_run_id"])
    )
    assert draft.inputs["audio_end_sec"] == "20.000"


def test_run_auto_draft_clamps_export_to_short_song_duration(monkeypatch):
    repo = StorageRepository(InMemoryObjectStore())
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    song = _publish_artifact(
        repo,
        file_id="file_short_song",
        kind="song_audio",
        filename="short.wav",
        body=b"wav",
        content_type="audio/wav",
    )
    video = _publish_artifact(
        repo,
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        body=b"mp4",
        content_type="video/mp4",
    )
    _complete_analysis_run(
        repo,
        run_id=repo.create_run(
            user_id="user_123",
            workflow_type="music_analysis",
            inputs={"audio_file_id": song["file_id"], "audio_version_id": song["version_id"]},
            steps=["analyze_music", "publish_analysis"],
        ).run_id,
        file_id="file_short_music_analysis",
        kind="music_analysis",
        filename="short.json",
        file_key="music_analysis_file_id",
        version_key="music_analysis_version_id",
        body=json.dumps({"source": {"duration_sec": 20.0}}).encode("utf-8"),
    )
    captured = {}

    def run_edit_pipeline(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(runner, "run_edit_pipeline", run_edit_pipeline)

    runner.run_auto_draft(
        user_id="user_123",
        run_id="run_auto",
        audio=song,
        source_video=video,
        collection_slug="shorts",
    )

    assert captured["export_options"]["audio_end_sec"] == 20.0


def test_bucket_import_skips_duplicate_auto_draft_pair(monkeypatch):
    from api.auto_import import parse_import_candidate

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    audio = _publish_artifact(
        repo,
        file_id="file_song",
        kind="song_audio",
        filename="song.wav",
        body=b"wav",
        content_type="audio/wav",
    )
    video = _publish_artifact(
        repo,
        file_id="file_video",
        kind="source_video",
        filename="source.mp4",
        body=b"mp4",
        content_type="video/mp4",
    )
    for artifact in (audio, video):
        manifest = repo.load_file_manifest(FileRef(user_id="user_123", file_id=artifact["file_id"]))
        repo.save_file_manifest(
            manifest.model_copy(update={"tags": ["auto_import", "collection:mario"]})
        )
    existing = repo.create_run(
        user_id="user_123",
        workflow_type="auto_draft",
        inputs={
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "source_video_file_id": video["file_id"],
            "source_video_version_id": video["version_id"],
        },
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )
    repo.update_run_status(RunRef(user_id="user_123", run_id=existing.run_id), status="completed")
    candidate = parse_import_candidate(
        bucket="eclypte",
        key="incoming/collections/mario/videos/source.mp4",
        etag="etag-video",
        size_bytes=3,
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="bucket_import",
        inputs=candidate.run_inputs(),
        steps=["normalize_media", "publish_asset", "analyze_asset", "create_auto_draft"],
    )

    created = runner._maybe_create_auto_draft(
        repo=repo,
        user_id="user_123",
        parent_run_id=run.run_id,
        imported_ref={
            "file_id": video["file_id"],
            "version_id": video["version_id"],
        },
        imported_kind="source_video",
        collection_slug="mario",
    )

    assert created is None
