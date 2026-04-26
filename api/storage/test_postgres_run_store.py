import json

from api.storage.models import RunManifest, RunStep
from api.storage.postgres_run_store import PostgresRunStore
from api.storage.refs import RunRef


class FakePostgresPool:
    def __init__(self):
        self.manifests = {}
        self.events = {}
        self.progress = {}
        self.statements = []

    def connection(self):
        return FakePostgresConnection(self)


class FakePostgresConnection:
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def cursor(self):
        return FakePostgresCursor(self.pool)


class FakePostgresCursor:
    def __init__(self, pool):
        self.pool = pool
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def execute(self, sql, params=None):
        self.pool.statements.append(sql)
        normalized = " ".join(sql.lower().split())
        params = params or ()

        if (
            normalized.startswith("create table")
            or normalized.startswith("create index")
            or normalized.startswith("alter table")
        ):
            return

        if normalized.startswith("insert into run_manifests"):
            (
                owner_user_id,
                run_id,
                workflow_type,
                status,
                inputs,
                outputs,
                steps,
                current_step,
                last_error,
                created_at,
                updated_at,
                archived_at,
                archived_reason,
            ) = params
            self.pool.manifests[(owner_user_id, run_id)] = {
                "owner_user_id": owner_user_id,
                "run_id": run_id,
                "workflow_type": workflow_type,
                "status": status,
                "inputs": json.loads(inputs),
                "outputs": json.loads(outputs),
                "steps": json.loads(steps),
                "current_step": current_step,
                "last_error": last_error,
                "created_at": created_at,
                "updated_at": updated_at,
                "archived_at": archived_at,
                "archived_reason": archived_reason,
            }
            return

        if normalized.startswith("select") and "from run_manifests" in normalized:
            if "run_id = %s" in normalized:
                self.rows = [self.pool.manifests.get((params[0], params[1]))]
                return
            self.rows = sorted(
                [
                    row
                    for (owner_user_id, _), row in self.pool.manifests.items()
                    if owner_user_id == params[0]
                ],
                key=lambda item: item["updated_at"],
                reverse=True,
            )
            return

        if normalized.startswith("insert into run_events"):
            owner_user_id, run_id, event_id, event_type, timestamp, payload = params
            self.pool.events.setdefault((owner_user_id, run_id), {}).setdefault(
                event_id,
                {
                    "owner_user_id": owner_user_id,
                    "run_id": run_id,
                    "event_id": event_id,
                    "event_type": event_type,
                    "timestamp": timestamp,
                    "payload": json.loads(payload),
                },
            )
            return

        if normalized.startswith("insert into run_stage_progress"):
            owner_user_id, run_id, stage, percent, detail, event_id, timestamp, payload = params
            key = (owner_user_id, run_id, stage)
            current = self.pool.progress.get(key)
            if current is None or current["timestamp"] <= timestamp:
                self.pool.progress[key] = {
                    "owner_user_id": owner_user_id,
                    "run_id": run_id,
                    "stage": stage,
                    "percent": percent,
                    "detail": detail,
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "payload": json.loads(payload),
                }
            return

        if normalized.startswith("select") and "from run_events" in normalized:
            rows = list(self.pool.events.get((params[0], params[1]), {}).values())
            self.rows = sorted(rows, key=lambda item: (item["timestamp"], item["event_id"]))
            return

        if normalized.startswith("select") and "from run_stage_progress" in normalized:
            rows = [
                row
                for (owner_user_id, run_id, _), row in self.pool.progress.items()
                if owner_user_id == params[0] and run_id == params[1]
            ]
            self.rows = sorted(rows, key=lambda item: item["stage"])
            return

        raise AssertionError(f"unhandled SQL: {sql}")

    def fetchone(self):
        return self.rows[0] if self.rows and self.rows[0] is not None else None

    def fetchall(self):
        return [row for row in self.rows if row is not None]


def test_postgres_run_store_round_trips_runs_events_and_latest_progress():
    store = PostgresRunStore(FakePostgresPool())
    run_ref = RunRef(user_id="user_123", run_id="run_001")
    manifest = RunManifest(
        run_id=run_ref.run_id,
        owner_user_id=run_ref.user_id,
        workflow_type="edit_pipeline",
        status="running",
        inputs={"title": "AMV"},
        outputs={},
        steps=[RunStep(name="timeline", status="running")],
        current_step="timeline",
        last_error=None,
        created_at="2026-04-21T19:00:00Z",
        updated_at="2026-04-21T19:00:00Z",
    )

    store.save_run_manifest(manifest)
    store.append_run_event(
        run_ref=run_ref,
        event_type="progress",
        timestamp="2026-04-21T19:02:00Z",
        event_id="evt_progress_new",
        payload={"stage": "timeline", "percent": 75, "detail": "Planning shots"},
    )
    store.append_run_event(
        run_ref=run_ref,
        event_type="progress",
        timestamp="2026-04-21T19:01:00Z",
        event_id="evt_progress_old",
        payload={"stage": "timeline", "percent": 20, "detail": "Older event"},
    )

    loaded = store.load_run_manifest(run_ref)
    listed = store.list_run_manifests("user_123")
    events = store.list_run_events(run_ref)
    latest = store.list_latest_run_progress(run_ref)

    assert loaded == manifest
    assert listed == [manifest]
    assert [event.event_id for event in events] == ["evt_progress_old", "evt_progress_new"]
    assert latest["timeline"]["percent"] == 75
    assert latest["timeline"]["detail"] == "Planning shots"


def test_postgres_run_store_schema_contains_required_tables():
    pool = FakePostgresPool()

    PostgresRunStore(pool)

    ddl = "\n".join(pool.statements)
    assert "run_manifests" in ddl
    assert "run_events" in ddl
    assert "run_stage_progress" in ddl
