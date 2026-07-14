from datetime import datetime, timezone

from api.autopilot import combo_key, run_autopilot_tick, select_trim_windows
from api.storage.models import AutopilotItem, AutopilotState
from api.storage.refs import FileRef, RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore

USER = "user_test"
NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-06-09"


class RecordingStarts:
    def __init__(self):
        self.analysis_calls = []
        self.edit_calls = []

    def start_music_analysis(self, user_id, *, audio):
        self.analysis_calls.append((user_id, audio))
        return f"run_analysis_{len(self.analysis_calls)}"

    def start_edit(self, user_id, **kwargs):
        self.edit_calls.append((user_id, kwargs))
        return f"run_edit_{len(self.edit_calls)}"


def build_repo():
    return StorageRepository(InMemoryObjectStore())


def make_item(**overrides):
    base = {
        "item_id": "ap_item1",
        "source_video_file_id": "file_video",
        "source_video_version_id": "v_video",
        "song_file_id": "file_song",
        "song_version_id": "v_song",
        "created_at": "2026-06-09T11:00:00Z",
        "updated_at": "2026-06-09T11:00:00Z",
    }
    base.update(overrides)
    return AutopilotItem(**base)


def save_state(repo, **overrides):
    fields = {"enabled": True, **overrides}
    state = AutopilotState(owner_user_id=USER, **fields)
    return repo.save_autopilot_state(state)


def tick(repo, starts):
    return run_autopilot_tick(
        repo,
        user_id=USER,
        start_music_analysis=starts.start_music_analysis,
        start_edit=starts.start_edit,
        now=NOW,
    )


def make_analysis(duration_sec=120.0, chorus_start=60.0):
    rate_hz = 10
    values = []
    for index in range(int(duration_sec * rate_hz)):
        t = index / rate_hz
        values.append(0.9 if chorus_start <= t < chorus_start + 35 else 0.2)
    return {
        "schema_version": 1,
        "source": {"duration_sec": duration_sec},
        "energy": {"rate_hz": rate_hz, "values": values},
        "segments": [
            {"start_sec": 0.0, "end_sec": chorus_start, "label": "verse"},
            {"start_sec": chorus_start, "end_sec": chorus_start + 35, "label": "chorus"},
            {"start_sec": chorus_start + 35, "end_sec": duration_sec, "label": "outro"},
        ],
    }


def publish_analysis_artifact(repo, *, file_id="file_analysis", analysis=None):
    """Publish a music_analysis artifact, returning (file_id, version_id)."""
    analysis_ref = FileRef(user_id=USER, file_id=file_id)
    repo.create_file_manifest(
        file_ref=analysis_ref,
        kind="music_analysis",
        display_name="song.json",
    )
    version = repo.publish_json(
        file_ref=analysis_ref,
        data=analysis if analysis is not None else make_analysis(),
        original_filename="song.json",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    return analysis_ref.file_id, version.version_id


def publish_song_with_analysis(repo, *, song_version_id="v_song"):
    """Create a completed music_analysis run + artifact for the test song."""
    file_id, version_id = publish_analysis_artifact(repo)
    run = repo.create_run(
        user_id=USER,
        workflow_type="music_analysis",
        inputs={"audio_version_id": song_version_id},
        steps=["analyze"],
    )
    repo.update_run_status(
        RunRef(user_id=USER, run_id=run.run_id),
        status="completed",
        outputs={
            "music_analysis_file_id": file_id,
            "music_analysis_version_id": version_id,
        },
    )


def publish_render_output(repo, *, file_id="file_render"):
    file_ref = FileRef(user_id=USER, file_id=file_id)
    repo.create_file_manifest(
        file_ref=file_ref,
        kind="render_output",
        display_name="My Edit.mp4",
    )
    version = repo.publish_bytes(
        file_ref=file_ref,
        body=b"mp4",
        content_type="video/mp4",
        original_filename="My Edit.mp4",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    return {"file_id": file_id, "version_id": version.version_id}


def test_select_trim_windows_prefers_high_energy_chorus():
    windows = select_trim_windows(make_analysis(duration_sec=120.0, chorus_start=60.0))

    assert windows
    start, end = windows[0]
    # Begins ~CHORUS_LEAD_IN_SEC (5s) before the chorus so the reel captures the build-in.
    assert start < 60.0
    assert 54.0 <= start <= 56.5
    assert 20.0 <= end - start <= 30.0
    assert end <= 120.0


def test_select_trim_windows_short_song_returns_full_span():
    analysis = make_analysis(duration_sec=20.0, chorus_start=0.0)
    analysis["source"]["duration_sec"] = 20.0

    assert select_trim_windows(analysis) == [(0.0, 20.0)]


def test_select_trim_windows_without_analysis():
    assert select_trim_windows(None) == []
    assert select_trim_windows({}) == []


def test_tick_disabled_takes_no_action():
    repo = build_repo()
    starts = RecordingStarts()
    save_state(repo, enabled=False, items=[make_item()])

    state = tick(repo, starts)

    assert starts.edit_calls == []
    assert starts.analysis_calls == []
    assert state.last_tick_at is not None
    assert state.items[0].status == "pending"


def test_tick_analyzes_song_without_analysis():
    repo = build_repo()
    starts = RecordingStarts()
    save_state(repo, items=[make_item()])

    state = tick(repo, starts)

    # No analysis exists yet, so the tick must run analysis first rather than
    # starting an untrimmed (full-song) edit.
    assert starts.edit_calls == []
    assert starts.analysis_calls == [
        (USER, {"file_id": "file_song", "version_id": "v_song"})
    ]
    item = state.items[0]
    assert item.status == "analyzing"
    assert item.analysis_run_id == "run_analysis_1"


def test_tick_uses_trim_window_from_music_analysis():
    repo = build_repo()
    starts = RecordingStarts()
    publish_song_with_analysis(repo)
    save_state(repo, items=[make_item()])

    state = tick(repo, starts)

    _, kwargs = starts.edit_calls[0]
    options = kwargs["export_options"]
    assert 50.0 <= options["audio_start_sec"] <= 60.0
    assert 20.0 <= options["audio_end_sec"] - options["audio_start_sec"] <= 30.0
    item = state.items[0]
    assert item.audio_start_sec == options["audio_start_sec"]


def test_tick_fails_legacy_importing_item_without_counting_toward_halt():
    repo = build_repo()
    starts = RecordingStarts()
    # Items stuck in "importing" predate the YouTube-import removal; nothing can
    # advance them anymore, so the tick fails them without tripping the halt.
    item = make_item(
        song_file_id=None,
        song_version_id=None,
        song_youtube_url="https://youtu.be/abc123",
        status="importing",
        import_run_id="run_import_legacy",
    )
    save_state(repo, items=[item])

    state = tick(repo, starts)

    assert starts.edit_calls == []
    assert starts.analysis_calls == []
    updated = state.items[0]
    assert updated.status == "failed"
    assert "YouTube import was removed" in (updated.last_error or "")
    assert state.consecutive_failures == 0
    assert state.halted_reason is None


def _complete_analysis_run(repo, *, song_version_id="v_song", analysis=None, file_id="file_analysis"):
    """Create a completed music_analysis run carrying an analysis artifact."""
    analysis_file_id, analysis_version_id = publish_analysis_artifact(
        repo, file_id=file_id, analysis=analysis
    )
    run = repo.create_run(
        user_id=USER,
        workflow_type="music_analysis",
        inputs={"audio_version_id": song_version_id},
        steps=["analyze_music", "publish_analysis"],
    )
    repo.update_run_status(
        RunRef(user_id=USER, run_id=run.run_id),
        status="completed",
        outputs={
            "music_analysis_file_id": analysis_file_id,
            "music_analysis_version_id": analysis_version_id,
        },
    )
    return run.run_id


def test_tick_advances_completed_analysis_to_edit():
    repo = build_repo()
    starts = RecordingStarts()
    analysis_run_id = _complete_analysis_run(repo)
    item = make_item(status="analyzing", analysis_run_id=analysis_run_id)
    save_state(repo, items=[item])

    state = tick(repo, starts)

    assert len(starts.edit_calls) == 1
    _, kwargs = starts.edit_calls[0]
    options = kwargs["export_options"]
    assert options["format"] == "reels_cinematic"
    assert 20.0 <= options["audio_end_sec"] - options["audio_start_sec"] <= 30.0
    updated = state.items[0]
    assert updated.status == "editing"
    assert updated.edit_run_id == "run_edit_1"
    assert updated.audio_start_sec == options["audio_start_sec"]


def test_tick_fails_when_analysis_yields_no_window():
    repo = build_repo()
    starts = RecordingStarts()
    analysis_run_id = _complete_analysis_run(
        repo, analysis={"schema_version": 1, "source": {"duration_sec": 0.0}}
    )
    item = make_item(status="analyzing", analysis_run_id=analysis_run_id)
    save_state(repo, items=[item])

    state = tick(repo, starts)

    assert starts.edit_calls == []
    updated = state.items[0]
    assert updated.status == "failed"
    assert "trim window" in (updated.last_error or "")


def test_tick_packages_completed_edit(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    repo = build_repo()
    starts = RecordingStarts()
    render = publish_render_output(repo)
    run = repo.create_run(
        user_id=USER,
        workflow_type="edit_pipeline",
        inputs={},
        steps=["render"],
    )
    repo.update_run_status(
        RunRef(user_id=USER, run_id=run.run_id),
        status="completed",
        outputs={
            "render_output_file_id": render["file_id"],
            "render_output_version_id": render["version_id"],
        },
    )
    item = make_item(status="editing", edit_run_id=run.run_id)
    save_state(repo, items=[item], consecutive_failures=2)

    state = tick(repo, starts)

    updated = state.items[0]
    assert updated.status == "packaged"
    assert updated.post_id
    assert state.packaged_counts[TODAY] == 1
    assert state.consecutive_failures == 0
    post = repo.load_publishing_post(user_id=USER, post_id=updated.post_id)
    assert post.auto_created is True
    assert post.status == "ready"


def test_tick_marks_item_failed_when_edit_run_fails():
    repo = build_repo()
    starts = RecordingStarts()
    run = repo.create_run(
        user_id=USER,
        workflow_type="edit_pipeline",
        inputs={},
        steps=["render"],
    )
    repo.update_run_status(
        RunRef(user_id=USER, run_id=run.run_id),
        status="failed",
        last_error="render exploded",
    )
    item = make_item(status="editing", edit_run_id=run.run_id)
    save_state(repo, items=[item])

    state = tick(repo, starts)

    assert state.items[0].status == "failed"
    assert "render exploded" in state.items[0].last_error
    assert state.consecutive_failures == 1


def test_tick_respects_daily_target():
    repo = build_repo()
    starts = RecordingStarts()
    save_state(
        repo,
        daily_target=2,
        packaged_counts={TODAY: 2},
        items=[make_item()],
    )

    state = tick(repo, starts)

    assert starts.edit_calls == []
    assert state.items[0].status == "pending"


def test_tick_skips_already_used_combo_without_counting_failure():
    repo = build_repo()
    starts = RecordingStarts()
    # A short song yields exactly one window (0, duration); marking it used means
    # every window for this pair is exhausted.
    short_analysis = make_analysis(duration_sec=20.0, chorus_start=0.0)
    short_analysis["source"]["duration_sec"] = 20.0
    _complete_analysis_run(repo, analysis=short_analysis)
    save_state(
        repo,
        items=[make_item()],
        used_combos=[combo_key("file_video", "file_song", (0.0, 20.0))],
    )

    state = tick(repo, starts)

    assert starts.edit_calls == []
    assert state.items[0].status == "failed"
    assert "already used" in state.items[0].last_error
    assert state.consecutive_failures == 0
    assert state.halted_reason is None


def test_tick_halts_after_three_consecutive_failures():
    repo = build_repo()
    starts = RecordingStarts()
    broken = [
        make_item(
            item_id=f"ap_broken{i}",
            song_file_id=None,
            song_version_id=None,
        )
        for i in range(3)
    ]
    healthy = make_item(item_id="ap_ok")
    save_state(repo, daily_target=5, items=[*broken, healthy])

    state = tick(repo, starts)

    assert state.halted_reason is not None
    assert state.consecutive_failures == 3
    statuses = {item.item_id: item.status for item in state.items}
    assert statuses["ap_ok"] == "pending"
    assert starts.edit_calls == []

    second = tick(repo, RecordingStarts())
    assert second.halted_reason == state.halted_reason
    assert {item.item_id: item.status for item in second.items}["ap_ok"] == "pending"


def test_autopilot_endpoints_flow(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ECLYPTE_AUTOPILOT", raising=False)
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.test_api_v1 import RecordingWorkflowRunner, publish_artifact

    store = InMemoryObjectStore()
    runner = RecordingWorkflowRunner()
    client = TestClient(create_app(store=store, workflow_runner=runner))
    repo = StorageRepository(store)
    video = publish_artifact(
        repo, user_id="local_dev", file_id="file_video", kind="source_video", filename="film.mp4"
    )
    song = publish_artifact(
        repo, user_id="local_dev", file_id="file_song", kind="song_audio", filename="song.wav"
    )
    # Pre-seed a completed analysis so the first tick can pick a trim window and
    # start the edit directly (no separate analyzing pass needed for this flow).
    analysis_ref = FileRef(user_id="local_dev", file_id="file_song_analysis")
    repo.create_file_manifest(
        file_ref=analysis_ref, kind="music_analysis", display_name="song.json"
    )
    analysis_version = repo.publish_json(
        file_ref=analysis_ref,
        data=make_analysis(),
        original_filename="song.json",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    analysis_run = repo.create_run(
        user_id="local_dev",
        workflow_type="music_analysis",
        inputs={"audio_version_id": song["version_id"]},
        steps=["analyze_music", "publish_analysis"],
    )
    repo.update_run_status(
        RunRef(user_id="local_dev", run_id=analysis_run.run_id),
        status="completed",
        outputs={
            "music_analysis_file_id": analysis_ref.file_id,
            "music_analysis_version_id": analysis_version.version_id,
        },
    )

    health = client.get("/healthz").json()
    assert health["autopilot_loop_configured"] is False

    enabled = client.patch("/v1/autopilot", json={"enabled": True, "daily_target": 3})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["daily_target"] == 3

    invalid = client.post(
        "/v1/autopilot/queue",
        json={"items": [{"source_video": video}]},
    )
    assert invalid.status_code == 400

    queued = client.post(
        "/v1/autopilot/queue",
        json={"items": [{"source_video": video, "song": song, "creative_brief": "go hard"}]},
    )
    assert queued.status_code == 201
    assert queued.json()["pending"] == 1
    item_id = queued.json()["items"][0]["item_id"]

    ticked = client.post("/v1/autopilot/tick")
    assert ticked.status_code == 200
    body = ticked.json()
    assert body["in_flight"] == 1
    assert body["items"][0]["status"] == "editing"
    assert [call for call in runner.calls if call[0] == "edit_pipeline"]

    runs = client.get("/v1/runs", params={"workflow_type": "edit_pipeline"}).json()
    assert len(runs) == 1
    assert runs[0]["inputs"]["creative_brief"] == "go hard"
    assert runs[0]["inputs"]["export_format"] == "reels_cinematic"

    in_flight_delete = client.delete(f"/v1/autopilot/queue/{item_id}")
    assert in_flight_delete.status_code == 400

    status_view = client.get("/v1/autopilot")
    assert status_view.status_code == 200
    assert status_view.json()["enabled"] is True
