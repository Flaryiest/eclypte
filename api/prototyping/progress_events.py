from __future__ import annotations

from datetime import datetime, timezone
import json
import urllib.request
import uuid


def _scaled_percent(progress_context: dict, percent: int) -> int:
    try:
        start = progress_context.get("percent_start")
        end = progress_context.get("percent_end")
        if start is None or end is None:
            return int(percent)
        return round(float(start) + (float(percent) / 100.0) * (float(end) - float(start)))
    except (TypeError, ValueError):
        return int(percent)


def emit_progress(progress_context: dict | None, percent: int, detail: str) -> None:
    if not progress_context:
        return
    user_id = progress_context.get("user_id")
    run_id = progress_context.get("run_id")
    stage = progress_context.get("stage")
    if not user_id or not run_id or not stage:
        return
    resolved_percent = max(0, min(100, _scaled_percent(progress_context, percent)))
    if _emit_internal_progress(
        progress_context,
        user_id=str(user_id),
        run_id=str(run_id),
        stage=str(stage),
        percent=resolved_percent,
        detail=detail,
    ):
        return
    r2_config = progress_context.get("r2_config") or {}
    bucket = r2_config.get("bucket")
    if not bucket:
        return

    import boto3

    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
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
                    "percent": resolved_percent,
                    "detail": detail,
                },
            },
            indent=2,
        ).encode("utf-8"),
        ContentType="application/json",
    )


def _emit_internal_progress(
    progress_context: dict,
    *,
    user_id: str,
    run_id: str,
    stage: str,
    percent: int,
    detail: str,
) -> bool:
    progress_api_url = progress_context.get("progress_api_url")
    progress_token = progress_context.get("progress_token")
    if not progress_api_url or not progress_token:
        return False
    body = json.dumps(
        {
            "user_id": user_id,
            "run_id": run_id,
            "stage": stage,
            "percent": percent,
            "detail": detail,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        str(progress_api_url),
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Eclypte-Internal-Token": str(progress_token),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= int(getattr(response, "status", 200)) < 300
    except Exception:
        return False
