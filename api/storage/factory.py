from pathlib import Path
import os

from dotenv import load_dotenv

from .config import R2Config
from .r2_client import R2ObjectStore
from .repository import StorageRepository
from .run_broadcast import RunUpdateBroadcaster
from .run_store import R2RunStore, RunStore

_API_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_REQUIRED_R2_KEYS = (
    "ECLYPTE_R2_ACCOUNT_ID",
    "ECLYPTE_R2_BUCKET",
    "ECLYPTE_R2_ACCESS_KEY_ID",
    "ECLYPTE_R2_SECRET_ACCESS_KEY",
)
_RUN_STORE_CACHE: dict[str, RunStore] = {}
_RUN_BROADCASTER_CACHE: dict[str, RunUpdateBroadcaster] = {}


def load_storage_env() -> None:
    if _API_ENV_PATH.exists():
        load_dotenv(_API_ENV_PATH, override=False)


def get_default_user_id(default: str = "local_dev") -> str:
    load_storage_env()
    return os.environ.get("ECLYPTE_DEFAULT_USER_ID", default)


def get_object_store(*, required: bool = False) -> R2ObjectStore | None:
    load_storage_env()
    missing = [key for key in _REQUIRED_R2_KEYS if not os.environ.get(key)]
    if missing:
        if required:
            joined = ", ".join(missing)
            raise RuntimeError(f"missing required R2 env vars: {joined}")
        return None
    return R2ObjectStore(R2Config.from_env())


def get_database_url(*, required: bool = False) -> str | None:
    load_storage_env()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url and required:
        raise RuntimeError("DATABASE_URL is required")
    return database_url


def get_redis_url(*, required: bool = False) -> str | None:
    load_storage_env()
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url and required:
        raise RuntimeError("REDIS_URL is required")
    return redis_url


def get_run_store(
    *,
    object_store=None,
    required: bool = False,
) -> RunStore | None:
    database_url = get_database_url(required=False)
    if database_url:
        cached = _RUN_STORE_CACHE.get(database_url)
        if cached is None:
            from .postgres_run_store import PostgresRunStore

            cached = PostgresRunStore.from_url(database_url)
            _RUN_STORE_CACHE[database_url] = cached
        return cached
    if object_store is not None:
        return R2RunStore(object_store)
    if required:
        fallback_store = get_object_store(required=True)
        assert fallback_store is not None
        return R2RunStore(fallback_store)
    return None


def get_run_broadcaster() -> RunUpdateBroadcaster | None:
    redis_url = get_redis_url(required=False)
    if not redis_url:
        return None
    cached = _RUN_BROADCASTER_CACHE.get(redis_url)
    if cached is None:
        from .redis_run_broadcast import RedisRunUpdateBroadcaster

        cached = RedisRunUpdateBroadcaster.from_url(redis_url)
        _RUN_BROADCASTER_CACHE[redis_url] = cached
    return cached


def get_storage_repository(*, required: bool = False) -> StorageRepository | None:
    object_store = get_object_store(required=required)
    if object_store is None:
        return None
    return StorageRepository(
        object_store,
        run_store=get_run_store(object_store=object_store),
        run_broadcaster=get_run_broadcaster(),
    )
