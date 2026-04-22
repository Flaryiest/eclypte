from pathlib import Path

from .refs import FileVersionRef
from .repository import StorageRepository


def stage_version_to_tempdir(
    *,
    repository: StorageRepository,
    version_ref: FileVersionRef,
    temp_dir: Path,
    filename: str,
) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    target = temp_dir / filename
    body = repository.read_version_bytes(version_ref)
    target.write_bytes(body)
    return target
