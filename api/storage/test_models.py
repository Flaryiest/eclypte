from api.storage.models import (
    AutopilotItem,
    AutopilotState,
    DerivedFrom,
    FileManifest,
    FileVersionMeta,
    PostMetricsSnapshot,
    PublishingPostRecord,
    RunEvent,
    RunManifest,
    RunStep,
)


def test_file_manifest_round_trips():
    manifest = FileManifest(
        file_id="file_001",
        owner_user_id="user_123",
        kind="source_video",
        current_version_id="ver_001",
        source_run_id=None,
        display_name="source.mp4",
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:00:00Z",
        tags=["upload"],
    )

    restored = FileManifest.model_validate_json(manifest.model_dump_json())
    assert restored.current_version_id == "ver_001"
    assert restored.kind == "source_video"


def test_file_version_meta_requires_derivation_details():
    meta = FileVersionMeta(
        version_id="ver_001",
        file_id="file_001",
        owner_user_id="user_123",
        content_type="video/mp4",
        size_bytes=12,
        sha256="abc",
        original_filename="source.mp4",
        created_at="2026-04-21T19:00:00Z",
        created_by_step="upload",
        storage_key="users/user_123/files/file_001/versions/ver_001/blob",
        derived_from=DerivedFrom(
            run_id="run_001",
            step_id="upload_source",
            input_file_version_ids=[],
            params_hash=None,
        ),
    )

    assert meta.derived_from.step_id == "upload_source"


def test_run_manifest_tracks_step_statuses():
    manifest = RunManifest(
        run_id="run_001",
        owner_user_id="user_123",
        workflow_type="edit_pipeline",
        status="running",
        inputs={"source_video": "file_001"},
        outputs={},
        steps=[RunStep(name="upload_source", status="completed")],
        current_step="video_analysis",
        last_error=None,
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:05:00Z",
    )

    assert manifest.steps[0].status == "completed"


def test_run_event_is_append_only_record():
    event = RunEvent(
        event_id="evt_001",
        run_id="run_001",
        owner_user_id="user_123",
        event_type="step_started",
        timestamp="2026-04-21T19:00:00Z",
        payload={"step": "video_analysis"},
    )

    assert event.payload["step"] == "video_analysis"


def test_publishing_post_record_carries_source_and_song_names():
    from api.storage.models import PublishingPostRecord

    record = PublishingPostRecord(
        post_id="pub_1",
        owner_user_id="u1",
        status="ready",
        render_file_id="f1",
        render_version_id="v1",
        render_display_name="My Edit.mp4",
        source_name="Spirited Away",
        song_name="Unravel",
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
    )
    assert record.source_name == "Spirited Away"
    assert record.song_name == "Unravel"
    # round-trips through JSON (durable storage)
    assert PublishingPostRecord.model_validate_json(record.model_dump_json()).song_name == "Unravel"


def test_autopilot_state_autonomy_fields_default_off_and_round_trip():
    # Legacy persisted JSON (no autonomy fields) must load under extra="forbid".
    legacy = AutopilotState.model_validate(
        {"owner_user_id": "u1", "updated_at": "2026-07-27T00:00:00Z"}
    )
    assert legacy.auto_pair is False
    assert legacy.auto_publish is False
    assert legacy.last_paired_at == {}
    assert legacy.exhausted_pairs == []
    assert legacy.recycling is False
    assert legacy.waiting_for_library is False

    state = legacy.model_copy(
        update={
            "auto_pair": True,
            "auto_publish": True,
            "last_paired_at": {"file_a": "2026-07-27T01:00:00Z"},
            "exhausted_pairs": ["file_a::file_b"],
            "recycling": True,
            "waiting_for_library": False,
        }
    )
    reloaded = AutopilotState.model_validate(state.model_dump(mode="json"))
    assert reloaded.last_paired_at == {"file_a": "2026-07-27T01:00:00Z"}
    assert reloaded.exhausted_pairs == ["file_a::file_b"]


def test_autopilot_item_auto_paired_defaults_false():
    item = AutopilotItem(
        item_id="ap_1",
        source_video_file_id="fv",
        source_video_version_id="vv",
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )
    assert item.auto_paired is False
    assert AutopilotItem.model_validate(item.model_dump(mode="json")).auto_paired is False


def test_publishing_post_metrics_fields_default_empty_and_round_trip():
    legacy = PublishingPostRecord.model_validate(
        {
            "post_id": "pub_1",
            "owner_user_id": "u1",
            "status": "ready",
            "render_file_id": "rf",
            "render_version_id": "rv",
            "render_display_name": "reel.mp4",
            "created_at": "2026-07-27T00:00:00Z",
            "updated_at": "2026-07-27T00:00:00Z",
        }
    )
    assert legacy.metrics == {}
    assert legacy.metrics_updated_at is None
    assert legacy.metrics_checked_at is None
    assert legacy.metrics_history == []
    assert legacy.source_video_file_id is None
    assert legacy.song_file_id is None

    stamped = legacy.model_copy(
        update={
            "metrics": {"views": 1200.0, "likes": 88.0},
            "metrics_updated_at": "2026-07-27T09:00:00Z",
            "metrics_checked_at": "2026-07-27T10:00:00Z",
            "metrics_history": [
                PostMetricsSnapshot(
                    captured_at="2026-07-26T10:00:00Z", metrics={"views": 400.0}
                )
            ],
            "source_video_file_id": "file_film",
            "song_file_id": "file_song",
        }
    )
    reloaded = PublishingPostRecord.model_validate(stamped.model_dump(mode="json"))
    assert reloaded.metrics == {"views": 1200.0, "likes": 88.0}
    assert reloaded.metrics_history[0].metrics == {"views": 400.0}
    assert reloaded.song_file_id == "file_song"


def test_autopilot_state_used_windows_defaults_and_round_trips():
    state = AutopilotState(owner_user_id="u1")
    assert state.used_windows == {}
    stamped = state.model_copy(update={"used_windows": {"f1::s1": [[10.0, 35.0]]}})
    reloaded = AutopilotState.model_validate(stamped.model_dump(mode="json"))
    assert reloaded.used_windows == {"f1::s1": [[10.0, 35.0]]}


def test_publishing_post_graph_fields_default_and_round_trip():
    legacy = PublishingPostRecord.model_validate(
        {
            "post_id": "pub_1",
            "owner_user_id": "u1",
            "status": "ready",
            "render_file_id": "rf",
            "render_version_id": "rv",
            "render_display_name": "reel.mp4",
            "created_at": "2026-08-04T00:00:00Z",
            "updated_at": "2026-08-04T00:00:00Z",
        }
    )
    assert legacy.provider == "buffer"
    assert legacy.ig_container_id is None
    assert legacy.ig_media_id is None
    assert legacy.copyright_status is None

    stamped = legacy.model_copy(
        update={
            "provider": "graph",
            "ig_container_id": "c1",
            "ig_media_id": "m1",
            "copyright_status": "clean",
        }
    )
    reloaded = PublishingPostRecord.model_validate(stamped.model_dump(mode="json"))
    assert reloaded.provider == "graph"
    assert reloaded.ig_media_id == "m1"
