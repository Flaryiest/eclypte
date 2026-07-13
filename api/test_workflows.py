import base64
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from api.youtube_download import YoutubeDownloadAttempt, YoutubeDownloadResult
from api.storage.refs import FileRef
from api.storage.refs import FileVersionRef
from api.storage.refs import RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore
from api.workflows import CLIP_INDEX_BUILD_STEP, DefaultWorkflowRunner


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
    created_by_step: str = "test",
):
    file_ref = FileRef(user_id="user_123", file_id=file_id)
    repo.create_file_manifest(file_ref=file_ref, kind=kind, display_name=filename)
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=body,
        content_type=content_type,
        original_filename=filename,
        created_by_step=created_by_step,
        derived_from_step="test",
        input_file_version_ids=input_file_version_ids or [],
    )
    return {"file_id": file_id, "version_id": version_ref.version_id}


def _publish_timeline_inputs(repo: StorageRepository, video: dict | None = None):
    song = {
        "source": {"duration_sec": 4.0},
        "tempo_bpm": 120,
        "segments": [{"start_sec": 0.0, "end_sec": 4.0, "label": "chorus"}],
    }
    video = video or {
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

    class FakeAlign:
        @staticmethod
        def remote(*_args):
            return None

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: None
    )
    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=FakeAlign)
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


def test_audio_conversion_publishes_wav_and_archives_raw(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    source = _publish_artifact(
        repo,
        file_id="file_raw_audio",
        kind="song_audio",
        filename="song.mp3",
        body=b"mp3-bytes",
        content_type="audio/mpeg",
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="audio_conversion",
        inputs={
            "audio_file_id": source["file_id"],
            "audio_version_id": source["version_id"],
        },
        steps=["convert_audio", "publish_audio"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-convert"))

    def fake_convert(src_path, wav_path):
        assert Path(src_path).read_bytes() == b"mp3-bytes"
        Path(wav_path).write_bytes(b"wav-bytes")
        return wav_path

    monkeypatch.setattr("api.workflows._convert_audio_to_wav", fake_convert)

    runner.run_audio_conversion(
        user_id="user_123",
        run_id=run.run_id,
        source_file_id=source["file_id"],
        source_version_id=source["version_id"],
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["audio_file_id"] == f"file_audio_{run.run_id}"

    wav_ref = FileVersionRef(
        user_id="user_123",
        file_id=completed.outputs["audio_file_id"],
        version_id=completed.outputs["audio_version_id"],
    )
    wav_meta = repo.load_file_version_meta(wav_ref)
    assert wav_meta.content_type == "audio/wav"
    assert wav_meta.original_filename == "song.wav"
    assert repo.read_version_bytes(wav_ref) == b"wav-bytes"

    # The raw upload is archived so the library shows only the WAV.
    raw_manifest = repo.load_file_manifest(FileRef(user_id="user_123", file_id="file_raw_audio"))
    assert raw_manifest.archived_at is not None


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

    class FakeAlign:
        @staticmethod
        def remote(*_args):
            return None

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: None
    )
    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=FakeAlign)
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
        created_by_step=CLIP_INDEX_BUILD_STEP,
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
        return {
            "shots": [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}],
            "overlays": [],
        }

    monkeypatch.setattr("api.workflows._run_agent_synthesis", fake_synthesis)

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,        creative_brief="Make it cinematic.",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["clip_index_file_id"] == clip_index["file_id"]
    assert completed.outputs["clip_index_version_id"] == clip_index["version_id"]
    assert completed.outputs["synthesis_prompt_version_id"] == prompt.version_id
    assert completed.outputs["timeline_file_id"] == f"file_timeline_{run.run_id}"
    assert captured["system_prompt"] == "CUSTOM SYSTEM PROMPT"
    assert captured["instructions"] == "Make it cinematic."


def test_enrich_clip_results_attaches_scene_metadata():
    from api.workflows import _enrich_clip_results

    video = {
        "source": {"duration_sec": 12.0},
        "scenes": [
            {
                "index": 0,
                "start_sec": 0.0,
                "end_sec": 6.0,
                "motion": {"avg_intensity": 0.72, "camera_movement": "pan"},
                "impacts": {"impact_frames": [{"timestamp_sec": 5.2, "intensity": 0.8}]},
            },
            {
                "index": 1,
                "start_sec": 6.0,
                "end_sec": 12.0,
                "motion": {"avg_intensity": 0.1, "camera_movement": "static"},
                "impacts": {"impact_frames": []},
            },
        ],
    }
    results = [{"timestamp": 5.0, "score": 0.9}, {"timestamp": 8.0, "score": 0.5}]

    enriched = _enrich_clip_results(results, video)

    assert enriched[0]["motion"] == 0.72
    assert enriched[0]["camera"] == "pan"
    assert enriched[0]["impact_near"] is True
    assert enriched[1]["motion"] == 0.1
    assert enriched[1]["impact_near"] is False
    # originals untouched (score/timestamp preserved)
    assert enriched[0]["score"] == 0.9
    assert results[0].get("motion") is None


def test_enrich_clip_results_noop_without_scene_metadata():
    from api.workflows import _enrich_clip_results

    video = {"source": {"duration_sec": 12.0}, "scenes": [{"index": 0, "start_sec": 0.0, "end_sec": 12.0}]}
    enriched = _enrich_clip_results([{"timestamp": 5.0, "score": 0.9}], video)

    assert enriched == [{"timestamp": 5.0, "score": 0.9}]


def test_agent_timeline_enriches_query_results_and_emits_sync_report(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    video = {
        "source": {"duration_sec": 12.0},
        "scenes": [
            {
                "index": 0,
                "start_sec": 0.0,
                "end_sec": 12.0,
                "motion": {"avg_intensity": 0.6, "camera_movement": "handheld"},
                "impacts": {"impact_frames": [{"timestamp_sec": 5.2, "intensity": 0.8}]},
            }
        ],
    }
    audio, source_video, music_analysis, video_analysis = _publish_timeline_inputs(repo, video=video)
    _publish_artifact(
        repo,
        file_id="file_clip_index",
        kind="clip_index",
        filename="source.npz",
        body=b"npz",
        content_type="application/x-numpy-data",
        input_file_version_ids=[source_video["version_id"]],
        created_by_step=CLIP_INDEX_BUILD_STEP,
    )
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})
    monkeypatch.setattr(
        "api.workflows._query_clip_index_r2",
        lambda **_kwargs: [{"timestamp": 5.0, "score": 0.9}],
    )

    seen_results = {}

    def fake_synthesis(**kwargs):
        seen_results["query"] = kwargs["query_clips_fn"]("action", "source.mp4", 5)
        return {
            "shots": [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}],
            "overlays": [],
        }

    monkeypatch.setattr("api.workflows._run_agent_synthesis", fake_synthesis)

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        creative_brief="Make it hit.",
    )

    # Query results reaching the agent carry the scene metadata.
    assert seen_results["query"][0]["motion"] == 0.6
    assert seen_results["query"][0]["camera"] == "handheld"
    assert seen_results["query"][0]["impact_near"] is True

    # The run records a sync-report telemetry event.
    events = [
        event for event in repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
        if event.event_type == "timeline_sync_report"
    ]
    assert len(events) == 1
    payload = events[0].payload
    assert "sync" in payload
    assert payload["sync"]["shot_count"] >= 1
    assert "impact_registrations" in payload
    assert "pacing_splits" in payload


def test_agent_timeline_derives_style_profile_from_references(monkeypatch):
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
        created_by_step=CLIP_INDEX_BUILD_STEP,
    )
    # one completed reference whose editors cut 0.05s before the downbeat
    ref = repo.create_synthesis_reference(user_id="user_123", url="https://x/reel")
    repo.update_synthesis_reference(
        user_id="user_123",
        reference_id=ref.reference_id,
        status="completed",
        metrics={
            "cut_offsets_to_downbeats": {"n": 12, "median": -0.05},
            "cut_density_per_section": {"chorus": {"cuts_per_downbeat": 2.0}},
        },
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
        return {
            "shots": [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}],
            "overlays": [],
        }

    monkeypatch.setattr("api.workflows._run_agent_synthesis", fake_synthesis)

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        creative_brief="Cut like the references.",
    )

    # the derived profile reaches the agent...
    assert captured["style_profile"]["cut_lead_sec"] == 0.05
    assert captured["style_profile"]["pacing_bands_beats"]["chorus"][0] > 0
    # ...and is recorded on the sync-report telemetry event
    events = [
        e for e in repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
        if e.event_type == "timeline_sync_report"
    ]
    assert events and events[0].payload["style_profile"]["reference_count"] == 1


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
        created_by_step=CLIP_INDEX_BUILD_STEP,
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
        lambda **_kwargs: {
            "shots": [
                {"start_time": 0.0, "end_time": 2.0, "source_timestamp": 2.0},
                {"start_time": 2.0, "end_time": 4.0, "source_timestamp": 8.0},
            ],
            "overlays": [],
        },
    )

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,        creative_brief="Use strong moments.",
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
        lambda **_kwargs: {
            "shots": [{"start_time": 0.0, "end_time": 4.0, "source_timestamp": 2.0}],
            "overlays": [],
        },
    )

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,        creative_brief="",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["clip_index_file_id"].startswith("file_clip_index_")
    assert completed.outputs["clip_index_version_id"].startswith("ver_")
    assert built["filename"] == "source.mp4"
    assert built["source_key"].endswith(f"/versions/{source_video['version_id']}/blob")


def test_agent_timeline_failure_is_visible(monkeypatch):
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
        video_analysis=video_analysis,        creative_brief="",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "failed"
    assert completed.last_error == "agent failed"


def test_edit_pipeline_reuses_existing_analyses_and_publishes_render(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_LYRICS_TIMING_DISABLED", "1")
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
            "source_video_version_id": source_video["version_id"],            "creative_brief": "",
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
        source_video=source_video,        creative_brief="",
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
    # The kill-switch must actually suppress the lyrics-timing backfill.
    assert not [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]


def test_edit_pipeline_creates_missing_analysis_child_runs(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_LYRICS_TIMING_DISABLED", "1")
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
        creative_brief="",
        title="Fresh edit",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert completed.status == "completed"
    assert completed.outputs["music_run_id"].startswith("run_")
    assert completed.outputs["video_run_id"].startswith("run_")
    assert completed.outputs["render_output_version_id"].startswith("ver_")
    # The kill-switch must actually suppress the lyrics-timing backfill.
    assert not [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]


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
            "source_video_version_id": source_video["version_id"],            "creative_brief": "",
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
        source_video=source_video,        creative_brief="",
        title="Broken edit",
    )

    failed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert failed.status == "failed"
    assert failed.current_step == "music"
    assert failed.last_error == "music exploded"
    assert "timeline_file_id" not in failed.outputs


def test_run_video_analysis_publishes_source_poster(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "b"})

    source_ref = FileRef(user_id="user_123", file_id="file_video")
    repo.create_file_manifest(file_ref=source_ref, kind="source_video", display_name="film.mp4")
    source_version = repo.publish_bytes(
        file_ref=source_ref,
        body=b"video-bytes",
        content_type="video/mp4",
        original_filename="film.mp4",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="video_analysis",
        inputs={"source_video_file_id": "file_video", "source_video_version_id": source_version.version_id},
        steps=["analyze_video"],
    )

    poster_b64 = base64.b64encode(b"jpeg-bytes").decode("ascii")
    payload = {
        "schema_version": 1,
        "source": {"duration_sec": 100.0},
        "scenes": [],
        "poster_jpeg_b64": poster_b64,
        "poster_ts_sec": 20.0,
    }

    class _FakeRemote:
        def remote(self, *args):
            return dict(payload)

    fake_modal = types.SimpleNamespace(
        Function=types.SimpleNamespace(from_name=lambda app, fn: _FakeRemote())
    )
    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    runner.run_video_analysis(
        user_id="user_123",
        run_id=run.run_id,
        source_video={"file_id": "file_video", "version_id": source_version.version_id},
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed", completed.last_error
    assert completed.outputs["source_poster_file_id"] == f"file_source_poster_{run.run_id}"
    assert completed.outputs["source_poster_version_id"].startswith("ver_")
    # The published analysis JSON must NOT contain the transport-only poster keys.
    analysis_key = [
        k
        for k in store.objects
        if completed.outputs["video_analysis_version_id"] in k and k.endswith("blob")
    ]
    stored = json.loads(store.get_bytes(analysis_key[0]).decode("utf-8"))
    assert "poster_jpeg_b64" not in stored and "poster_ts_sec" not in stored


# ---- word-level lyrics timing ----

LYRICS_LRC = "[00:01.00]Hello world\n[00:02.00]Second line"


def _fake_modal_per_app(analyze=None, align=None):
    def from_name(app_name, _fn_name=None):
        return align if app_name == "eclypte-lyrics" else analyze

    return SimpleNamespace(Function=SimpleNamespace(from_name=from_name))


def _lyrics_timing_payload():
    return {
        "schema_version": 1,
        "source": {"duration_sec": 4.0},
        "mode": "aligned",
        "language": "en",
        "text_source": "synced_lrc",
        "model": "large-v3",
        "quality": {"word_count": 2},
        "lines": [
            {
                "line_idx": 0,
                "start_sec": 1.0,
                "end_sec": 2.0,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start_sec": 1.0, "end_sec": 1.4, "confidence": 0.9},
                    {"word": "world", "start_sec": 1.5, "end_sec": 2.0, "confidence": 0.9},
                ],
            }
        ],
    }


def _seed_song_audio(repo):
    return _publish_artifact(
        repo,
        file_id="file_audio",
        kind="song_audio",
        filename="song.wav",
        body=b"wav",
        content_type="audio/wav",
    )


def test_music_analysis_publishes_lyrics_timing(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio = _seed_song_audio(repo)
    run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music", "publish_analysis"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    captured = {}

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            return {"source": {"duration_sec": 4.0}}

    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            captured["text"] = text
            return _lyrics_timing_payload()

    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=FakeAlign)
    )

    runner.run_music_analysis(user_id="user_123", run_id=run.run_id, audio=audio)

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["lyrics_file_id"]
    assert completed.outputs["lyrics_timing_file_id"] == f"file_lyrics_timing_{run.run_id}"
    assert completed.outputs["lyrics_timing_version_id"].startswith("ver_")
    # LRC timestamps are discarded — the aligner receives text only.
    assert captured["text"] == "Hello world\nSecond line"


def test_music_analysis_survives_alignment_failure(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio = _seed_song_audio(repo)
    run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music", "publish_analysis"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            return {"source": {"duration_sec": 4.0}}

    class FakeAlign:
        @staticmethod
        def remote(*_args):
            raise RuntimeError("modal down")

    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=FakeAlign)
    )

    runner.run_music_analysis(user_id="user_123", run_id=run.run_id, audio=audio)

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["music_analysis_file_id"]
    assert "lyrics_timing_file_id" not in completed.outputs


def test_youtube_song_import_merges_lyrics_timing_keys(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    run = _create_youtube_import_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setenv("ECLYPTE_TEMP_DIR", str(Path.cwd() / ".pytest-tmp-youtube-worker"))
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    def fake_download(url, workdir):
        wav_path = workdir / "download.wav"
        wav_path.write_bytes(b"wav-bytes")
        return YoutubeDownloadResult(
            title="Imported Song",
            wav_path=wav_path,
            attempts=[YoutubeDownloadAttempt("pytubefix", "succeeded", "ok")],
        )

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            return {"source": {"duration_sec": 4.0}}

    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            assert audio_bytes == b"wav-bytes"
            return _lyrics_timing_payload()

    monkeypatch.setattr("api.workflows._download_youtube_wav", fake_download)
    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=FakeAlign)
    )

    runner.run_youtube_song_import(
        user_id="user_123",
        run_id=run.run_id,
        url="https://www.youtube.com/watch?v=abc123",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["lyrics_timing_file_id"] == f"file_lyrics_timing_{run.run_id}"


def test_find_song_lyrics_timing_matches_all_arms():
    from api.workflows import _find_song_lyrics_timing

    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    keys = {"lyrics_timing_file_id": "file_lt", "lyrics_timing_version_id": "ver_lt"}

    backfill = repo.create_run(
        user_id="user_123",
        workflow_type="lyrics_timing",
        inputs={"audio_version_id": "ver_a"},
        steps=["align_lyrics"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=backfill.run_id), status="completed", outputs=keys
    )
    analysis = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": "ver_b"},
        steps=["analyze_music"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=analysis.run_id), status="completed", outputs=keys
    )
    yt = repo.create_run(
        user_id="user_123",
        workflow_type="youtube_song_import",
        inputs={"youtube_url": "u"},
        steps=["download_youtube_audio"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=yt.run_id),
        status="completed",
        outputs={**keys, "audio_version_id": "ver_c"},
    )

    for version_id in ("ver_a", "ver_b", "ver_c"):
        found = _find_song_lyrics_timing(
            repo, user_id="user_123", audio_version_id=version_id
        )
        assert found == {"file_id": "file_lt", "version_id": "ver_lt"}

    assert (
        _find_song_lyrics_timing(repo, user_id="user_123", audio_version_id="ver_none")
        is None
    )


def _create_edit_parent(repo, audio, source_video):
    return repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={
            "title": "Edit",
            "audio_file_id": audio["file_id"],
            "audio_version_id": audio["version_id"],
            "source_video_file_id": source_video["file_id"],
            "source_video_version_id": source_video["version_id"],
            "creative_brief": "",
        },
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )


def test_ensure_edit_lyrics_timing_reuses_existing_artifact(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    timing_run = repo.create_run(
        user_id="user_123",
        workflow_type="lyrics_timing",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["align_lyrics"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=timing_run.run_id),
        status="completed",
        outputs={
            "lyrics_timing_file_id": "file_lt",
            "lyrics_timing_version_id": "ver_lt",
            "lyrics_timing_status": "ok",
        },
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        runner,
        "run_lyrics_timing",
        lambda **_: (_ for _ in ()).throw(AssertionError("timing should be reused")),
    )

    runner._ensure_edit_lyrics_timing(
        repo=repo,
        user_id="user_123",
        parent_ref=RunRef(user_id="user_123", run_id=parent.run_id),
        audio=audio,
    )

    updated = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert updated.outputs["lyrics_timing_file_id"] == "file_lt"
    assert updated.outputs["lyrics_timing_version_id"] == "ver_lt"
    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 1


def test_ensure_edit_lyrics_timing_creates_child_and_stamps_parent(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            return _lyrics_timing_payload()

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=FakeAlign))

    runner._ensure_edit_lyrics_timing(
        repo=repo,
        user_id="user_123",
        parent_ref=RunRef(user_id="user_123", run_id=parent.run_id),
        audio=audio,
    )

    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 1
    child = timing_runs[0]
    assert child.status == "completed"
    assert child.outputs["lyrics_timing_status"] == "ok"

    updated = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert updated.outputs["lyrics_timing_run_id"] == child.run_id
    assert updated.outputs["lyrics_timing_file_id"] == child.outputs["lyrics_timing_file_id"]


def test_ensure_edit_lyrics_timing_negative_cache_skips_gpu(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    # A completed timing run with no usable words: don't re-burn GPU per edit.
    prior = repo.create_run(
        user_id="user_123",
        workflow_type="lyrics_timing",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["align_lyrics"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=prior.run_id),
        status="completed",
        outputs={"lyrics_timing_status": "none"},
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        runner,
        "run_lyrics_timing",
        lambda **_: (_ for _ in ()).throw(AssertionError("negative cache must hold")),
    )

    runner._ensure_edit_lyrics_timing(
        repo=repo,
        user_id="user_123",
        parent_ref=RunRef(user_id="user_123", run_id=parent.run_id),
        audio=audio,
    )

    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 1


def test_ensure_edit_lyrics_timing_failed_child_retries_next_edit(monkeypatch):
    # Transient errors (Modal app missing, network, timeout) must FAIL the child
    # run — a completed "none" would permanently negative-cache the song.
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    class BrokenAlign:
        @staticmethod
        def remote(*_args):
            raise RuntimeError("modal outage")

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=BrokenAlign))
    parent_ref = RunRef(user_id="user_123", run_id=parent.run_id)

    runner._ensure_edit_lyrics_timing(
        repo=repo, user_id="user_123", parent_ref=parent_ref, audio=audio
    )

    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 1
    assert timing_runs[0].status == "failed"
    updated = repo.load_run_manifest(parent_ref)
    assert "lyrics_timing_file_id" not in updated.outputs

    # The outage ends; the next edit retries and succeeds.
    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            return _lyrics_timing_payload()

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=FakeAlign))
    runner._ensure_edit_lyrics_timing(
        repo=repo, user_id="user_123", parent_ref=parent_ref, audio=audio
    )

    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 2
    updated = repo.load_run_manifest(parent_ref)
    assert updated.outputs["lyrics_timing_file_id"]


def test_ensure_edit_lyrics_timing_writes_negative_cache_on_no_words(monkeypatch):
    # A genuine no-words conclusion (instrumental) completes with status "none"
    # and stops later edits from re-burning GPU.
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )
    calls = {"align": 0}

    class NoWordsAlign:
        @staticmethod
        def remote(*_args):
            calls["align"] += 1
            return None

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=NoWordsAlign))
    parent_ref = RunRef(user_id="user_123", run_id=parent.run_id)

    runner._ensure_edit_lyrics_timing(
        repo=repo, user_id="user_123", parent_ref=parent_ref, audio=audio
    )
    runner._ensure_edit_lyrics_timing(
        repo=repo, user_id="user_123", parent_ref=parent_ref, audio=audio
    )

    timing_runs = [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]
    assert len(timing_runs) == 1
    assert timing_runs[0].status == "completed"
    assert timing_runs[0].outputs["lyrics_timing_status"] == "none"
    assert "lyrics_timing_file_id" not in timing_runs[0].outputs
    assert calls["align"] == 1


def test_ensure_edit_lyrics_timing_honors_song_workflow_negative_cache(monkeypatch):
    # A music_analysis run that already concluded "no usable words" stops the
    # backfill from re-burning GPU on the first edit.
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    analysis_run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=analysis_run.run_id),
        status="completed",
        outputs={"lyrics_timing_status": "none"},
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        runner,
        "run_lyrics_timing",
        lambda **_: (_ for _ in ()).throw(AssertionError("negative cache must hold")),
    )

    runner._ensure_edit_lyrics_timing(
        repo=repo,
        user_id="user_123",
        parent_ref=RunRef(user_id="user_123", run_id=parent.run_id),
        audio=audio,
    )

    assert not [
        r for r in repo.list_run_manifests("user_123") if r.workflow_type == "lyrics_timing"
    ]


def test_music_analysis_records_concluded_none(monkeypatch):
    # A conclusive no-words alignment during song analysis is stamped so the
    # edit pipeline's negative cache can honor it.
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio = _seed_song_audio(repo)
    run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music", "publish_analysis"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    class FakeAnalyze:
        @staticmethod
        def remote(audio_bytes, filename):
            return {"source": {"duration_sec": 4.0}}

    class NoWordsAlign:
        @staticmethod
        def remote(*_args):
            return None

    monkeypatch.setitem(
        sys.modules, "modal", _fake_modal_per_app(analyze=FakeAnalyze, align=NoWordsAlign)
    )

    runner.run_music_analysis(user_id="user_123", run_id=run.run_id, audio=audio)

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["lyrics_timing_status"] == "none"
    assert "lyrics_timing_file_id" not in completed.outputs


def test_run_lyrics_timing_reuses_stored_lrc(monkeypatch):
    # The backfill must reuse the stored LRC (no re-fetch, no duplicate asset).
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    audio = _seed_song_audio(repo)
    lyrics_asset = _publish_artifact(
        repo,
        file_id="file_lyrics_stored",
        kind="lyrics",
        filename="lyrics.lrc",
        body=LYRICS_LRC.encode("utf-8"),
        content_type="text/plain",
    )
    analysis_run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["analyze_music"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=analysis_run.run_id),
        status="completed",
        outputs={
            "lyrics_file_id": lyrics_asset["file_id"],
            "lyrics_version_id": lyrics_asset["version_id"],
        },
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="lyrics_timing",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["fetch_lyrics", "align_lyrics", "publish_lyrics_timing"],
    )
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics",
        lambda query: (_ for _ in ()).throw(AssertionError("must reuse stored LRC")),
    )
    captured = {}

    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            captured["text"] = text
            return _lyrics_timing_payload()

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=FakeAlign))

    runner.run_lyrics_timing(user_id="user_123", run_id=run.run_id, audio=audio)

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed"
    assert completed.outputs["lyrics_timing_status"] == "ok"
    assert captured["text"] == "Hello world\nSecond line"
    lyrics_manifests = [
        m for m in repo.list_file_manifests("user_123") if m.kind == "lyrics"
    ]
    assert len(lyrics_manifests) == 1  # no duplicate publish from the backfill


def test_edit_pipeline_generates_lyrics_timing_when_enabled(monkeypatch):
    # End-to-end: an edit on a song without timing backfills it and stamps the
    # parent run, with the feature ENABLED (no kill-switch, fakes wired).
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.delenv("ECLYPTE_LYRICS_TIMING_DISABLED", raising=False)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)
    monkeypatch.setattr(
        "api.prototyping.music.lyrics.search_synced_lyrics", lambda query: LYRICS_LRC
    )

    class FakeAlign:
        @staticmethod
        def remote(audio_bytes, filename, text):
            return _lyrics_timing_payload()

    monkeypatch.setitem(sys.modules, "modal", _fake_modal_per_app(align=FakeAlign))

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
        creative_brief="",
        title="Edit",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert completed.status == "completed"
    assert completed.outputs["lyrics_timing_run_id"].startswith("run_")
    assert completed.outputs["lyrics_timing_file_id"].startswith("file_lyrics_timing_")
    assert completed.outputs["lyrics_timing_version_id"].startswith("ver_")


def test_edit_pipeline_completes_when_lyrics_timing_fails(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    audio, source_video, _, _ = _publish_timeline_inputs(repo)
    parent = _create_edit_parent(repo, audio, source_video)

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
    monkeypatch.setattr(
        runner,
        "_ensure_edit_lyrics_timing",
        lambda **_: (_ for _ in ()).throw(RuntimeError("lyrics blew up")),
    )

    runner.run_edit_pipeline(
        user_id="user_123",
        run_id=parent.run_id,
        audio=audio,
        source_video=source_video,
        creative_brief="",
        title="Edit",
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=parent.run_id))
    assert completed.status == "completed"


def test_agent_timeline_passes_trimmed_lyrics_to_synthesis(monkeypatch):
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
        created_by_step=CLIP_INDEX_BUILD_STEP,
    )
    timing_artifact = _publish_artifact(
        repo,
        file_id="file_lyrics_timing",
        kind="lyrics_timing",
        filename="lyrics_timing.json",
        body=json.dumps(_lyrics_timing_payload()).encode("utf-8"),
        content_type="application/json",
    )
    timing_run = repo.create_run(
        user_id="user_123",
        workflow_type="lyrics_timing",
        inputs={"audio_version_id": audio["version_id"]},
        steps=["align_lyrics"],
    )
    repo.update_run_status(
        RunRef(user_id="user_123", run_id=timing_run.run_id),
        status="completed",
        outputs={
            "lyrics_timing_file_id": timing_artifact["file_id"],
            "lyrics_timing_version_id": timing_artifact["version_id"],
        },
    )
    run = _create_timeline_agent_run(repo)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "test"})

    captured = {}

    def fake_synthesis(**kwargs):
        captured.update(kwargs)
        return {
            "shots": [{"start_time": 0.0, "end_time": 3.0, "source_timestamp": 2.0}],
            "overlays": [],
        }

    monkeypatch.setattr("api.workflows._run_agent_synthesis", fake_synthesis)

    runner.run_timeline_plan(
        user_id="user_123",
        run_id=run.run_id,
        audio=audio,
        source_video=source_video,
        music_analysis=music_analysis,
        video_analysis=video_analysis,
        creative_brief="",
        export_options={
            "format": "reels_cinematic",
            "audio_start_sec": 0.5,
            "audio_end_sec": 3.5,
        },
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed", completed.last_error
    lyrics = captured["lyrics"]
    # Trimmed to the audio window and rebased: line 1.0-2.0 -> 0.5-1.5.
    assert lyrics["source"]["trim_start_sec"] == 0.5
    assert lyrics["lines"][0]["start_sec"] == 0.5
    assert lyrics["lines"][0]["words"][0]["word"] == "Hello"
