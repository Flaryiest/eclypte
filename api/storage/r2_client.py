from dataclasses import dataclass
import json
from typing import Any, Protocol

from .config import R2Config


@dataclass(frozen=True)
class ObjectHead:
    key: str
    size_bytes: int
    content_type: str | None
    metadata: dict[str, str]
    etag: str | None


class ObjectStore(Protocol):
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...
    def put_json(self, key: str, data: dict[str, Any]) -> None: ...
    def get_json(self, key: str) -> dict[str, Any]: ...
    def head(self, key: str) -> ObjectHead: ...
    def delete(self, key: str) -> None: ...
    def list_keys(self, prefix: str) -> list[str]: ...


class R2ObjectStore:
    def __init__(self, config: R2Config, *, s3_client=None):
        self._config = config
        self._client = s3_client or self._build_s3_client(config)

    @staticmethod
    def _build_s3_client(config: R2Config):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region_name,
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        payload = {
            "Bucket": self._config.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type is not None:
            payload["ContentType"] = content_type
        if metadata:
            payload["Metadata"] = metadata
        self._client.put_object(**payload)

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._config.bucket, Key=key)
        return response["Body"].read()

    def put_json(self, key: str, data: dict[str, Any]) -> None:
        self.put_bytes(
            key,
            json.dumps(data, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def get_json(self, key: str) -> dict[str, Any]:
        return json.loads(self.get_bytes(key).decode("utf-8"))

    def head(self, key: str) -> ObjectHead:
        response = self._client.head_object(Bucket=self._config.bucket, Key=key)
        return ObjectHead(
            key=key,
            size_bytes=response["ContentLength"],
            content_type=response.get("ContentType"),
            metadata=response.get("Metadata", {}),
            etag=response.get("ETag"),
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._config.bucket, Key=key)

    def list_keys(self, prefix: str) -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._config.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                keys.append(item["Key"])
        return keys
