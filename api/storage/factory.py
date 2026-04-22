from pathlib import Path
import os

from dotenv import load_dotenv

from .config import R2Config
from .r2_client import R2ObjectStore

_API_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_REQUIRED_R2_KEYS = (
    "ECLYPTE_R2_ACCOUNT_ID",
    "ECLYPTE_R2_BUCKET",
    "ECLYPTE_R2_ACCESS_KEY_ID",
    "ECLYPTE_R2_SECRET_ACCESS_KEY",
)


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
