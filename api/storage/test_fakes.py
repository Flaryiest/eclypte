from dataclasses import dataclass
import json

from .r2_client import ObjectHead


@dataclass
class _StoredObject:
    body: bytes
    content_type: str | None
    metadata: dict[str, str]


class InMemoryObjectStore:
    def __init__(self):
        self.objects: dict[str, _StoredObject] = {}

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.objects[key] = _StoredObject(
            body=data,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key].body

    def put_json(self, key: str, data: dict) -> None:
        self.put_bytes(
            key,
            json.dumps(data, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def get_json(self, key: str) -> dict:
        return json.loads(self.get_bytes(key).decode("utf-8"))

    def head(self, key: str) -> ObjectHead:
        obj = self.objects[key]
        return ObjectHead(
            key=key,
            size_bytes=len(obj.body),
            content_type=obj.content_type,
            metadata=obj.metadata,
            etag="memory-etag",
        )

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))
