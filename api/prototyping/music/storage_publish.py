from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from api.storage.models import RunManifest
from api.storage.refs import FileRef
from api.storage.repository import StorageRepository


@dataclass(frozen=True)
class PublishedArtifact:
    file_id: str
    version_id: str


@dataclass(frozen=True)
class MusicPublishSummary:
    run_id: str
    audio: PublishedArtifact
    analysis: PublishedArtifact
    lyrics: PublishedArtifact


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish_music_artifacts(
    *,
    repository: StorageRepository,
    user_id: str,
    wav_path: Path,
    analysis_path: Path,
    lyrics_path: Path,
) -> MusicPublishSummary:
    run_id = f"run_music_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    repository.save_run_manifest(
        RunManifest(
            run_id=run_id,
            owner_user_id=user_id,
            workflow_type="music_pipeline",
            status="completed",
            inputs={},
            outputs={},
            steps=[],
            current_step=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
    )

    audio_ref = FileRef(
        user_id=user_id,
        file_id=f"file_audio_{uuid.uuid4().hex[:12]}",
    )
    repository.create_file_manifest(
        file_ref=audio_ref,
        kind="song_audio",
        display_name=wav_path.name,
        source_run_id=run_id,
    )
    audio_version = repository.publish_bytes(
        file_ref=audio_ref,
        body=wav_path.read_bytes(),
        content_type="audio/wav",
        original_filename=wav_path.name,
        created_by_step="upload_song",
        derived_from_step="upload_song",
        input_file_version_ids=[],
        derived_from_run_id=run_id,
    )

    analysis_ref = FileRef(
        user_id=user_id,
        file_id=f"file_analysis_{uuid.uuid4().hex[:12]}",
    )
    repository.create_file_manifest(
        file_ref=analysis_ref,
        kind="music_analysis",
        display_name=analysis_path.name,
        source_run_id=run_id,
    )
    analysis_version = repository.publish_json(
        file_ref=analysis_ref,
        data=json.loads(analysis_path.read_text(encoding="utf-8")),
        original_filename=analysis_path.name,
        created_by_step="analyze_music",
        derived_from_step="analyze_music",
        input_file_version_ids=[audio_version.version_id],
        derived_from_run_id=run_id,
    )

    lyrics_ref = FileRef(
        user_id=user_id,
        file_id=f"file_lyrics_{uuid.uuid4().hex[:12]}",
    )
    repository.create_file_manifest(
        file_ref=lyrics_ref,
        kind="lyrics",
        display_name=lyrics_path.name,
        source_run_id=run_id,
    )
    lyrics_version = repository.publish_bytes(
        file_ref=lyrics_ref,
        body=lyrics_path.read_text(encoding="utf-8").encode("utf-8"),
        content_type="text/plain",
        original_filename=lyrics_path.name,
        created_by_step="fetch_lyrics",
        derived_from_step="fetch_lyrics",
        input_file_version_ids=[audio_version.version_id],
        derived_from_run_id=run_id,
    )

    return MusicPublishSummary(
        run_id=run_id,
        audio=PublishedArtifact(
            file_id=audio_ref.file_id,
            version_id=audio_version.version_id,
        ),
        analysis=PublishedArtifact(
            file_id=analysis_ref.file_id,
            version_id=analysis_version.version_id,
        ),
        lyrics=PublishedArtifact(
            file_id=lyrics_ref.file_id,
            version_id=lyrics_version.version_id,
        ),
    )
