from api.storage.config import R2Config
from api.storage.keys import (
    file_manifest_key,
    file_version_blob_key,
    file_version_meta_key,
    run_event_key,
    run_manifest_key,
)
from api.storage.refs import FileRef, FileVersionRef, RunRef


def test_file_keys_use_user_file_and_version_ids():
    assert file_manifest_key(user_id="user_123", file_id="file_456") == (
        "users/user_123/files/file_456/manifest.json"
    )
    assert file_version_blob_key(
        user_id="user_123",
        file_id="file_456",
        version_id="ver_789",
    ) == "users/user_123/files/file_456/versions/ver_789/blob"
    assert file_version_meta_key(
        user_id="user_123",
        file_id="file_456",
        version_id="ver_789",
    ) == "users/user_123/files/file_456/versions/ver_789/meta.json"


def test_run_keys_are_stable_and_append_only():
    assert run_manifest_key(user_id="user_123", run_id="run_001") == (
        "users/user_123/runs/run_001/manifest.json"
    )
    key = run_event_key(
        user_id="user_123",
        run_id="run_001",
        timestamp="2026-04-21T19:00:00Z",
        event_id="evt_001",
    )
    assert key == "users/user_123/runs/run_001/events/2026-04-21T19:00:00Z_evt_001.json"


def test_refs_build_expected_storage_keys():
    file_ref = FileRef(user_id="user_123", file_id="file_456")
    version_ref = FileVersionRef(
        user_id="user_123",
        file_id="file_456",
        version_id="ver_789",
    )
    run_ref = RunRef(user_id="user_123", run_id="run_001")

    assert file_ref.manifest_key == "users/user_123/files/file_456/manifest.json"
    assert version_ref.blob_key == "users/user_123/files/file_456/versions/ver_789/blob"
    assert version_ref.meta_key == "users/user_123/files/file_456/versions/ver_789/meta.json"
    assert run_ref.manifest_key == "users/user_123/runs/run_001/manifest.json"


def test_r2_config_builds_endpoint_from_account_id(monkeypatch):
    monkeypatch.setenv("ECLYPTE_R2_ACCOUNT_ID", "abc123")
    monkeypatch.setenv("ECLYPTE_R2_BUCKET", "eclypte")
    monkeypatch.setenv("ECLYPTE_R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("ECLYPTE_R2_SECRET_ACCESS_KEY", "secret")

    config = R2Config.from_env()

    assert config.bucket == "eclypte"
    assert config.endpoint_url == "https://abc123.r2.cloudflarestorage.com"
