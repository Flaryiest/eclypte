from __future__ import annotations

import argparse
import json

from .factory import get_object_store, get_run_store, load_storage_env
from .models import RunEvent, RunManifest
from .refs import RunRef
from .r2_client import ObjectStore
from .run_store import R2RunStore, RunStore


def backfill_runs_from_r2(
    *,
    object_store: ObjectStore,
    run_store: RunStore,
    user_id: str | None = None,
) -> dict[str, int]:
    run_count = 0
    event_count = 0
    for key in _manifest_keys(object_store, user_id=user_id):
        parsed = _parse_run_manifest_key(key)
        if parsed is None:
            continue
        owner_user_id, run_id = parsed
        manifest = RunManifest.model_validate(object_store.get_json(key))
        run_store.save_run_manifest(manifest)
        run_count += 1
        event_prefix = f"users/{owner_user_id}/runs/{run_id}/events/"
        for event_key in sorted(object_store.list_keys(event_prefix)):
            event = RunEvent.model_validate(object_store.get_json(event_key))
            run_store.append_run_event(
                run_ref=RunRef(user_id=event.owner_user_id, run_id=event.run_id),
                event_type=event.event_type,
                timestamp=event.timestamp,
                event_id=event.event_id,
                payload=event.payload,
            )
            event_count += 1
    return {"runs": run_count, "events": event_count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill R2 run manifests and events into Postgres."
    )
    parser.add_argument("--user-id", help="Only backfill one user's runs.")
    args = parser.parse_args(argv)

    load_storage_env()
    object_store = get_object_store(required=True)
    assert object_store is not None
    run_store = get_run_store(object_store=object_store, required=True)
    if isinstance(run_store, R2RunStore):
        raise RuntimeError("DATABASE_URL is required for Postgres run backfill")
    counts = backfill_runs_from_r2(
        object_store=object_store,
        run_store=run_store,
        user_id=args.user_id,
    )
    print(json.dumps(counts, indent=2))
    return 0


def _manifest_keys(object_store: ObjectStore, *, user_id: str | None) -> list[str]:
    prefix = f"users/{user_id}/runs/" if user_id else "users/"
    return sorted(
        key
        for key in object_store.list_keys(prefix)
        if key.endswith("/manifest.json") and _parse_run_manifest_key(key) is not None
    )


def _parse_run_manifest_key(key: str) -> tuple[str, str] | None:
    parts = key.split("/")
    if len(parts) != 5:
        return None
    if parts[0] != "users" or parts[2] != "runs" or parts[4] != "manifest.json":
        return None
    return parts[1], parts[3]


if __name__ == "__main__":
    raise SystemExit(main())
