from pathlib import Path

from api.storage.r2_client import R2ObjectStore

_R2_KEYS = (
    "ECLYPTE_R2_ACCOUNT_ID",
    "ECLYPTE_R2_BUCKET",
    "ECLYPTE_R2_ACCESS_KEY_ID",
    "ECLYPTE_R2_SECRET_ACCESS_KEY",
    "ECLYPTE_R2_REGION_NAME",
    "ECLYPTE_R2_ENDPOINT_URL",
    "ECLYPTE_DEFAULT_USER_ID",
)


def _clear_r2_env(monkeypatch):
    for key in _R2_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_get_object_store_returns_none_when_env_is_missing(monkeypatch):
    from api.storage import factory

    _clear_r2_env(monkeypatch)
    monkeypatch.setattr(factory, "_API_ENV_PATH", Path("missing.env"))

    assert factory.get_object_store(required=False) is None


def test_get_object_store_loads_api_env_file(tmp_path, monkeypatch):
    from api.storage import factory

    _clear_r2_env(monkeypatch)
    env_path = tmp_path / ".env"
    fake_client = object()
    env_path.write_text(
        "\n".join(
            [
                "ECLYPTE_R2_ACCOUNT_ID=abc123",
                "ECLYPTE_R2_BUCKET=eclypte",
                "ECLYPTE_R2_ACCESS_KEY_ID=key",
                "ECLYPTE_R2_SECRET_ACCESS_KEY=secret",
                "ECLYPTE_R2_REGION_NAME=auto",
                "ECLYPTE_DEFAULT_USER_ID=local_dev",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(factory, "_API_ENV_PATH", env_path)
    monkeypatch.setattr(
        factory.R2ObjectStore,
        "_build_s3_client",
        staticmethod(lambda config: fake_client),
    )

    store = factory.get_object_store(required=True)

    assert isinstance(store, R2ObjectStore)
    assert store._config.bucket == "eclypte"
    assert factory.get_default_user_id() == "local_dev"
