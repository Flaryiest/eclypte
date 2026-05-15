from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict


SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".aac"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
INCOMING_PREFIX = "incoming/collections/"


class UnsupportedImportObject(ValueError):
    pass


class ImportCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str
    source_key: str
    source_etag: str
    source_size_bytes: int
    collection_slug: str
    media_role: Literal["song", "video"]
    kind: Literal["song_audio", "source_video"]
    original_filename: str
    source_suffix: str
    output_filename: str
    output_content_type: str

    def collection_tag(self) -> str:
        return f"collection:{self.collection_slug}"

    def run_inputs(self) -> dict[str, str]:
        return {
            "source_bucket": self.bucket,
            "source_key": self.source_key,
            "source_etag": self.source_etag,
            "source_size_bytes": str(self.source_size_bytes),
            "collection_slug": self.collection_slug,
            "media_role": self.media_role,
            "import_kind": self.kind,
            "original_filename": self.original_filename,
            "output_filename": self.output_filename,
        }


def parse_import_candidate(
    *,
    bucket: str,
    key: str,
    etag: str | None,
    size_bytes: int | None,
) -> ImportCandidate:
    parts = key.split("/")
    if len(parts) < 5 or parts[0] != "incoming" or parts[1] != "collections":
        raise UnsupportedImportObject(
            "expected key under incoming/collections/{collection_slug}/songs/ or videos/"
        )
    collection_slug = parts[2].strip()
    role_segment = parts[3]
    filename = "/".join(parts[4:]).strip()
    if not collection_slug or not filename:
        raise UnsupportedImportObject(
            "expected key under incoming/collections/{collection_slug}/songs/ or videos/"
        )
    if role_segment not in {"songs", "videos"}:
        raise UnsupportedImportObject("expected songs/ or videos/ under collection prefix")

    path = PurePosixPath(filename)
    suffix = path.suffix.lower()
    if role_segment == "songs":
        if suffix not in SUPPORTED_AUDIO_SUFFIXES:
            raise UnsupportedImportObject(f"unsupported audio suffix: {suffix or '(none)'}")
        media_role: Literal["song", "video"] = "song"
        kind: Literal["song_audio", "source_video"] = "song_audio"
        output_suffix = ".wav"
        content_type = "audio/wav"
    else:
        if suffix not in SUPPORTED_VIDEO_SUFFIXES:
            raise UnsupportedImportObject(f"unsupported video suffix: {suffix or '(none)'}")
        media_role = "video"
        kind = "source_video"
        output_suffix = ".mp4"
        content_type = "video/mp4"

    output_filename = f"{path.with_suffix('').name}{output_suffix}"
    return ImportCandidate(
        bucket=bucket,
        source_key=key,
        source_etag=str(etag or ""),
        source_size_bytes=int(size_bytes or 0),
        collection_slug=collection_slug,
        media_role=media_role,
        kind=kind,
        original_filename=path.name,
        source_suffix=suffix,
        output_filename=output_filename,
        output_content_type=content_type,
    )


def matching_import_run(runs, candidate: ImportCandidate):
    for run in runs:
        if (
            run.workflow_type == "bucket_import"
            and run.inputs.get("source_bucket") == candidate.bucket
            and run.inputs.get("source_key") == candidate.source_key
            and run.inputs.get("source_etag") == candidate.source_etag
            and run.archived_at is None
        ):
            return run
    return None


def active_run_count(runs, workflow_type: str) -> int:
    return sum(
        1
        for run in runs
        if run.workflow_type == workflow_type
        and run.status in {"created", "running", "blocked"}
        and run.archived_at is None
    )


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default
