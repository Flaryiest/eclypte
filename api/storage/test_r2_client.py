from api.storage.config import R2Config
from api.storage.r2_client import R2ObjectStore

try:
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - botocore is installed with boto3 in normal test envs.
    ClientError = None


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
            "Metadata": kwargs.get("Metadata", {}),
        }

    def get_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            raise_missing_object(kwargs["Key"])
        body = self.objects[kwargs["Key"]]["Body"]
        return {"Body": FakeStream(body)}

    def head_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            raise_missing_object(kwargs["Key"])
        obj = self.objects[kwargs["Key"]]
        return {
            "ContentLength": len(obj["Body"]),
            "ContentType": obj["ContentType"],
            "Metadata": obj["Metadata"],
            "ETag": "etag",
        }

    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator(self.objects)


class FakePaginator:
    def __init__(self, objects):
        self.objects = objects

    def paginate(self, **kwargs):
        prefix = kwargs["Prefix"]
        contents = [
            {"Key": key}
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]
        return [{"Contents": contents}]


class FakeStream:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body


def build_store() -> R2ObjectStore:
    return R2ObjectStore(
        config=R2Config(
            account_id="acct",
            bucket="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://acct.r2.cloudflarestorage.com",
        ),
        s3_client=FakeS3Client(),
    )


def test_r2_object_store_puts_and_gets_bytes():
    store = build_store()

    store.put_bytes("key.txt", b"hello", content_type="text/plain", metadata={"kind": "test"})

    assert store.get_bytes("key.txt") == b"hello"
    head = store.head("key.txt")
    assert head.content_type == "text/plain"
    assert head.metadata["kind"] == "test"


def test_r2_object_store_round_trips_json():
    store = build_store()

    store.put_json("doc.json", {"ok": True})

    assert store.get_json("doc.json") == {"ok": True}


def test_r2_object_store_maps_missing_objects_to_key_error():
    store = build_store()

    try:
        store.get_json("missing.json")
    except KeyError as exc:
        assert exc.args == ("missing.json",)
    else:
        raise AssertionError("expected KeyError for missing JSON object")

    try:
        store.head("missing.json")
    except KeyError as exc:
        assert exc.args == ("missing.json",)
    else:
        raise AssertionError("expected KeyError for missing object head")


def raise_missing_object(key: str):
    if ClientError is None:
        raise KeyError(key)
    raise ClientError(
        {
            "Error": {"Code": "NoSuchKey", "Message": "Not Found"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )
