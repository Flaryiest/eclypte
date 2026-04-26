import json
import sys
from pathlib import Path
from types import SimpleNamespace

from api.youtube_download import YoutubeDownloadAttempt, YoutubeDownloadResult
from api.storage.refs import FileRef
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
):
    artifact = _publish_artifact(
        repo,
        file_id=file_id,
        kind=kind,
        filename=filename,
        body=b"{}",
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
