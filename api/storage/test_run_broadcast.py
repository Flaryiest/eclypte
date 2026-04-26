from api.storage.models import RunEvent, RunManifest
from api.storage.refs import RunRef
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingRunBroadcaster:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.manifests: list[RunManifest] = []
        self.events: list[RunEvent] = []

    def publish_run_manifest(self, manifest: RunManifest) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.manifests.append(manifest)

    def publish_run_event(self, event: RunEvent) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.events.append(event)


def test_repository_broadcasts_run_manifest_and_progress_event_after_durable_write():
    broadcaster = RecordingRunBroadcaster()
    repo = StorageRepository(
        InMemoryObjectStore(),
        run_broadcaster=broadcaster,
    )

    run = repo.create_run(
        user_id="user_123",
        workflow_type="edit_pipeline",
        inputs={"title": "Live edit"},
        steps=["assets", "music"],
    )
    event = repo.append_run_progress(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        stage="music",
        percent=30,
        detail="Analyzing",
    )

    assert broadcaster.manifests == [run]
    assert broadcaster.events == [event]
    assert repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id)) == run
    assert repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id)) == [event]


def test_broadcast_failure_does_not_break_durable_run_writes():
    repo = StorageRepository(
        InMemoryObjectStore(),
        run_broadcaster=RecordingRunBroadcaster(fail=True),
    )

    run = repo.create_run(
        user_id="user_123",
        workflow_type="music_analysis",
        inputs={"audio_version_id": "ver_audio"},
        steps=["analyze_music"],
    )
    event = repo.append_run_progress(
        run_ref=RunRef(user_id="user_123", run_id=run.run_id),
        stage="analyze_music",
        percent=55,
        detail="Reading audio",
    )

    loaded = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    events = repo.list_run_events(RunRef(user_id="user_123", run_id=run.run_id))
    assert loaded.run_id == run.run_id
    assert events == [event]
