from __future__ import annotations

import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from api.youtube_download import (
    YoutubeDownloadAttempt,
    YoutubeDownloadError,
    YoutubeDownloadResult,
    download_youtube_wav,
)
from api.prototyping.edit.synthesis.system_prompt import (
    SYSTEM_PROMPT as DEFAULT_SYNTHESIS_PROMPT,
)
from api.storage.config import R2Config
from api.storage.factory import get_storage_repository, load_storage_env
from api.storage.refs import FileRef, FileVersionRef, RunRef
from api.storage.repository import StorageRepository

DEFAULT_CREATIVE_BRIEF = (
    "Create a polished AMV that fits the full song, opens with a strong hook, "
    "uses unique source moments, and follows the source story with clear pacing."
)
CLIP_INDEX_CONTENT_TYPE = "application/x-numpy-data"
TIMELINE_COVERAGE_TOLERANCE_SEC = 0.75


class WorkflowRunner(Protocol):
    def run_music_analysis(self, **kwargs) -> None: ...
    def run_youtube_song_import(self, **kwargs) -> None: ...
    def run_video_analysis(self, **kwargs) -> None: ...
    def run_timeline_plan(self, **kwargs) -> None: ...
    def run_render(self, **kwargs) -> None: ...
    def run_edit_pipeline(self, **kwargs) -> None: ...
    def run_synthesis_reference_ingest(self, **kwargs) -> None: ...
    def run_synthesis_consolidation(self, **kwargs) -> None: ...


class DefaultWorkflowRunner:
    """Railway-side workflow runner.

    The API injects this behind FastAPI BackgroundTasks. Tests replace it with
    a recording fake, so normal verification never calls live Modal or R2.
    """

    def _repository(self) -> StorageRepository:
        repository = get_storage_repository(required=True)
        assert repository is not None
        return repository

    def _r2_config_payload(self) -> dict[str, str]:
        load_storage_env()
        config = R2Config.from_env()
        return {
            "bucket": config.bucket,
            "endpoint_url": config.endpoint_url,
            "access_key_id": config.access_key_id,
            "secret_access_key": config.secret_access_key,
            "region_name": config.region_name,
        }

    def _progress_context(self, *, user_id: str, run_id: str, stage: str) -> dict:
        try:
            r2_config = self._r2_config_payload()
        except Exception:
            r2_config = {}
        context = {
            "r2_config": r2_config,
            "user_id": user_id,
            "run_id": run_id,
            "stage": stage,
        }
        progress_url = os.environ.get("ECLYPTE_INTERNAL_PROGRESS_URL")
        progress_token = os.environ.get("ECLYPTE_INTERNAL_PROGRESS_TOKEN")
        if progress_url and progress_token:
            context.update(
                {
                    "progress_api_url": progress_url,
                    "progress_token": progress_token,
                }
            )
        return context

    def _mark_failed(self, repo: StorageRepository, user_id: str, run_id: str, exc: Exception) -> None:
        repo.update_run_status(
            RunRef(user_id=user_id, run_id=run_id),
            status="failed",
            last_error=str(exc),
        )

    def _append_progress_context(
        self,
        repo: StorageRepository,
        progress_context: dict | None,
        percent: int,
        detail: str,
    ) -> None:
        if not progress_context:
            return
        user_id = progress_context.get("user_id")
        run_id = progress_context.get("run_id")
        stage = progress_context.get("stage")
        if not user_id or not run_id or not stage:
            return
        repo.append_run_progress(
            run_ref=RunRef(user_id=str(user_id), run_id=str(run_id)),
            stage=str(stage),
            percent=percent,
            detail=detail,
        )

    def _scaled_progress_context(
        self,
        progress_context: dict | None,
        *,
        percent_start: int,
        percent_end: int,
    ) -> dict | None:
        if not progress_context:
            return None
        return {
            **progress_context,
            "percent_start": percent_start,
            "percent_end": percent_end,
        }

    def run_edit_pipeline(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        audio = kwargs["audio"]
        source_video = kwargs["source_video"]
        planning_mode = kwargs.get("planning_mode", "agent")
        creative_brief = kwargs.get("creative_brief", "")
        parent_ref = RunRef(user_id=user_id, run_id=run_id)
        current_stage = "assets"

        try:
            self._set_edit_progress(repo, parent_ref, "assets", 100, "Selected saved assets")

            current_stage = "music"
            music_analysis = self._ensure_edit_music_analysis(
                repo=repo,
                user_id=user_id,
                parent_ref=parent_ref,
                audio=audio,
            )

            current_stage = "video"
            video_analysis = self._ensure_edit_video_analysis(
                repo=repo,
                user_id=user_id,
                parent_ref=parent_ref,
                source_video=source_video,
            )

            current_stage = "timeline"
            timeline = self._run_edit_timeline(
                repo=repo,
                user_id=user_id,
                parent_ref=parent_ref,
                audio=audio,
                source_video=source_video,
                music_analysis=music_analysis,
                video_analysis=video_analysis,
                planning_mode=planning_mode,
                creative_brief=creative_brief,
            )

            current_stage = "render"
            render_output = self._run_edit_render(
                repo=repo,
                user_id=user_id,
                parent_ref=parent_ref,
                timeline=timeline,
                audio=audio,
                source_video=source_video,
            )

            self._set_edit_progress(repo, parent_ref, "result", 100, "AMV is ready")
            repo.update_run_status(
                parent_ref,
                status="completed",
                current_step=None,
                outputs={
                    "render_output_file_id": render_output["file_id"],
                    "render_output_version_id": render_output["version_id"],
                },
            )
        except Exception as exc:
            repo.append_run_progress(
                run_ref=parent_ref,
                stage=current_stage,
                percent=0,
                detail=str(exc),
            )
            repo.update_run_status(
                parent_ref,
                status="failed",
                current_step=current_stage,
                last_error=str(exc),
            )

    def _set_edit_progress(
        self,
        repo: StorageRepository,
        parent_ref: RunRef,
        stage: str,
        percent: int,
        detail: str,
        outputs: dict[str, str] | None = None,
    ) -> None:
        updated = repo.update_run_status(
            parent_ref,
            status="running",
            current_step=stage,
            outputs=outputs,
        )
        if updated.status == "canceled":
            return
        repo.append_run_progress(
            run_ref=parent_ref,
            stage=stage,
            percent=percent,
            detail=detail,
        )

    def _create_child_run(
        self,
        repo: StorageRepository,
        *,
        user_id: str,
        workflow_type: str,
        inputs: dict[str, str],
        steps: list[str],
    ):
        run = repo.create_run(
            user_id=user_id,
            workflow_type=workflow_type,
            inputs=inputs,
            steps=steps,
        )
        repo.append_run_event(
            run_ref=RunRef(user_id=user_id, run_id=run.run_id),
            event_type="run_created",
            timestamp=run.created_at,
            event_id="evt_created",
            payload={"workflow_type": workflow_type},
        )
        return run

    def _ensure_edit_music_analysis(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        parent_ref: RunRef,
        audio: dict,
    ) -> dict[str, str]:
        existing = _find_completed_analysis(
            repo=repo,
            user_id=user_id,
            workflow_type="music_analysis",
            input_key="audio_version_id",
            input_version_id=audio["version_id"],
            file_key="music_analysis_file_id",
            version_key="music_analysis_version_id",
            youtube_audio_version_id=audio["version_id"],
        )
        if existing is not None:
            self._set_edit_progress(
                repo,
                parent_ref,
                "music",
                100,
                "Reused existing music analysis",
                outputs={
                    "music_analysis_file_id": existing["file_id"],
                    "music_analysis_version_id": existing["version_id"],
                },
            )
            return existing

        child = self._create_child_run(
            repo,
            user_id=user_id,
            workflow_type="music_analysis",
            inputs={"audio_file_id": audio["file_id"], "audio_version_id": audio["version_id"]},
            steps=["analyze_music", "publish_analysis"],
        )
        self._set_edit_progress(
            repo,
            parent_ref,
            "music",
            5,
            "Starting music analysis",
            outputs={"music_run_id": child.run_id},
        )
        self.run_music_analysis(
            user_id=user_id,
            run_id=child.run_id,
            audio=audio,
            progress_context=self._progress_context(
                user_id=user_id,
                run_id=parent_ref.run_id,
                stage="music",
            ),
        )
        completed = _require_completed_run(repo, user_id, child.run_id)
        analysis = _output_ref(completed, "music_analysis_file_id", "music_analysis_version_id")
        self._set_edit_progress(
            repo,
            parent_ref,
            "music",
            100,
            "Music analysis complete",
            outputs={
                "music_analysis_file_id": analysis["file_id"],
                "music_analysis_version_id": analysis["version_id"],
            },
        )
        return analysis

    def _ensure_edit_video_analysis(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        parent_ref: RunRef,
        source_video: dict,
    ) -> dict[str, str]:
        existing = _find_completed_analysis(
            repo=repo,
            user_id=user_id,
            workflow_type="video_analysis",
            input_key="source_video_version_id",
            input_version_id=source_video["version_id"],
            file_key="video_analysis_file_id",
            version_key="video_analysis_version_id",
        )
        if existing is not None:
            self._set_edit_progress(
                repo,
                parent_ref,
                "video",
                100,
                "Reused existing video analysis",
                outputs={
                    "video_analysis_file_id": existing["file_id"],
                    "video_analysis_version_id": existing["version_id"],
                },
            )
            return existing

        child = self._create_child_run(
            repo,
            user_id=user_id,
            workflow_type="video_analysis",
            inputs={
                "source_video_file_id": source_video["file_id"],
                "source_video_version_id": source_video["version_id"],
            },
            steps=["analyze_video", "publish_analysis"],
        )
        self._set_edit_progress(
            repo,
            parent_ref,
            "video",
            5,
            "Starting video analysis",
            outputs={"video_run_id": child.run_id},
        )
        self.run_video_analysis(
            user_id=user_id,
            run_id=child.run_id,
            source_video=source_video,
            progress_context=self._progress_context(
                user_id=user_id,
                run_id=parent_ref.run_id,
                stage="video",
            ),
        )
        completed = _require_completed_run(repo, user_id, child.run_id)
        analysis = _output_ref(completed, "video_analysis_file_id", "video_analysis_version_id")
        self._set_edit_progress(
            repo,
            parent_ref,
            "video",
            100,
            "Video analysis complete",
            outputs={
                "video_analysis_file_id": analysis["file_id"],
                "video_analysis_version_id": analysis["version_id"],
            },
        )
        return analysis

    def _run_edit_timeline(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        parent_ref: RunRef,
        audio: dict,
        source_video: dict,
        music_analysis: dict,
        video_analysis: dict,
        planning_mode: str,
        creative_brief: str,
    ) -> dict[str, str]:
        steps = (
            ["ensure_clip_index", "agent_plan_timeline", "publish_timeline"]
            if planning_mode == "agent"
            else ["plan_timeline", "publish_timeline"]
        )
        workflow_type = "timeline_agent_plan" if planning_mode == "agent" else "timeline_plan"
        child = self._create_child_run(
            repo,
            user_id=user_id,
            workflow_type=workflow_type,
            inputs={
                "audio_version_id": audio["version_id"],
                "source_video_version_id": source_video["version_id"],
                "music_analysis_version_id": music_analysis["version_id"],
                "video_analysis_version_id": video_analysis["version_id"],
                "planning_mode": planning_mode,
            },
            steps=steps,
        )
        self._set_edit_progress(
            repo,
            parent_ref,
            "timeline",
            5,
            "Starting timeline plan",
            outputs={"timeline_run_id": child.run_id},
        )
        self.run_timeline_plan(
            user_id=user_id,
            run_id=child.run_id,
            audio=audio,
            source_video=source_video,
            music_analysis=music_analysis,
            video_analysis=video_analysis,
            planning_mode=planning_mode,
            creative_brief=creative_brief,
            max_duration_sec=None,
            progress_context=self._progress_context(
                user_id=user_id,
                run_id=parent_ref.run_id,
                stage="timeline",
            ),
        )
        completed = _require_completed_run(repo, user_id, child.run_id)
        timeline = _output_ref(completed, "timeline_file_id", "timeline_version_id")
        self._set_edit_progress(
            repo,
            parent_ref,
            "timeline",
            100,
            "Timeline plan complete",
            outputs={
                "timeline_file_id": timeline["file_id"],
                "timeline_version_id": timeline["version_id"],
            },
        )
        return timeline

    def _run_edit_render(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        parent_ref: RunRef,
        timeline: dict,
        audio: dict,
        source_video: dict,
    ) -> dict[str, str]:
        child = self._create_child_run(
            repo,
            user_id=user_id,
            workflow_type="render",
            inputs={
                "timeline_version_id": timeline["version_id"],
                "audio_version_id": audio["version_id"],
                "source_video_version_id": source_video["version_id"],
            },
            steps=["render", "publish_render"],
        )
        self._set_edit_progress(
            repo,
            parent_ref,
            "render",
            5,
            "Starting render",
            outputs={"render_run_id": child.run_id},
        )
        self.run_render(
            user_id=user_id,
            run_id=child.run_id,
            timeline=timeline,
            audio=audio,
            source_video=source_video,
            progress_context=self._progress_context(
                user_id=user_id,
                run_id=parent_ref.run_id,
                stage="render",
            ),
        )
        completed = _require_completed_run(repo, user_id, child.run_id)
        render_output = _output_ref(completed, "render_output_file_id", "render_output_version_id")
        self._set_edit_progress(
            repo,
            parent_ref,
            "render",
            100,
            "Render complete",
            outputs={
                "render_output_file_id": render_output["file_id"],
                "render_output_version_id": render_output["version_id"],
            },
        )
        return render_output

    def run_music_analysis(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        audio = kwargs["audio"]
        progress_context = kwargs.get("progress_context")
        try:
            import modal

            audio_ref = FileVersionRef(
                user_id=user_id,
                file_id=audio["file_id"],
                version_id=audio["version_id"],
            )
            audio_meta = repo.load_file_version_meta(audio_ref)
            analyze = modal.Function.from_name("eclypte-analysis", "analyze_remote")
            args = [repo.read_version_bytes(audio_ref), audio_meta.original_filename]
            if progress_context is not None:
                args.append(progress_context)
            result = analyze.remote(*args)
            file_ref = FileRef(user_id=user_id, file_id=f"file_music_analysis_{run_id}")
            repo.create_file_manifest(
                file_ref=file_ref,
                kind="music_analysis",
                display_name=f"{audio_meta.original_filename}.json",
                source_run_id=run_id,
            )
            version = repo.publish_json(
                file_ref=file_ref,
                data=result,
                original_filename=f"{audio_meta.original_filename}.json",
                created_by_step="analyze_music",
                derived_from_step="analyze_music",
                input_file_version_ids=[audio_ref.version_id],
                derived_from_run_id=run_id,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={
                    "music_analysis_file_id": file_ref.file_id,
                    "music_analysis_version_id": version.version_id,
                },
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_youtube_song_import(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        url = kwargs["url"]
        try:
            import modal
            repo.append_run_progress(
                run_ref=RunRef(user_id=user_id, run_id=run_id),
                stage="download_youtube_audio",
                percent=5,
                detail="Starting YouTube download",
            )
            with _temporary_directory("eclypte_youtube_") as td:
                try:
                    download = _download_youtube_wav(url, Path(td))
                except YoutubeDownloadError as exc:
                    _record_youtube_download_attempts(repo, user_id, run_id, exc.attempts)
                    raise
                _record_youtube_download_attempts(repo, user_id, run_id, download.attempts)
                repo.append_run_progress(
                    run_ref=RunRef(user_id=user_id, run_id=run_id),
                    stage="download_youtube_audio",
                    percent=35,
                    detail="Downloaded YouTube audio",
                )
                title = download.title
                wav_path = download.wav_path
                filename = f"{_safe_audio_basename(title)}.wav"
                wav_bytes = wav_path.read_bytes()

            repo.append_run_progress(
                run_ref=RunRef(user_id=user_id, run_id=run_id),
                stage="publish_audio",
                percent=55,
                detail="Publishing audio asset",
            )
            audio_ref = FileRef(user_id=user_id, file_id=f"file_audio_{run_id}")
            repo.create_file_manifest(
                file_ref=audio_ref,
                kind="song_audio",
                display_name=filename,
                source_run_id=run_id,
            )
            audio_version = repo.publish_bytes(
                file_ref=audio_ref,
                body=wav_bytes,
                content_type="audio/wav",
                original_filename=filename,
                created_by_step="download_youtube_audio",
                derived_from_step="download_youtube_audio",
                input_file_version_ids=[],
                derived_from_run_id=run_id,
            )

            repo.append_run_progress(
                run_ref=RunRef(user_id=user_id, run_id=run_id),
                stage="analyze_music",
                percent=65,
                detail="Analyzing imported song",
            )
            analyze = modal.Function.from_name("eclypte-analysis", "analyze_remote")
            result = analyze.remote(wav_bytes, filename)
            analysis_ref = FileRef(user_id=user_id, file_id=f"file_music_analysis_{run_id}")
            repo.create_file_manifest(
                file_ref=analysis_ref,
                kind="music_analysis",
                display_name=f"{filename}.json",
                source_run_id=run_id,
            )
            analysis_version = repo.publish_json(
                file_ref=analysis_ref,
                data=result,
                original_filename=f"{filename}.json",
                created_by_step="analyze_music",
                derived_from_step="analyze_music",
                input_file_version_ids=[audio_version.version_id],
                derived_from_run_id=run_id,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={
                    "audio_file_id": audio_ref.file_id,
                    "audio_version_id": audio_version.version_id,
                    "music_analysis_file_id": analysis_ref.file_id,
                    "music_analysis_version_id": analysis_version.version_id,
                },
            )
            repo.append_run_progress(
                run_ref=RunRef(user_id=user_id, run_id=run_id),
                stage="publish_analysis",
                percent=100,
                detail="YouTube song imported and analyzed",
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_video_analysis(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        source_video = kwargs["source_video"]
        progress_context = kwargs.get("progress_context")
        try:
            import modal

            source_ref = FileVersionRef(
                user_id=user_id,
                file_id=source_video["file_id"],
                version_id=source_video["version_id"],
            )
            source_meta = repo.load_file_version_meta(source_ref)
            analyze = modal.Function.from_name("eclypte-video-r2", "analyze_r2")
            args = [
                self._r2_config_payload(),
                source_meta.storage_key,
                source_meta.original_filename,
            ]
            if progress_context is not None:
                args.append(progress_context)
            result = analyze.remote(*args)
            file_ref = FileRef(user_id=user_id, file_id=f"file_video_analysis_{run_id}")
            repo.create_file_manifest(
                file_ref=file_ref,
                kind="video_analysis",
                display_name=f"{source_meta.original_filename}.json",
                source_run_id=run_id,
            )
            version = repo.publish_json(
                file_ref=file_ref,
                data=result,
                original_filename=f"{source_meta.original_filename}.json",
                created_by_step="analyze_video",
                derived_from_step="analyze_video",
                input_file_version_ids=[source_ref.version_id],
                derived_from_run_id=run_id,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={
                    "video_analysis_file_id": file_ref.file_id,
                    "video_analysis_version_id": version.version_id,
                },
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_timeline_plan(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        try:
            planning_mode = kwargs.get("planning_mode", "agent")
            if planning_mode == "deterministic":
                self._run_deterministic_timeline_plan(repo, user_id, run_id, kwargs)
            else:
                self._run_agent_timeline_plan(repo, user_id, run_id, kwargs)
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def _timeline_refs(
        self,
        user_id: str,
        kwargs: dict,
    ) -> tuple[FileVersionRef, FileVersionRef, FileVersionRef, FileVersionRef]:
        music_analysis = kwargs["music_analysis"]
        video_analysis = kwargs["video_analysis"]
        audio = kwargs["audio"]
        source_video = kwargs["source_video"]
        music_ref = FileVersionRef(
            user_id=user_id,
            file_id=music_analysis["file_id"],
            version_id=music_analysis["version_id"],
        )
        video_ref = FileVersionRef(
            user_id=user_id,
            file_id=video_analysis["file_id"],
            version_id=video_analysis["version_id"],
        )
        audio_ref = FileVersionRef(
            user_id=user_id,
            file_id=audio["file_id"],
            version_id=audio["version_id"],
        )
        source_ref = FileVersionRef(
            user_id=user_id,
            file_id=source_video["file_id"],
            version_id=source_video["version_id"],
        )
        return music_ref, video_ref, audio_ref, source_ref

    def _run_deterministic_timeline_plan(
        self,
        repo: StorageRepository,
        user_id: str,
        run_id: str,
        kwargs: dict,
    ) -> None:
        from api.prototyping.edit.synthesis.planner import plan

        progress_context = kwargs.get("progress_context")
        self._append_progress_context(repo, progress_context, 10, "Loading timeline inputs")
        music_ref, video_ref, audio_ref, source_ref = self._timeline_refs(user_id, kwargs)
        song = _read_json_version(repo, music_ref)
        video = _read_json_version(repo, video_ref)
        source_meta = repo.load_file_version_meta(source_ref)
        audio_meta = repo.load_file_version_meta(audio_ref)
        self._append_progress_context(repo, progress_context, 45, "Running deterministic timeline planner")
        timeline = plan(
            song=song,
            video=video,
            source_video_path=source_meta.original_filename,
            audio_path=audio_meta.original_filename,
            max_duration_sec=kwargs.get("max_duration_sec"),
        )
        self._append_progress_context(repo, progress_context, 90, "Publishing timeline")
        self._publish_timeline(
            repo=repo,
            user_id=user_id,
            run_id=run_id,
            timeline=timeline,
            created_by_step="plan_timeline",
            input_version_ids=[
                audio_ref.version_id,
                source_ref.version_id,
                music_ref.version_id,
                video_ref.version_id,
            ],
            outputs={},
        )

    def _run_agent_timeline_plan(
        self,
        repo: StorageRepository,
        user_id: str,
        run_id: str,
        kwargs: dict,
    ) -> None:
        from api.prototyping.edit.synthesis.adapter import adapt

        progress_context = kwargs.get("progress_context")
        run_ref = RunRef(user_id=user_id, run_id=run_id)
        self._append_progress_context(repo, progress_context, 10, "Loading timeline inputs")
        music_ref, video_ref, audio_ref, source_ref = self._timeline_refs(user_id, kwargs)
        source_meta = repo.load_file_version_meta(source_ref)
        audio_meta = repo.load_file_version_meta(audio_ref)
        song = _read_json_version(repo, music_ref)
        video = _read_json_version(repo, video_ref)

        repo.update_run_status(run_ref, status="running", current_step="ensure_clip_index")
        self._append_progress_context(repo, progress_context, 15, "Checking CLIP index")
        clip_file_ref, clip_version_ref, clip_meta = self._ensure_clip_index(
            repo=repo,
            user_id=user_id,
            run_id=run_id,
            source_ref=source_ref,
            source_meta=source_meta,
            progress_context=self._scaled_progress_context(
                progress_context,
                percent_start=20,
                percent_end=35,
            ),
        )
        clip_outputs = {
            "clip_index_file_id": clip_file_ref.file_id,
            "clip_index_version_id": clip_version_ref.version_id,
        }

        repo.update_run_status(
            run_ref,
            status="running",
            current_step="agent_plan_timeline",
            outputs=clip_outputs,
        )
        self._append_progress_context(repo, progress_context, 40, "Loading active synthesis prompt")
        prompt_state = repo.get_synthesis_prompt_state(
            user_id=user_id,
            default_prompt_text=DEFAULT_SYNTHESIS_PROMPT.strip(),
        )
        active_prompt = prompt_state.active_prompt
        r2_config = self._r2_config_payload()

        def query_clip_index(query: str, _video_filename: str, top_k: int = 5) -> list[dict]:
            return _query_clip_index_r2(
                r2_config=r2_config,
                index_key=clip_meta.storage_key,
                query=query,
                top_k=top_k,
            )

        creative_brief = str(kwargs.get("creative_brief") or "").strip() or DEFAULT_CREATIVE_BRIEF
        self._append_progress_context(repo, progress_context, 55, "Running agent timeline planner")
        agent_output = _run_agent_synthesis(
            video_filename=source_meta.original_filename,
            instructions=creative_brief,
            song=song,
            system_prompt=active_prompt.prompt_text,
            query_clips_fn=query_clip_index,
        )
        self._append_progress_context(repo, progress_context, 70, "Adapting agent timeline")
        timeline = adapt(
            agent_output=agent_output,
            song=song,
            video=video,
            source_video_path=source_meta.original_filename,
            audio_path=audio_meta.original_filename,
        )
        self._append_progress_context(repo, progress_context, 75, "Validating timeline coverage")
        _validate_agent_timeline_coverage(timeline, song)

        self._append_progress_context(repo, progress_context, 90, "Publishing timeline")
        self._publish_timeline(
            repo=repo,
            user_id=user_id,
            run_id=run_id,
            timeline=timeline,
            created_by_step="agent_plan_timeline",
            input_version_ids=[
                audio_ref.version_id,
                source_ref.version_id,
                music_ref.version_id,
                video_ref.version_id,
                clip_version_ref.version_id,
            ],
            outputs={
                **clip_outputs,
                "synthesis_prompt_version_id": active_prompt.version_id,
            },
        )

    def _ensure_clip_index(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        run_id: str,
        source_ref: FileVersionRef,
        source_meta,
        progress_context: dict | None = None,
    ) -> tuple[FileRef, FileVersionRef, object]:
        existing = _find_clip_index_for_source(repo, user_id, source_ref.version_id)
        if existing is not None:
            self._append_progress_context(repo, progress_context, 25, "Reused existing CLIP index")
            return existing

        index_name = f"{Path(source_meta.original_filename).stem or run_id}.npz"
        file_ref = FileRef(user_id=user_id, file_id=f"file_clip_index_{run_id}")
        repo.create_file_manifest(
            file_ref=file_ref,
            kind="clip_index",
            display_name=index_name,
            source_run_id=run_id,
        )
        version_ref = repo.reserve_file_version(file_ref)
        output = _build_clip_index_r2(
            r2_config=self._r2_config_payload(),
            source_key=source_meta.storage_key,
            filename=source_meta.original_filename,
            output_key=version_ref.blob_key,
            progress_context=progress_context,
        )
        repo.record_existing_version(
            file_ref=file_ref,
            version_ref=version_ref,
            content_type=output.get("content_type", CLIP_INDEX_CONTENT_TYPE),
            size_bytes=int(output["size_bytes"]),
            sha256=output["sha256"],
            original_filename=index_name,
            created_by_step="ensure_clip_index",
            derived_from_step="ensure_clip_index",
            input_file_version_ids=[source_ref.version_id],
            derived_from_run_id=run_id,
        )
        return file_ref, version_ref, repo.load_file_version_meta(version_ref)

    def _publish_timeline(
        self,
        *,
        repo: StorageRepository,
        user_id: str,
        run_id: str,
        timeline,
        created_by_step: str,
        input_version_ids: list[str],
        outputs: dict[str, str],
    ) -> None:
        file_ref = FileRef(user_id=user_id, file_id=f"file_timeline_{run_id}")
        repo.create_file_manifest(
            file_ref=file_ref,
            kind="timeline",
            display_name=f"{run_id}.timeline.json",
            source_run_id=run_id,
        )
        version = repo.publish_json(
            file_ref=file_ref,
            data=timeline.model_dump(mode="json"),
            original_filename=f"{run_id}.timeline.json",
            created_by_step=created_by_step,
            derived_from_step=created_by_step,
            input_file_version_ids=input_version_ids,
            derived_from_run_id=run_id,
        )
        repo.update_run_status(
            RunRef(user_id=user_id, run_id=run_id),
            status="completed",
            outputs={
                **outputs,
                "timeline_file_id": file_ref.file_id,
                "timeline_version_id": version.version_id,
            },
        )

    def run_render(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        timeline = kwargs["timeline"]
        audio = kwargs["audio"]
        source_video = kwargs["source_video"]
        progress_context = kwargs.get("progress_context")
        try:
            import modal

            timeline_ref = FileVersionRef(
                user_id=user_id,
                file_id=timeline["file_id"],
                version_id=timeline["version_id"],
            )
            audio_ref = FileVersionRef(
                user_id=user_id,
                file_id=audio["file_id"],
                version_id=audio["version_id"],
            )
            source_ref = FileVersionRef(
                user_id=user_id,
                file_id=source_video["file_id"],
                version_id=source_video["version_id"],
            )
            timeline_meta = repo.load_file_version_meta(timeline_ref)
            audio_meta = repo.load_file_version_meta(audio_ref)
            source_meta = repo.load_file_version_meta(source_ref)
            file_ref = FileRef(user_id=user_id, file_id=f"file_render_{run_id}")
            repo.create_file_manifest(
                file_ref=file_ref,
                kind="render_output",
                display_name=f"{run_id}.mp4",
                source_run_id=run_id,
            )
            version_ref = repo.reserve_file_version(file_ref)
            render = modal.Function.from_name("eclypte-render-r2", "render_r2")
            args = [
                self._r2_config_payload(),
                timeline_meta.storage_key,
                source_meta.storage_key,
                audio_meta.storage_key,
                version_ref.blob_key,
                f"{run_id}.mp4",
            ]
            if progress_context is not None:
                args.append(progress_context)
            output = render.remote(*args)
            repo.record_existing_version(
                file_ref=file_ref,
                version_ref=version_ref,
                content_type=output.get("content_type", "video/mp4"),
                size_bytes=int(output["size_bytes"]),
                sha256=output["sha256"],
                original_filename=f"{run_id}.mp4",
                created_by_step="render",
                derived_from_step="render",
                input_file_version_ids=[
                    timeline_ref.version_id,
                    audio_ref.version_id,
                    source_ref.version_id,
                ],
                derived_from_run_id=run_id,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={
                    "render_output_file_id": file_ref.file_id,
                    "render_output_version_id": version_ref.version_id,
                },
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_synthesis_reference_ingest(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        reference_id = kwargs["reference_id"]
        url = kwargs["url"]
        likes = int(kwargs.get("likes", 0))
        views = int(kwargs.get("views", 0))
        try:
            import tempfile
            from pathlib import Path

            from api.prototyping.edit.reference.download import download_reference
            from api.prototyping.edit.reference.ingest import (
                _run_music_analysis,
                _run_video_analysis,
            )
            from api.prototyping.edit.reference.metrics import compute_metrics

            repo.update_synthesis_reference(
                user_id=user_id,
                reference_id=reference_id,
                status="running",
            )
            with tempfile.TemporaryDirectory(prefix="eclypte_ref_api_") as td:
                media = download_reference(url, Path(td))
                music = _run_music_analysis(media.audio_wav_path)
                video = _run_video_analysis(media.video_mp4_path)
                metrics = compute_metrics(music, video)
            repo.update_synthesis_reference(
                user_id=user_id,
                reference_id=reference_id,
                status="completed",
                title=media.title,
                author=media.author,
                duration_sec=media.duration_sec,
                metrics={
                    **metrics,
                    "likes": likes,
                    "views": views,
                },
            )
        except Exception as exc:
            repo.update_synthesis_reference(
                user_id=user_id,
                reference_id=reference_id,
                status="failed",
                last_error=str(exc),
            )

    def run_synthesis_consolidation(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        try:
            from api.prototyping.edit.synthesis.system_prompt import SYSTEM_PROMPT

            references = [
                record
                for record in repo.list_synthesis_references(user_id)
                if record.status == "completed"
            ]
            guidance = _synthesis_guidance(references)
            prompt_text = SYSTEM_PROMPT.strip()
            if guidance:
                prompt_text = f"{prompt_text}\n\nReference guidance:\n{guidance}"
            version = repo.create_synthesis_prompt_version(
                user_id=user_id,
                label=f"Generated from {len(references)} references",
                prompt_text=prompt_text,
                generated_guidance=guidance,
                source_reference_ids=[record.reference_id for record in references],
                activate=True,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={"synthesis_prompt_version_id": version.version_id},
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)


def _synthesis_guidance(references) -> str:
    if not references:
        return "No completed Reel references yet. Keep the baseline AMV editing rules."
    lines = [
        "Use the completed Reel reference metrics as lightweight style guidance:",
    ]
    for record in references[:8]:
        metrics = record.metrics or {}
        title = record.title or record.url
        cuts = metrics.get("n_cuts", 0)
        scenes = metrics.get("n_scenes", 0)
        lines.append(
            f"- {record.reference_id}: {title} ({cuts} cuts across {scenes} scenes)."
        )
    lines.append(
        "Prefer hooks and pacing patterns supported by multiple references; keep source timestamps unique."
    )
    return "\n".join(lines)


def _find_completed_analysis(
    *,
    repo: StorageRepository,
    user_id: str,
    workflow_type: str,
    input_key: str,
    input_version_id: str,
    file_key: str,
    version_key: str,
    youtube_audio_version_id: str | None = None,
) -> dict[str, str] | None:
    for run in repo.list_run_manifests(user_id):
        matches_direct = (
            run.workflow_type == workflow_type
            and run.inputs.get(input_key) == input_version_id
        )
        matches_youtube_import = (
            youtube_audio_version_id is not None
            and run.workflow_type == "youtube_song_import"
            and run.outputs.get("audio_version_id") == youtube_audio_version_id
        )
        if not (matches_direct or matches_youtube_import):
            continue
        if run.status != "completed":
            continue
        file_id = run.outputs.get(file_key)
        version_id = run.outputs.get(version_key)
        if file_id and version_id:
            return {"file_id": file_id, "version_id": version_id}
    return None


def _require_completed_run(
    repo: StorageRepository,
    user_id: str,
    run_id: str,
):
    run = repo.load_run_manifest(RunRef(user_id=user_id, run_id=run_id))
    if run.status == "failed":
        raise RuntimeError(run.last_error or f"{run.workflow_type} failed")
    if run.status != "completed":
        raise RuntimeError(f"{run.workflow_type} did not complete")
    return run


def _output_ref(run, file_key: str, version_key: str) -> dict[str, str]:
    file_id = run.outputs.get(file_key)
    version_id = run.outputs.get(version_key)
    if not file_id or not version_id:
        raise RuntimeError(f"{run.workflow_type} completed without expected output")
    return {"file_id": file_id, "version_id": version_id}


def _read_json_version(repo: StorageRepository, version_ref: FileVersionRef) -> dict:
    import json

    return json.loads(repo.read_version_bytes(version_ref).decode("utf-8"))


def _find_clip_index_for_source(
    repo: StorageRepository,
    user_id: str,
    source_version_id: str,
) -> tuple[FileRef, FileVersionRef, object] | None:
    for manifest in repo.list_file_manifests(user_id):
        if manifest.kind != "clip_index" or not manifest.current_version_id:
            continue
        version_ref = FileVersionRef(
            user_id=user_id,
            file_id=manifest.file_id,
            version_id=manifest.current_version_id,
        )
        meta = repo.load_file_version_meta(version_ref)
        if source_version_id in meta.derived_from.input_file_version_ids:
            return FileRef(user_id=user_id, file_id=manifest.file_id), version_ref, meta
    return None


def _build_clip_index_r2(
    *,
    r2_config: dict[str, str],
    source_key: str,
    filename: str,
    output_key: str,
    progress_context: dict | None = None,
) -> dict:
    import modal

    build_index = modal.Function.from_name("eclypte-clip-index-r2", "build_index_r2")
    if progress_context is None:
        return build_index.remote(r2_config, source_key, filename, output_key)
    return build_index.remote(r2_config, source_key, filename, output_key, progress_context)


def _query_clip_index_r2(
    *,
    r2_config: dict[str, str],
    index_key: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    import modal

    query_index = modal.Function.from_name("eclypte-clip-index-r2", "query_index_r2")
    return query_index.remote(r2_config, index_key, query, top_k)


def _run_agent_synthesis(
    *,
    video_filename: str,
    instructions: str,
    song: dict,
    system_prompt: str,
    query_clips_fn,
) -> list[dict]:
    from api.prototyping.edit.synthesis.agent import run_synthesis_loop

    return run_synthesis_loop(
        video_filename=video_filename,
        instructions=instructions,
        song=song,
        system_prompt=system_prompt,
        query_clips_fn=query_clips_fn,
    )


def _validate_agent_timeline_coverage(timeline, song: dict) -> None:
    song_duration = float(song.get("source", {}).get("duration_sec", 0.0) or 0.0)
    if song_duration <= 0:
        return
    if float(timeline.output.duration_sec) + TIMELINE_COVERAGE_TOLERANCE_SEC < song_duration:
        raise ValueError(
            f"agent timeline duration {timeline.output.duration_sec:.3f}s is shorter "
            f"than song duration {song_duration:.3f}s"
        )


def _download_youtube_wav(url: str, workdir: Path) -> YoutubeDownloadResult:
    return download_youtube_wav(url, workdir)


def _record_youtube_download_attempts(
    repo: StorageRepository,
    user_id: str,
    run_id: str,
    attempts: list[YoutubeDownloadAttempt],
) -> None:
    run_ref = RunRef(user_id=user_id, run_id=run_id)
    for index, attempt in enumerate(attempts):
        repo.append_run_event(
            run_ref=run_ref,
            event_type="youtube_download_attempt",
            timestamp=_utc_now(),
            event_id=f"evt_{index:04d}_{uuid.uuid4().hex[:12]}",
            payload={
                "step": "download_youtube_audio",
                "provider": attempt.provider,
                "status": attempt.status,
                "detail": attempt.detail,
            },
        )


@contextmanager
def _temporary_directory(prefix: str):
    import tempfile

    temp_root = os.environ.get("ECLYPTE_TEMP_DIR")
    if temp_root:
        root = Path(temp_root)
        root.mkdir(parents=True, exist_ok=True)
        workdir = root / f"{prefix}{uuid.uuid4().hex[:12]}"
        workdir.mkdir()
        try:
            yield str(workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return
    with tempfile.TemporaryDirectory(
        prefix=prefix,
        ignore_cleanup_errors=True,
    ) as td:
        yield td


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_audio_basename(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    return (cleaned or "youtube_song")[:96]
