from __future__ import annotations

import os
import secrets
from typing import Literal
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.export_options import resolve_export_options
from api.storage.factory import (
    get_default_user_id,
    get_object_store,
    get_run_broadcaster,
    get_run_store,
)
from api.prototyping.edit.synthesis.system_prompt import (
    SYSTEM_PROMPT as DEFAULT_SYNTHESIS_PROMPT,
)
from api.storage.models import (
    ArtifactKind,
    FileManifest,
    FileVersionMeta,
    RunEvent,
    RunManifest,
    RunStatus,
    SynthesisPromptState,
    SynthesisReferenceRecord,
)
from api.storage.r2_client import ObjectStore
from api.storage.refs import FileRef, FileVersionRef, RunRef
from api.storage.repository import StorageRepository
from api.storage.run_broadcast import RunUpdateBroadcaster
from api.storage.run_store import RunStore
from api.workflows import DefaultWorkflowRunner, WorkflowRunner

DEFAULT_CORS_ORIGINS = (
    "https://eclypte.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
UPLOAD_URL_EXPIRES_IN = 900
DOWNLOAD_URL_EXPIRES_IN = 900
EDIT_STAGE_LABELS = {
    "assets": "Asset prep",
    "music": "Music analysis",
    "video": "Video analysis",
    "timeline": "Timeline plan",
    "render": "Render",
    "result": "Result",
}
EDIT_STAGE_ORDER = list(EDIT_STAGE_LABELS)


class FileVersionInput(BaseModel):
    file_id: str
    version_id: str


class UploadCreateRequest(BaseModel):
    kind: Literal["song_audio", "source_video"]
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, gt=0)


class UploadCreateResponse(BaseModel):
    upload_id: str
    file_id: str
    version_id: str
    upload_url: str
    required_headers: dict[str, str]
    expires_in: int


class UploadCompleteRequest(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)


class DownloadUrlResponse(BaseModel):
    download_url: str
    expires_in: int


class MusicAnalysisRequest(BaseModel):
    audio: FileVersionInput


class YouTubeSongImportRequest(BaseModel):
    url: str = Field(min_length=1)


class VideoAnalysisRequest(BaseModel):
    source_video: FileVersionInput


class ExportOptionsInput(BaseModel):
    format: Literal["reels_9_16", "youtube_16_9"] = "youtube_16_9"
    audio_start_sec: float = Field(default=0.0, ge=0)
    audio_end_sec: float | None = Field(default=None, gt=0)
    crop_focus_x: float = Field(default=0.5, ge=0, le=1)


class TimelineRequest(BaseModel):
    audio: FileVersionInput
    source_video: FileVersionInput
    music_analysis: FileVersionInput
    video_analysis: FileVersionInput
    planning_mode: Literal["agent", "deterministic"] = "agent"
    creative_brief: str = ""
    max_duration_sec: float | None = Field(default=None, gt=0)
    export_options: ExportOptionsInput | None = None


class RenderRequest(BaseModel):
    timeline: FileVersionInput
    audio: FileVersionInput
    source_video: FileVersionInput


class EditJobRequest(BaseModel):
    audio: FileVersionInput
    source_video: FileVersionInput
    planning_mode: Literal["agent", "deterministic"] = "agent"
    creative_brief: str = ""
    title: str | None = None
    export_options: ExportOptionsInput | None = None


class InternalProgressRequest(BaseModel):
    user_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    percent: int = Field(ge=0, le=100)
    detail: str = ""


class EditJobStage(BaseModel):
    id: str
    label: str
    status: str
    percent: int
    detail: str


class EditJobStatus(BaseModel):
    run_id: str
    workflow_type: str
    status: RunStatus
    title: str
    progress_percent: int
    stages: list[EditJobStage]
    child_runs: dict[str, str]
    render_output: FileVersionInput | None
    last_error: str | None
    created_at: str
    updated_at: str


class AssetSummary(BaseModel):
    file_id: str
    kind: ArtifactKind
    display_name: str
    current_version_id: str | None
    created_at: str
    updated_at: str
    source_run_id: str | None
    tags: list[str]
    current_version: FileVersionMeta | None
    latest_run: RunManifest | None
    analysis: FileVersionInput | None
    archived_at: str | None
    archived_reason: str | None


class SynthesisReferencesRequest(BaseModel):
    urls: list[str] = Field(min_length=1)
    likes: int = Field(default=0, ge=0)
    views: int = Field(default=0, ge=0)


class SynthesisPromptVersionRequest(BaseModel):
    prompt_text: str = Field(min_length=1)
    label: str = Field(default="Manual edit", min_length=1)
    generated_guidance: str = ""
    source_reference_ids: list[str] = Field(default_factory=list)
    activate: bool = True


def parse_cors_origins(value: str | None = None) -> list[str]:
    raw = value if value is not None else os.environ.get("ECLYPTE_CORS_ORIGINS")
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        hostname == "youtu.be"
        or hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
    )


def create_app(
    *,
    store: ObjectStore | None = None,
    run_store: RunStore | None = None,
    run_broadcaster: RunUpdateBroadcaster | None = None,
    workflow_runner: WorkflowRunner | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Eclypte API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or parse_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    runner = workflow_runner or DefaultWorkflowRunner()

    def resolve_store() -> ObjectStore:
        resolved = store or get_object_store(required=False)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="R2 storage is not configured",
            )
        return resolved

    def repository(resolved: ObjectStore = Depends(resolve_store)) -> StorageRepository:
        selected_run_store = run_store
        if selected_run_store is None and store is None:
            selected_run_store = get_run_store(object_store=resolved)
        selected_broadcaster = run_broadcaster
        if selected_broadcaster is None:
            selected_broadcaster = get_run_broadcaster()
        return StorageRepository(
            resolved,
            run_store=selected_run_store,
            run_broadcaster=selected_broadcaster,
        )

    def resolve_run_broadcaster() -> RunUpdateBroadcaster:
        selected_broadcaster = run_broadcaster or get_run_broadcaster()
        if selected_broadcaster is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="run streaming is not configured",
            )
        return selected_broadcaster

    def user_id(x_user_id: str | None = Header(default=None)) -> str:
        return x_user_id or get_default_user_id()

    def load_version(
        repo: StorageRepository,
        uid: str,
        ref: FileVersionInput,
        expected_kind: str,
    ) -> tuple[FileManifest, FileVersionMeta]:
        try:
            manifest = repo.load_file_manifest(FileRef(user_id=uid, file_id=ref.file_id))
            meta = repo.load_file_version_meta(
                FileVersionRef(
                    user_id=uid,
                    file_id=ref.file_id,
                    version_id=ref.version_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="file version not found") from exc
        if manifest.archived_at is not None:
            raise HTTPException(status_code=400, detail="file is archived")
        if manifest.kind != expected_kind:
            raise HTTPException(
                status_code=400,
                detail=f"expected {expected_kind}, got {manifest.kind}",
            )
        return manifest, meta

    def create_workflow_run(
        repo: StorageRepository,
        uid: str,
        workflow_type: str,
        inputs: dict[str, str],
        steps: list[str],
    ) -> RunManifest:
        run = repo.create_run(
            user_id=uid,
            workflow_type=workflow_type,
            inputs=inputs,
            steps=steps,
        )
        repo.append_run_event(
            run_ref=RunRef(user_id=uid, run_id=run.run_id),
            event_type="run_created",
            timestamp=run.created_at,
            event_id="evt_created",
            payload={"workflow_type": workflow_type},
        )
        return run

    def edit_child_runs(run: RunManifest) -> dict[str, str]:
        child_runs: dict[str, str] = {}
        for stage in ("music", "video", "timeline", "render"):
            run_id = run.outputs.get(f"{stage}_run_id")
            if run_id:
                child_runs[stage] = run_id
        return child_runs

    def edit_render_output(run: RunManifest) -> FileVersionInput | None:
        file_id = run.outputs.get("render_output_file_id")
        version_id = run.outputs.get("render_output_version_id")
        if not file_id or not version_id:
            return None
        return FileVersionInput(file_id=file_id, version_id=version_id)

    def is_active_run(run: RunManifest) -> bool:
        return run.status in {"created", "running", "blocked"}

    def load_edit_run(repo: StorageRepository, uid: str, run_id: str) -> RunManifest:
        try:
            run = repo.load_run_manifest(RunRef(user_id=uid, run_id=run_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="edit job not found") from exc
        if run.workflow_type != "edit_pipeline":
            raise HTTPException(status_code=404, detail="edit job not found")
        return run

    def edit_status_from_run(
        repo: StorageRepository,
        uid: str,
        run: RunManifest,
    ) -> EditJobStatus:
        latest_progress = repo.list_latest_run_progress(RunRef(user_id=uid, run_id=run.run_id))

        step_statuses = {step.name: step.status for step in run.steps}
        stages: list[EditJobStage] = []
        for stage_id in EDIT_STAGE_ORDER:
            progress = latest_progress.get(stage_id, {})
            status_value = step_statuses.get(stage_id, "pending")
            if run.status == "completed":
                status_value = "completed"
            if run.status == "canceled":
                if stage_id == run.current_step or status_value == "running":
                    status_value = "canceled"
                elif status_value != "completed":
                    status_value = "pending"
            if run.status == "failed" and run.current_step == stage_id:
                status_value = "failed"
            percent = int(progress.get("percent", 0))
            if status_value == "completed":
                percent = 100
            stages.append(
                EditJobStage(
                    id=stage_id,
                    label=EDIT_STAGE_LABELS[stage_id],
                    status=status_value,
                    percent=max(0, min(100, percent)),
                    detail=str(progress.get("detail") or status_value),
                )
            )
        progress_percent = 100 if run.status == "completed" else round(
            sum(stage.percent for stage in stages) / len(stages)
        )
        return EditJobStatus(
            run_id=run.run_id,
            workflow_type=run.workflow_type,
            status=run.status,
            title=run.inputs.get("title") or "Untitled edit",
            progress_percent=progress_percent,
            stages=stages,
            child_runs=edit_child_runs(run),
            render_output=edit_render_output(run),
            last_error=run.last_error,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    def file_version_input(file_id: str | None, version_id: str | None) -> FileVersionInput | None:
        if not file_id or not version_id:
            return None
        return FileVersionInput(file_id=file_id, version_id=version_id)

    def analysis_for_asset(
        manifest: FileManifest,
        runs: list[RunManifest],
    ) -> tuple[FileVersionInput | None, RunManifest | None]:
        if not manifest.current_version_id:
            return None, None
        if manifest.kind == "song_audio":
            workflow_type = "music_analysis"
            input_key = "audio_version_id"
            file_key = "music_analysis_file_id"
            version_key = "music_analysis_version_id"
        elif manifest.kind == "source_video":
            workflow_type = "video_analysis"
            input_key = "source_video_version_id"
            file_key = "video_analysis_file_id"
            version_key = "video_analysis_version_id"
        else:
            return None, None
        matching = [
            run
            for run in runs
            if (
                run.workflow_type == workflow_type
                and run.inputs.get(input_key) == manifest.current_version_id
            )
            or (
                manifest.kind == "song_audio"
                and run.workflow_type == "youtube_song_import"
                and run.outputs.get("audio_version_id") == manifest.current_version_id
            )
        ]
        if not matching:
            return None, None
        latest = matching[0]
        if latest.status != "completed":
            return None, latest
        return file_version_input(
            latest.outputs.get(file_key),
            latest.outputs.get(version_key),
        ), latest

    def summarize_asset(
        repo: StorageRepository,
        manifest: FileManifest,
        runs: list[RunManifest],
        uid: str,
    ) -> AssetSummary:
        current_version = None
        if manifest.current_version_id:
            try:
                current_version = repo.load_file_version_meta(
                    FileVersionRef(
                        user_id=uid,
                        file_id=manifest.file_id,
                        version_id=manifest.current_version_id,
                    )
                )
            except KeyError:
                current_version = None
        analysis, analysis_run = analysis_for_asset(manifest, runs)
        latest_run = analysis_run
        if latest_run is None and manifest.source_run_id:
            latest_run = next(
                (run for run in runs if run.run_id == manifest.source_run_id),
                None,
            )
        return AssetSummary(
            file_id=manifest.file_id,
            kind=manifest.kind,
            display_name=manifest.display_name,
            current_version_id=manifest.current_version_id,
            created_at=manifest.created_at,
            updated_at=manifest.updated_at,
            source_run_id=manifest.source_run_id,
            tags=manifest.tags,
            current_version=current_version,
            latest_run=latest_run,
            analysis=analysis,
            archived_at=manifest.archived_at,
            archived_reason=manifest.archived_reason,
        )

    def start_edit_job(
        *,
        request: EditJobRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository,
        uid: str,
    ) -> EditJobStatus:
        load_version(repo, uid, request.audio, "song_audio")
        load_version(repo, uid, request.source_video, "source_video")
        try:
            export_options = resolve_export_options(request.export_options, max_duration_sec=None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        title = (request.title or "").strip() or "Untitled edit"
        run = create_workflow_run(
            repo,
            uid,
            "edit_pipeline",
            {
                "title": title,
                "audio_file_id": request.audio.file_id,
                "audio_version_id": request.audio.version_id,
                "source_video_file_id": request.source_video.file_id,
                "source_video_version_id": request.source_video.version_id,
                "planning_mode": request.planning_mode,
                "creative_brief": request.creative_brief,
                **export_options.as_run_inputs(),
            },
            EDIT_STAGE_ORDER,
        )
        background_tasks.add_task(
            runner.run_edit_pipeline,
            user_id=uid,
            run_id=run.run_id,
            audio=request.audio.model_dump(),
            source_video=request.source_video.model_dump(),
            planning_mode=request.planning_mode,
            creative_brief=request.creative_brief,
            title=title,
            export_options=export_options.as_payload(),
        )
        return edit_status_from_run(repo, uid, run)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {
            "ok": True,
            "youtube_cookies_configured": bool(
                os.environ.get("ECLYPTE_YOUTUBE_COOKIES_B64")
                or os.environ.get("ECLYPTE_YOUTUBE_COOKIES")
            ),
        }

    @app.post("/internal/progress")
    def record_internal_progress(
        request: InternalProgressRequest,
        x_eclypte_internal_token: str | None = Header(
            default=None,
            alias="X-Eclypte-Internal-Token",
        ),
        repo: StorageRepository = Depends(repository),
    ) -> dict[str, bool]:
        expected = os.environ.get("ECLYPTE_INTERNAL_PROGRESS_TOKEN")
        if not expected or not x_eclypte_internal_token or not secrets.compare_digest(
            expected,
            x_eclypte_internal_token,
        ):
            raise HTTPException(status_code=403, detail="invalid internal token")
        repo.append_run_progress(
            run_ref=RunRef(user_id=request.user_id, run_id=request.run_id),
            stage=request.stage,
            percent=request.percent,
            detail=request.detail,
        )
        return {"ok": True}

    @app.post(
        "/v1/uploads",
        response_model=UploadCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_upload(
        request: UploadCreateRequest,
        repo: StorageRepository = Depends(repository),
        resolved_store: ObjectStore = Depends(resolve_store),
        uid: str = Depends(user_id),
    ) -> UploadCreateResponse:
        reservation = repo.create_upload_reservation(
            user_id=uid,
            kind=request.kind,
            filename=request.filename,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            expires_in=UPLOAD_URL_EXPIRES_IN,
        )
        upload_url = resolved_store.presigned_put_url(
            reservation.blob_key,
            content_type=request.content_type,
            expires_in=UPLOAD_URL_EXPIRES_IN,
        )
        return UploadCreateResponse(
            upload_id=reservation.upload_id,
            file_id=reservation.file_id,
            version_id=reservation.version_id,
            upload_url=upload_url,
            required_headers={"Content-Type": request.content_type},
            expires_in=UPLOAD_URL_EXPIRES_IN,
        )

    @app.post("/v1/uploads/{upload_id}/complete", response_model=FileVersionMeta)
    def complete_upload(
        upload_id: str,
        request: UploadCompleteRequest,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> FileVersionMeta:
        try:
            version_ref = repo.complete_upload_reservation(
                upload_id=upload_id,
                sha256=request.sha256,
                user_id=uid,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return repo.load_file_version_meta(version_ref)

    @app.delete("/v1/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_upload(
        upload_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> Response:
        try:
            repo.delete_upload_reservation(upload_id=upload_id, user_id=uid)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/v1/files/{file_id}", response_model=FileManifest)
    def get_file(
        file_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> FileManifest:
        try:
            return repo.load_file_manifest(FileRef(user_id=uid, file_id=file_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="file not found") from exc

    @app.get("/v1/assets", response_model=list[AssetSummary])
    def list_assets(
        kind: ArtifactKind | None = None,
        include_archived: bool = False,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[AssetSummary]:
        manifests = repo.list_file_manifests(uid)
        if kind is not None:
            manifests = [manifest for manifest in manifests if manifest.kind == kind]
        else:
            manifests = [manifest for manifest in manifests if manifest.kind != "render_output"]
        if not include_archived:
            manifests = [manifest for manifest in manifests if manifest.archived_at is None]
        manifests = [manifest for manifest in manifests if manifest.current_version_id is not None]
        runs = repo.list_run_manifests(uid)
        return [summarize_asset(repo, manifest, runs, uid) for manifest in manifests]

    @app.delete("/v1/assets/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_asset(
        file_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> Response:
        file_ref = FileRef(user_id=uid, file_id=file_id)
        try:
            manifest = repo.load_file_manifest(file_ref)
        except KeyError:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        should_hard_delete = manifest.current_version_id is None
        if manifest.current_version_id is not None:
            try:
                repo.load_file_version_meta(
                    FileVersionRef(
                        user_id=uid,
                        file_id=file_id,
                        version_id=manifest.current_version_id,
                    )
                )
            except KeyError:
                should_hard_delete = True
        if should_hard_delete:
            repo.delete_file_tree(file_ref)
        else:
            repo.archive_file_manifest(file_ref, reason="user_deleted")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/assets/{file_id}/restore", response_model=AssetSummary)
    def restore_asset(
        file_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> AssetSummary:
        file_ref = FileRef(user_id=uid, file_id=file_id)
        try:
            manifest = repo.restore_file_manifest(file_ref)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="asset not found") from exc
        runs = repo.list_run_manifests(uid)
        return summarize_asset(repo, manifest, runs, uid)

    @app.get("/v1/files/{file_id}/versions/{version_id}", response_model=FileVersionMeta)
    def get_file_version(
        file_id: str,
        version_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> FileVersionMeta:
        try:
            return repo.load_file_version_meta(
                FileVersionRef(user_id=uid, file_id=file_id, version_id=version_id)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="file version not found") from exc

    @app.get(
        "/v1/files/{file_id}/versions/{version_id}/download-url",
        response_model=DownloadUrlResponse,
    )
    def get_download_url(
        file_id: str,
        version_id: str,
        repo: StorageRepository = Depends(repository),
        resolved_store: ObjectStore = Depends(resolve_store),
        uid: str = Depends(user_id),
    ) -> DownloadUrlResponse:
        meta = get_file_version(file_id, version_id, repo, uid)
        return DownloadUrlResponse(
            download_url=resolved_store.presigned_get_url(
                meta.storage_key,
                expires_in=DOWNLOAD_URL_EXPIRES_IN,
            ),
            expires_in=DOWNLOAD_URL_EXPIRES_IN,
        )

    @app.post("/v1/music/analyses", response_model=RunManifest, status_code=202)
    def create_music_analysis(
        request: MusicAnalysisRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        load_version(repo, uid, request.audio, "song_audio")
        run = create_workflow_run(
            repo,
            uid,
            "music_analysis",
            {"audio_file_id": request.audio.file_id, "audio_version_id": request.audio.version_id},
            ["analyze_music", "publish_analysis"],
        )
        background_tasks.add_task(
            runner.run_music_analysis,
            user_id=uid,
            run_id=run.run_id,
            audio=request.audio.model_dump(),
        )
        return run

    @app.post("/v1/music/youtube-imports", response_model=RunManifest, status_code=202)
    def create_youtube_song_import(
        request: YouTubeSongImportRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        if not is_youtube_url(request.url):
            raise HTTPException(status_code=400, detail="expected a YouTube URL")
        run = create_workflow_run(
            repo,
            uid,
            "youtube_song_import",
            {"youtube_url": request.url},
            ["download_youtube_audio", "publish_audio", "analyze_music", "publish_analysis"],
        )
        background_tasks.add_task(
            runner.run_youtube_song_import,
            user_id=uid,
            run_id=run.run_id,
            url=request.url,
        )
        return run

    @app.post("/v1/video/analyses", response_model=RunManifest, status_code=202)
    def create_video_analysis(
        request: VideoAnalysisRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        load_version(repo, uid, request.source_video, "source_video")
        run = create_workflow_run(
            repo,
            uid,
            "video_analysis",
            {
                "source_video_file_id": request.source_video.file_id,
                "source_video_version_id": request.source_video.version_id,
            },
            ["analyze_video", "publish_analysis"],
        )
        background_tasks.add_task(
            runner.run_video_analysis,
            user_id=uid,
            run_id=run.run_id,
            source_video=request.source_video.model_dump(),
        )
        return run

    @app.post("/v1/timelines", response_model=RunManifest, status_code=202)
    def create_timeline(
        request: TimelineRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        load_version(repo, uid, request.audio, "song_audio")
        load_version(repo, uid, request.source_video, "source_video")
        load_version(repo, uid, request.music_analysis, "music_analysis")
        load_version(repo, uid, request.video_analysis, "video_analysis")
        planning_mode = request.planning_mode
        try:
            export_options = resolve_export_options(
                request.export_options,
                max_duration_sec=request.max_duration_sec,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        steps = (
            ["ensure_clip_index", "agent_plan_timeline", "publish_timeline"]
            if planning_mode == "agent"
            else ["plan_timeline", "publish_timeline"]
        )
        workflow_type = "timeline_agent_plan" if planning_mode == "agent" else "timeline_plan"
        run = create_workflow_run(
            repo,
            uid,
            workflow_type,
            {
                "audio_version_id": request.audio.version_id,
                "source_video_version_id": request.source_video.version_id,
                "music_analysis_version_id": request.music_analysis.version_id,
                "video_analysis_version_id": request.video_analysis.version_id,
                "planning_mode": planning_mode,
                **export_options.as_run_inputs(),
            },
            steps,
        )
        background_tasks.add_task(
            runner.run_timeline_plan,
            user_id=uid,
            run_id=run.run_id,
            audio=request.audio.model_dump(),
            source_video=request.source_video.model_dump(),
            music_analysis=request.music_analysis.model_dump(),
            video_analysis=request.video_analysis.model_dump(),
            planning_mode=planning_mode,
            creative_brief=request.creative_brief,
            max_duration_sec=request.max_duration_sec,
            export_options=export_options.as_payload(),
        )
        return run

    @app.post("/v1/renders", response_model=RunManifest, status_code=202)
    def create_render(
        request: RenderRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        load_version(repo, uid, request.timeline, "timeline")
        load_version(repo, uid, request.audio, "song_audio")
        load_version(repo, uid, request.source_video, "source_video")
        run = create_workflow_run(
            repo,
            uid,
            "render",
            {
                "timeline_version_id": request.timeline.version_id,
                "audio_version_id": request.audio.version_id,
                "source_video_version_id": request.source_video.version_id,
            },
            ["render", "publish_render"],
        )
        background_tasks.add_task(
            runner.run_render,
            user_id=uid,
            run_id=run.run_id,
            timeline=request.timeline.model_dump(),
            audio=request.audio.model_dump(),
            source_video=request.source_video.model_dump(),
        )
        return run

    @app.post("/v1/edits", response_model=EditJobStatus, status_code=202)
    def create_edit_job(
        request: EditJobRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> EditJobStatus:
        return start_edit_job(
            request=request,
            background_tasks=background_tasks,
            repo=repo,
            uid=uid,
        )

    @app.get("/v1/edits", response_model=list[EditJobStatus])
    def list_edit_jobs(
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[EditJobStatus]:
        runs = [
            run
            for run in repo.list_run_manifests(uid)
            if run.workflow_type == "edit_pipeline" and run.archived_at is None
        ]
        return [edit_status_from_run(repo, uid, run) for run in runs]

    @app.get("/v1/edits/{run_id}", response_model=EditJobStatus)
    def get_edit_job(
        run_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> EditJobStatus:
        run = load_edit_run(repo, uid, run_id)
        if run.archived_at is not None:
            raise HTTPException(status_code=404, detail="edit job not found")
        return edit_status_from_run(repo, uid, run)

    @app.post("/v1/edits/{run_id}/cancel", response_model=EditJobStatus)
    def cancel_edit_job(
        run_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> EditJobStatus:
        run = load_edit_run(repo, uid, run_id)
        if run.archived_at is not None:
            raise HTTPException(status_code=404, detail="edit job not found")
        if is_active_run(run):
            current_stage = run.current_step or "result"
            repo.append_run_progress(
                run_ref=RunRef(user_id=uid, run_id=run_id),
                stage=current_stage,
                percent=0,
                detail="Canceled by user",
            )
            run = repo.update_run_status(
                RunRef(user_id=uid, run_id=run_id),
                status="canceled",
                current_step=current_stage,
                last_error=None,
            )
            repo.append_run_event(
                run_ref=RunRef(user_id=uid, run_id=run_id),
                event_type="run_canceled",
                timestamp=run.updated_at,
                event_id="evt_canceled",
                payload={},
            )
        return edit_status_from_run(repo, uid, repo.load_run_manifest(RunRef(user_id=uid, run_id=run_id)))

    @app.delete("/v1/edits/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_edit_job(
        run_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> Response:
        run = load_edit_run(repo, uid, run_id)
        run_ref = RunRef(user_id=uid, run_id=run_id)
        if is_active_run(run):
            repo.update_run_status(
                run_ref,
                status="canceled",
                current_step=run.current_step,
                last_error=None,
            )
        repo.archive_run(run_ref, reason="user_deleted")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/edits/{run_id}/redo", response_model=EditJobStatus, status_code=202)
    def redo_edit_job(
        run_id: str,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> EditJobStatus:
        run = load_edit_run(repo, uid, run_id)
        if run.archived_at is not None:
            raise HTTPException(status_code=404, detail="edit job not found")
        audio_file_id = run.inputs.get("audio_file_id")
        audio_version_id = run.inputs.get("audio_version_id")
        source_video_file_id = run.inputs.get("source_video_file_id")
        source_video_version_id = run.inputs.get("source_video_version_id")
        if not all([audio_file_id, audio_version_id, source_video_file_id, source_video_version_id]):
            raise HTTPException(status_code=400, detail="edit job cannot be redone because inputs are incomplete")
        export_options = _export_options_from_run_inputs(run.inputs)
        return start_edit_job(
            request=EditJobRequest(
                audio=FileVersionInput(
                    file_id=str(audio_file_id),
                    version_id=str(audio_version_id),
                ),
                source_video=FileVersionInput(
                    file_id=str(source_video_file_id),
                    version_id=str(source_video_version_id),
                ),
                planning_mode=run.inputs.get("planning_mode", "agent"),
                creative_brief=run.inputs.get("creative_brief", ""),
                title=run.inputs.get("title"),
                export_options=ExportOptionsInput(**export_options) if export_options else None,
            ),
            background_tasks=background_tasks,
            repo=repo,
            uid=uid,
        )

    @app.get("/v1/runs", response_model=list[RunManifest])
    def list_runs(
        workflow_type: str | None = None,
        status: RunStatus | None = None,
        include_archived: bool = False,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[RunManifest]:
        runs = repo.list_run_manifests(uid)
        if not include_archived:
            runs = [run for run in runs if run.archived_at is None]
        if workflow_type is not None:
            runs = [run for run in runs if run.workflow_type == workflow_type]
        if status is not None:
            runs = [run for run in runs if run.status == status]
        return runs

    @app.get("/v1/runs/stream")
    async def stream_runs(
        request: Request,
        broadcaster: RunUpdateBroadcaster = Depends(resolve_run_broadcaster),
        uid: str = Depends(user_id),
    ) -> StreamingResponse:
        return StreamingResponse(
            _json_line_stream(request, broadcaster.listen(user_id=uid)),
            media_type="application/x-ndjson",
        )

    @app.get("/v1/runs/{run_id}/stream")
    async def stream_run(
        run_id: str,
        request: Request,
        broadcaster: RunUpdateBroadcaster = Depends(resolve_run_broadcaster),
        uid: str = Depends(user_id),
    ) -> StreamingResponse:
        return StreamingResponse(
            _json_line_stream(request, broadcaster.listen(user_id=uid, run_id=run_id)),
            media_type="application/x-ndjson",
        )

    @app.get("/v1/runs/{run_id}", response_model=RunManifest)
    def get_run(
        run_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        try:
            return repo.load_run_manifest(RunRef(user_id=uid, run_id=run_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/v1/runs/{run_id}/events", response_model=list[RunEvent])
    def get_run_events(
        run_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[RunEvent]:
        return repo.list_run_events(RunRef(user_id=uid, run_id=run_id))

    @app.post(
        "/v1/synthesis/references",
        response_model=list[SynthesisReferenceRecord],
        status_code=201,
    )
    def create_synthesis_references(
        request: SynthesisReferencesRequest,
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[SynthesisReferenceRecord]:
        records = [
            repo.create_synthesis_reference(
                user_id=uid,
                url=url,
                likes=request.likes,
                views=request.views,
            )
            for url in request.urls
        ]
        for record in records:
            background_tasks.add_task(
                runner.run_synthesis_reference_ingest,
                user_id=uid,
                reference_id=record.reference_id,
                url=record.url,
                likes=record.likes,
                views=record.views,
            )
        return records

    @app.get("/v1/synthesis/references", response_model=list[SynthesisReferenceRecord])
    def list_synthesis_references(
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> list[SynthesisReferenceRecord]:
        return repo.list_synthesis_references(uid)

    @app.post("/v1/synthesis/consolidations", response_model=RunManifest, status_code=202)
    def create_synthesis_consolidation(
        background_tasks: BackgroundTasks,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> RunManifest:
        run = create_workflow_run(
            repo,
            uid,
            "synthesis_consolidation",
            {},
            ["consolidate_references", "publish_prompt"],
        )
        background_tasks.add_task(
            runner.run_synthesis_consolidation,
            user_id=uid,
            run_id=run.run_id,
        )
        return run

    @app.get("/v1/synthesis/prompt", response_model=SynthesisPromptState)
    def get_synthesis_prompt(
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> SynthesisPromptState:
        return repo.get_synthesis_prompt_state(
            user_id=uid,
            default_prompt_text=DEFAULT_SYNTHESIS_PROMPT.strip(),
        )

    @app.post(
        "/v1/synthesis/prompt/versions",
        response_model=SynthesisPromptState,
        status_code=201,
    )
    def create_synthesis_prompt_version(
        request: SynthesisPromptVersionRequest,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> SynthesisPromptState:
        repo.create_synthesis_prompt_version(
            user_id=uid,
            label=request.label,
            prompt_text=request.prompt_text,
            generated_guidance=request.generated_guidance,
            source_reference_ids=request.source_reference_ids,
            activate=request.activate,
        )
        return repo.get_synthesis_prompt_state(
            user_id=uid,
            default_prompt_text=DEFAULT_SYNTHESIS_PROMPT.strip(),
        )

    @app.post(
        "/v1/synthesis/prompt/versions/{version_id}/activate",
        response_model=SynthesisPromptState,
    )
    def activate_synthesis_prompt_version(
        version_id: str,
        repo: StorageRepository = Depends(repository),
        uid: str = Depends(user_id),
    ) -> SynthesisPromptState:
        state = repo.get_synthesis_prompt_state(
            user_id=uid,
            default_prompt_text=DEFAULT_SYNTHESIS_PROMPT.strip(),
        )
        if not any(version.version_id == version_id for version in state.versions):
            raise HTTPException(status_code=404, detail="prompt version not found")
        repo.activate_synthesis_prompt_version(user_id=uid, version_id=version_id)
        return repo.get_synthesis_prompt_state(
            user_id=uid,
            default_prompt_text=DEFAULT_SYNTHESIS_PROMPT.strip(),
        )

    return app


def _export_options_from_run_inputs(inputs: dict[str, str]) -> dict[str, object] | None:
    format_value = inputs.get("export_format")
    if not format_value:
        return None
    options: dict[str, object] = {"format": format_value}
    if "audio_start_sec" in inputs:
        options["audio_start_sec"] = float(inputs["audio_start_sec"])
    if "audio_end_sec" in inputs:
        options["audio_end_sec"] = float(inputs["audio_end_sec"])
    if "crop_focus_x" in inputs:
        options["crop_focus_x"] = float(inputs["crop_focus_x"])
    return options


async def _json_line_stream(request: Request, messages):
    async for message in messages:
        if await request.is_disconnected():
            break
        yield json_dumps_line(message)


def json_dumps_line(value) -> str:
    import json

    return f"{json.dumps(value, separators=(',', ':'))}\n"
