from api.storage.backfill_runs import backfill_runs_from_r2
from api.storage.repository import StorageRepository
from api.storage.refs import RunRef
from api.storage.test_fakes import InMemoryObjectStore, InMemoryRunStore


def test_backfill_runs_from_r2_is_idempotent():
    source_store = InMemoryObjectStore()
    source_repo = StorageRepository(source_store)
    run = source_repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={"title": "Existing edit"},
        steps=["assets", "music", "video", "timeline", "render", "result"],
    )
    source_repo.append_run_event(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        event_type="progress",
        timestamp="2026-04-21T19:01:00Z",
        event_id="evt_progress_001",
        payload={"stage": "timeline", "percent": 55, "detail": "Planning"},
    )
    target_run_store = InMemoryRunStore()

    first = backfill_runs_from_r2(
        object_store=source_store,
        run_store=target_run_store,
        user_id="user_123",
    )
    second = backfill_runs_from_r2(
        object_store=source_store,
        run_store=target_run_store,
        user_id="user_123",
    )

    loaded = target_run_store.load_run_manifest(
        RunRef(user_id="user_123", run_id=run.run_id)
    )
    events = target_run_store.list_run_events(
        RunRef(user_id="user_123", run_id=run.run_id)
    )
    latest = target_run_store.list_latest_run_progress(
        RunRef(user_id="user_123", run_id=run.run_id)
    )

    assert first == {"runs": 1, "events": 1}
    assert second == {"runs": 1, "events": 1}
    assert loaded.workflow_type == "edit_pipeline"
    assert [event.event_id for event in events] == ["evt_progress_001"]
    assert latest["timeline"]["percent"] == 55
