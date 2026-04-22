from dataclasses import dataclass

from .keys import (
    file_manifest_key,
    file_version_blob_key,
    file_version_meta_key,
    run_manifest_key,
)


@dataclass(frozen=True)
class FileRef:
    user_id: str
    file_id: str

    @property
    def manifest_key(self) -> str:
        return file_manifest_key(user_id=self.user_id, file_id=self.file_id)


@dataclass(frozen=True)
class FileVersionRef:
    user_id: str
    file_id: str
    version_id: str

    @property
    def blob_key(self) -> str:
        return file_version_blob_key(
            user_id=self.user_id,
            file_id=self.file_id,
            version_id=self.version_id,
        )

    @property
    def meta_key(self) -> str:
        return file_version_meta_key(
            user_id=self.user_id,
            file_id=self.file_id,
            version_id=self.version_id,
        )


@dataclass(frozen=True)
class RunRef:
    user_id: str
    run_id: str

    @property
    def manifest_key(self) -> str:
        return run_manifest_key(user_id=self.user_id, run_id=self.run_id)
