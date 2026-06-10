from __future__ import annotations

from pathlib import Path


def s3_client(config: dict):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name=config.get("region_name", "auto"),
    )


def download(client, bucket: str, key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        client.download_fileobj(bucket, key, f)
