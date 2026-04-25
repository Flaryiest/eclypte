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
    assert "timeline_file_id" not in completed.outputs
