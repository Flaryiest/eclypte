from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid


def emit_progress(progress_context: dict | None, percent: int, detail: str) -> None:
    if not progress_context:
        return
    r2_config = progress_context.get("r2_config") or {}
    user_id = progress_context.get("user_id")
    run_id = progress_context.get("run_id")
    stage = progress_context.get("stage")
    bucket = r2_config.get("bucket")
    if not user_id or not run_id or not stage or not bucket:
        return

    import boto3

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    event_id = f"evt_progress_{uuid.uuid4().hex[:12]}"
    key = f"users/{user_id}/runs/{run_id}/events/{timestamp}_{event_id}.json"
    client = boto3.client(
        "s3",
        endpoint_url=r2_config["endpoint_url"],
        aws_access_key_id=r2_config["access_key_id"],
        aws_secret_access_key=r2_config["secret_access_key"],
        region_name=r2_config.get("region_name", "auto"),
    )
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(
            {
                "event_id": event_id,
                "run_id": run_id,
                "owner_user_id": user_id,
                "event_type": "progress",
                "timestamp": timestamp,
                "payload": {
                    "stage": stage,
                    "percent": max(0, min(100, int(percent))),
                    "detail": detail,
                },
            },
            indent=2,
        ).encode("utf-8"),
        ContentType="application/json",
    )
