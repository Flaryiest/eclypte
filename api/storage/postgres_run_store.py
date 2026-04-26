from __future__ import annotations

import json
from typing import Any

from .models import RunEvent, RunManifest
from .refs import RunRef


RUN_MANIFEST_COLUMNS = (
    "run_id",
    "owner_user_id",
    "workflow_type",
    "status",
    "inputs",
    "outputs",
    "steps",
    "current_step",
    "last_error",
    "created_at",
    "updated_at",
)
RUN_EVENT_COLUMNS = (
    "event_id",
    "run_id",
    "owner_user_id",
    "event_type",
    "timestamp",
    "payload",
)


class PostgresRunStore:
    def __init__(self, pool, *, ensure_schema: bool = True):
        self._pool = pool
        if ensure_schema:
            self.ensure_schema()

    @classmethod
    def from_url(cls, database_url: str) -> "PostgresRunStore":
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        return cls(pool)

    def ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS run_manifests (
                owner_user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                workflow_type TEXT NOT NULL,
                status TEXT NOT NULL,
                inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
                outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
                steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                current_step TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (owner_user_id, run_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_manifests_owner_updated
            ON run_manifests (owner_user_id, updated_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS run_events (
                owner_user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                PRIMARY KEY (owner_user_id, run_id, event_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_events_run_timestamp
            ON run_events (owner_user_id, run_id, timestamp ASC, event_id ASC)
            """,
            """
            CREATE TABLE IF NOT EXISTS run_stage_progress (
                owner_user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                percent INTEGER NOT NULL,
                detail TEXT NOT NULL,
                event_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                PRIMARY KEY (owner_user_id, run_id, stage)
            )
            """,
        ]
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

    def save_run_manifest(self, manifest: RunManifest) -> RunManifest:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_manifests (
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
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                    ON CONFLICT (owner_user_id, run_id)
                    DO UPDATE SET
                        workflow_type = EXCLUDED.workflow_type,
                        status = EXCLUDED.status,
                        inputs = EXCLUDED.inputs,
                        outputs = EXCLUDED.outputs,
                        steps = EXCLUDED.steps,
                        current_step = EXCLUDED.current_step,
                        last_error = EXCLUDED.last_error,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        manifest.owner_user_id,
                        manifest.run_id,
                        manifest.workflow_type,
                        manifest.status,
                        json.dumps(manifest.inputs),
                        json.dumps(manifest.outputs),
                        json.dumps([step.model_dump(mode="json") for step in manifest.steps]),
                        manifest.current_step,
                        manifest.last_error,
                        manifest.created_at,
                        manifest.updated_at,
                    ),
                )
        return manifest

    def load_run_manifest(self, run_ref: RunRef) -> RunManifest:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {", ".join(RUN_MANIFEST_COLUMNS)}
                    FROM run_manifests
                    WHERE owner_user_id = %s AND run_id = %s
                    """,
                    (run_ref.user_id, run_ref.run_id),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(run_ref)
        return _manifest_from_row(row)

    def list_run_manifests(self, user_id: str) -> list[RunManifest]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {", ".join(RUN_MANIFEST_COLUMNS)}
                    FROM run_manifests
                    WHERE owner_user_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        return [_manifest_from_row(row) for row in rows]

    def append_run_event(
        self,
        *,
        run_ref: RunRef,
        event_type: str,
        timestamp: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> RunEvent:
        event = RunEvent(
            event_id=event_id,
            run_id=run_ref.run_id,
            owner_user_id=run_ref.user_id,
            event_type=event_type,
            timestamp=timestamp,
            payload=payload,
        )
        payload_json = json.dumps(payload)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_events (
                        owner_user_id,
                        run_id,
                        event_id,
                        event_type,
                        timestamp,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (owner_user_id, run_id, event_id) DO NOTHING
                    """,
                    (
                        run_ref.user_id,
                        run_ref.run_id,
                        event_id,
                        event_type,
                        timestamp,
                        payload_json,
                    ),
                )
                if event_type == "progress":
                    stage = str(payload.get("stage") or "")
                    if stage:
                        cur.execute(
                            """
                            INSERT INTO run_stage_progress (
                                owner_user_id,
                                run_id,
                                stage,
                                percent,
                                detail,
                                event_id,
                                timestamp,
                                payload
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                            ON CONFLICT (owner_user_id, run_id, stage)
                            DO UPDATE SET
                                percent = EXCLUDED.percent,
                                detail = EXCLUDED.detail,
                                event_id = EXCLUDED.event_id,
                                timestamp = EXCLUDED.timestamp,
                                payload = EXCLUDED.payload
                            WHERE run_stage_progress.timestamp <= EXCLUDED.timestamp
                            """,
                            (
                                run_ref.user_id,
                                run_ref.run_id,
                                stage,
                                max(0, min(100, int(payload.get("percent", 0)))),
                                str(payload.get("detail") or ""),
                                event_id,
                                timestamp,
                                payload_json,
                            ),
                        )
        return event

    def list_run_events(self, run_ref: RunRef) -> list[RunEvent]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {", ".join(RUN_EVENT_COLUMNS)}
                    FROM run_events
                    WHERE owner_user_id = %s AND run_id = %s
                    ORDER BY timestamp ASC, event_id ASC
                    """,
                    (run_ref.user_id, run_ref.run_id),
                )
                rows = cur.fetchall()
        return [_event_from_row(row) for row in rows]

    def list_latest_run_progress(self, run_ref: RunRef) -> dict[str, dict[str, Any]]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stage, percent, detail, event_id, timestamp, payload
                    FROM run_stage_progress
                    WHERE owner_user_id = %s AND run_id = %s
                    ORDER BY stage ASC
                    """,
                    (run_ref.user_id, run_ref.run_id),
                )
                rows = cur.fetchall()
        if not rows:
            return _latest_progress_from_events(self.list_run_events(run_ref))
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            stage = str(_value(row, "stage", 0))
            payload = _json_value(_value(row, "payload", 5), default={})
            if not isinstance(payload, dict):
                payload = {}
            latest[stage] = {
                "stage": stage,
                "percent": int(_value(row, "percent", 1)),
                "detail": str(_value(row, "detail", 2)),
                "timestamp": str(_value(row, "timestamp", 4)),
                "event_id": str(_value(row, "event_id", 3)),
                **payload,
            }
        return latest


def _manifest_from_row(row) -> RunManifest:
    return RunManifest.model_validate(
        {
            "run_id": _value(row, "run_id", 0),
            "owner_user_id": _value(row, "owner_user_id", 1),
            "workflow_type": _value(row, "workflow_type", 2),
            "status": _value(row, "status", 3),
            "inputs": _json_value(_value(row, "inputs", 4), default={}),
            "outputs": _json_value(_value(row, "outputs", 5), default={}),
            "steps": _json_value(_value(row, "steps", 6), default=[]),
            "current_step": _value(row, "current_step", 7),
            "last_error": _value(row, "last_error", 8),
            "created_at": _value(row, "created_at", 9),
            "updated_at": _value(row, "updated_at", 10),
        }
    )


def _event_from_row(row) -> RunEvent:
    return RunEvent.model_validate(
        {
            "event_id": _value(row, "event_id", 0),
            "run_id": _value(row, "run_id", 1),
            "owner_user_id": _value(row, "owner_user_id", 2),
            "event_type": _value(row, "event_type", 3),
            "timestamp": _value(row, "timestamp", 4),
            "payload": _json_value(_value(row, "payload", 5), default={}),
        }
    )


def _latest_progress_from_events(events: list[RunEvent]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != "progress":
            continue
        stage = str(event.payload.get("stage", ""))
        if stage:
            latest[stage] = {
                **event.payload,
                "timestamp": event.timestamp,
                "event_id": event.event_id,
            }
    return latest


def _json_value(value, *, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    return row[index]
