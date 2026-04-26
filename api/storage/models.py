from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ArtifactKind = Literal[
    "source_video",
    "song_audio",
    "lyrics",
    "music_analysis",
    "video_analysis",
    "clip_index",
    "timeline",
    "render_output",
]
RunStatus = Literal["created", "running", "blocked", "failed", "completed", "canceled"]
StepStatus = Literal["pending", "running", "completed", "failed"]
UploadStatus = Literal["created", "completed"]
SynthesisReferenceStatus = Literal["queued", "running", "completed", "failed"]


class DerivedFrom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    step_id: str
    input_file_version_ids: list[str] = Field(default_factory=list)
    params_hash: str | None = None


class FileManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str
    owner_user_id: str
    kind: ArtifactKind
    current_version_id: str | None = None
    source_run_id: str | None = None
    display_name: str
    created_at: str
    updated_at: str
    tags: list[str] = Field(default_factory=list)
    archived_at: str | None = None
    archived_reason: str | None = None


class FileVersionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    file_id: str
    owner_user_id: str
    content_type: str
    size_bytes: int
    sha256: str
    original_filename: str
    created_at: str
    created_by_step: str
    storage_key: str
    derived_from: DerivedFrom


class RunStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: StepStatus


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    owner_user_id: str
    workflow_type: str
    status: RunStatus
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    steps: list[RunStep] = Field(default_factory=list)
    current_step: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str
    archived_at: str | None = None
    archived_reason: str | None = None


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    owner_user_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class UploadReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str
    owner_user_id: str
    file_id: str
    version_id: str
    kind: ArtifactKind
    filename: str
    content_type: str
    size_bytes: int | None = None
    blob_key: str
    status: UploadStatus
    created_at: str
    expires_at: str
    completed_at: str | None = None


class SynthesisReferenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    owner_user_id: str
    url: str
    status: SynthesisReferenceStatus
    likes: int = 0
    views: int = 0
    title: str | None = None
    author: str | None = None
    duration_sec: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    created_at: str
    updated_at: str


class SynthesisPromptVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    owner_user_id: str
    label: str
    prompt_text: str
    generated_guidance: str = ""
    source_reference_ids: list[str] = Field(default_factory=list)
    created_at: str


class SynthesisPromptState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: str
    active_version_id: str
    active_prompt: SynthesisPromptVersion
    versions: list[SynthesisPromptVersion] = Field(default_factory=list)


class StoredSynthesisPromptState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: str
    active_version_id: str
