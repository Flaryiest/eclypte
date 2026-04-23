from api.storage.config import R2Config
from api.storage.r2_client import R2ObjectStore


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, client_method, Params, ExpiresIn):
        self.calls.append((client_method, Params, ExpiresIn))
        return f"https://signed.example/{client_method}/{Params['Key']}"


def test_r2_object_store_creates_presigned_put_and_get_urls():
    client = FakeS3Client()
    store = R2ObjectStore(
        config=R2Config(
            account_id="acct",
            bucket="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://acct.r2.cloudflarestorage.com",
        ),
        s3_client=client,
    )

    put_url = store.presigned_put_url(
        "users/u/files/f/versions/v/blob",
        content_type="video/mp4",
        expires_in=900,
    )
    get_url = store.presigned_get_url(
        "users/u/files/f/versions/v/blob",
        expires_in=300,
    )

    assert put_url.startswith("https://signed.example/put_object/")
    assert get_url.startswith("https://signed.example/get_object/")
    assert client.calls[0][1]["ContentType"] == "video/mp4"
    assert client.calls[0][2] == 900
