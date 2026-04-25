from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from api.storage.config import R2Config
from api.storage.factory import get_object_store, load_storage_env
from api.storage.refs import FileRef, FileVersionRef, RunRef
from api.storage.repository import StorageRepository

YOUTUBE_FORMAT_SELECTORS = (
    "234/233/140/251/bestaudio/best[acodec!=none]/best*[acodec!=none]",
    "bestaudio/best[acodec!=none]/best*[acodec!=none]",
    "best*[acodec!=none]/best*",
    None,
)
YOUTUBE_EXTRACTOR_ARG_VARIANTS = (
    None,
    {"youtube": {"player_client": ["mweb"]}},
    {"youtube": {"player_client": ["web"]}},
    {"youtube": {"player_client": ["web_safari"]}},
    {"youtube": {"player_client": ["tv"]}},
    {"youtube": {"formats": ["missing_pot"]}},
    {"youtube": {"player_client": ["mweb"], "formats": ["missing_pot"]}},
    {"youtube": {"player_client": ["web"], "formats": ["missing_pot"]}},
    {"youtube": {"player_client": ["web_safari"], "formats": ["missing_pot"]}},
    {"youtube": {"player_client": ["tv"], "formats": ["missing_pot"]}},
)
YOUTUBE_NO_COOKIE_EXTRACTOR_ARG_VARIANTS = (
    {"youtube": {"player_client": ["android_vr"]}},
)


class WorkflowRunner(Protocol):
    def run_music_analysis(self, **kwargs) -> None: ...
    def run_youtube_song_import(self, **kwargs) -> None: ...
    def run_video_analysis(self, **kwargs) -> None: ...
    def run_timeline_plan(self, **kwargs) -> None: ...
    def run_render(self, **kwargs) -> None: ...
    def run_synthesis_reference_ingest(self, **kwargs) -> None: ...
    def run_synthesis_consolidation(self, **kwargs) -> None: ...


class DefaultWorkflowRunner:
    """Railway-side workflow runner.

    The API injects this behind FastAPI BackgroundTasks. Tests replace it with
    a recording fake, so normal verification never calls live Modal or R2.
    """

    def _repository(self) -> StorageRepository:
        store = get_object_store(required=True)
        assert store is not None
        return StorageRepository(store)

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

    def _mark_failed(self, repo: StorageRepository, user_id: str, run_id: str, exc: Exception) -> None:
        repo.update_run_status(
            RunRef(user_id=user_id, run_id=run_id),
            status="failed",
            last_error=str(exc),
        )

    def run_music_analysis(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        audio = kwargs["audio"]
        try:
            import modal

            audio_ref = FileVersionRef(
                user_id=user_id,
                file_id=audio["file_id"],
                version_id=audio["version_id"],
            )
            audio_meta = repo.load_file_version_meta(audio_ref)
            analyze = modal.Function.from_name("eclypte-analysis", "analyze_remote")
            result = analyze.remote(
                repo.read_version_bytes(audio_ref),
                audio_meta.original_filename,
            )
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
            with _temporary_directory("eclypte_youtube_") as td:
                title, wav_path = _download_youtube_wav(url, Path(td))
                filename = f"{_safe_audio_basename(title)}.wav"
                wav_bytes = wav_path.read_bytes()

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
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_video_analysis(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        source_video = kwargs["source_video"]
        try:
            import modal

            source_ref = FileVersionRef(
                user_id=user_id,
                file_id=source_video["file_id"],
                version_id=source_video["version_id"],
            )
            source_meta = repo.load_file_version_meta(source_ref)
            analyze = modal.Function.from_name("eclypte-video-r2", "analyze_r2")
            result = analyze.remote(
                self._r2_config_payload(),
                source_meta.storage_key,
                source_meta.original_filename,
            )
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
            import json

            from api.prototyping.edit.synthesis.planner import plan

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
            timeline = plan(
                song=json.loads(repo.read_version_bytes(music_ref).decode("utf-8")),
                video=json.loads(repo.read_version_bytes(video_ref).decode("utf-8")),
                source_video_path=repo.load_file_version_meta(source_ref).original_filename,
                audio_path=repo.load_file_version_meta(audio_ref).original_filename,
                max_duration_sec=kwargs.get("max_duration_sec"),
            )
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
                created_by_step="plan_timeline",
                derived_from_step="plan_timeline",
                input_file_version_ids=[
                    audio_ref.version_id,
                    source_ref.version_id,
                    music_ref.version_id,
                    video_ref.version_id,
                ],
                derived_from_run_id=run_id,
            )
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs={
                    "timeline_file_id": file_ref.file_id,
                    "timeline_version_id": version.version_id,
                },
            )
        except Exception as exc:
            self._mark_failed(repo, user_id, run_id, exc)

    def run_render(self, **kwargs) -> None:
        repo = self._repository()
        user_id = kwargs["user_id"]
        run_id = kwargs["run_id"]
        timeline = kwargs["timeline"]
        audio = kwargs["audio"]
        source_video = kwargs["source_video"]
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
            output = render.remote(
                self._r2_config_payload(),
                timeline_meta.storage_key,
                source_meta.storage_key,
                audio_meta.storage_key,
                version_ref.blob_key,
                f"{run_id}.mp4",
            )
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


def _download_youtube_wav(url: str, workdir: Path) -> tuple[str, Path]:
    from imageio_ffmpeg import get_ffmpeg_exe
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    ydl_opts_base = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    cookiefile = _youtube_cookiefile(workdir)
    if cookiefile is not None:
        ydl_opts_base["cookiefile"] = str(cookiefile)
    try:
        info, downloaded = _download_youtube_media(url, ydl_opts_base, yt_dlp)
    except Exception as exc:
        if _is_youtube_cookie_auth_error(exc):
            raise RuntimeError(_youtube_auth_error_message(cookiefile is not None)) from exc
        raise

    wav_path = workdir / f"{_safe_audio_basename(info.get('id') or 'youtube_audio')}.wav"
    try:
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-i", str(downloaded), str(wav_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"failed to convert YouTube audio to WAV: {detail}") from exc
    return info.get("title") or "YouTube song", wav_path


def _download_youtube_media(url: str, ydl_opts_base: dict, yt_dlp) -> tuple[dict, Path]:
    last_format_error = None
    for extractor_args in YOUTUBE_EXTRACTOR_ARG_VARIANTS:
        for format_selector in YOUTUBE_FORMAT_SELECTORS:
            ydl_opts = dict(ydl_opts_base)
            if extractor_args:
                ydl_opts["extractor_args"] = extractor_args
            if format_selector:
                ydl_opts["format"] = format_selector
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info, _yt_dlp_downloaded_path(info, ydl)
            except Exception as exc:
                if _is_youtube_format_unavailable_error(exc):
                    last_format_error = exc
                    continue
                raise
    if last_format_error is not None:
        if "cookiefile" in ydl_opts_base:
            no_cookie_opts_base = dict(ydl_opts_base)
            no_cookie_opts_base.pop("cookiefile", None)
            for extractor_args in YOUTUBE_NO_COOKIE_EXTRACTOR_ARG_VARIANTS:
                for format_selector in YOUTUBE_FORMAT_SELECTORS:
                    ydl_opts = dict(no_cookie_opts_base)
                    ydl_opts["extractor_args"] = extractor_args
                    if format_selector:
                        ydl_opts["format"] = format_selector
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            return info, _yt_dlp_downloaded_path(info, ydl)
                    except Exception as exc:
                        if _is_youtube_format_unavailable_error(exc):
                            last_format_error = exc
                            continue
                        if _is_youtube_cookie_auth_error(exc):
                            continue
                        raise
        formats, probe_errors = _probe_youtube_formats(url, ydl_opts_base, yt_dlp)
        summary = _youtube_format_summary(formats)
        error_suffix = f" probe errors: {_youtube_error_summary(probe_errors)}" if probe_errors else ""
        raise RuntimeError(
            "Requested YouTube format is not available after trying fallback selectors. "
            f"yt-dlp visible formats: {summary}.{error_suffix}"
        ) from last_format_error
    raise RuntimeError("No YouTube format selectors configured")


def _probe_youtube_formats(url: str, ydl_opts_base: dict, yt_dlp) -> tuple[list[dict], list[str]]:
    errors = []
    for extractor_args in YOUTUBE_EXTRACTOR_ARG_VARIANTS:
        ydl_opts = dict(ydl_opts_base)
        ydl_opts["ignore_no_formats_error"] = True
        if extractor_args:
            ydl_opts["extractor_args"] = extractor_args
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats") or []
            if formats:
                return formats, errors
        except Exception as exc:
            errors.append(str(exc))
            continue
    return [], errors


def _youtube_format_summary(formats: list[dict], limit: int = 12) -> str:
    if not formats:
        return "none"
    parts = []
    for fmt in formats[:limit]:
        parts.append(
            "{id}:{ext}:a={audio}:v={video}:p={protocol}".format(
                id=fmt.get("format_id") or "?",
                ext=fmt.get("ext") or "?",
                audio=fmt.get("acodec") or "?",
                video=fmt.get("vcodec") or "?",
                protocol=fmt.get("protocol") or "?",
            )
        )
    if len(formats) > limit:
        parts.append(f"... +{len(formats) - limit} more")
    return ", ".join(parts)


def _youtube_error_summary(errors: list[str], limit: int = 4) -> str:
    if not errors:
        return "none"
    unique = []
    for error in errors:
        compact = re.sub(r"\s+", " ", error).strip()
        if compact and compact not in unique:
            unique.append(compact)
    parts = unique[:limit]
    if len(unique) > limit:
        parts.append(f"... +{len(unique) - limit} more")
    return " | ".join(parts)


def _yt_dlp_downloaded_path(info: dict, ydl) -> Path:
    for download in info.get("requested_downloads") or []:
        filepath = download.get("filepath")
        if filepath:
            return Path(filepath)
    filepath = info.get("filepath")
    if filepath:
        return Path(filepath)
    return Path(ydl.prepare_filename(info))


def _is_youtube_format_unavailable_error(exc: Exception) -> bool:
    return "requested format is not available" in str(exc).lower()


def _youtube_cookiefile(workdir: Path) -> Path | None:
    cookie_text = os.environ.get("ECLYPTE_YOUTUBE_COOKIES")
    encoded = os.environ.get("ECLYPTE_YOUTUBE_COOKIES_B64")
    if encoded:
        try:
            cookie_text = base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("ECLYPTE_YOUTUBE_COOKIES_B64 is not valid base64 text") from exc
    if not cookie_text:
        return None
    cookie_path = workdir / "youtube_cookies.txt"
    cookie_path.write_text(cookie_text, encoding="utf-8", newline="\n")
    return cookie_path


def _is_youtube_cookie_auth_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "sign in to confirm" in message
        or "not a bot" in message
        or "--cookies" in message
        or "cookies-from-browser" in message
    )


def _youtube_auth_error_message(has_cookiefile: bool) -> str:
    if has_cookiefile:
        return (
            "YouTube rejected the configured cookies. Refresh the YouTube cookies export, "
            "base64-encode it, and update ECLYPTE_YOUTUBE_COOKIES_B64 on the Railway API service."
        )
    return (
        "YouTube is requiring authenticated cookies for this download. Export YouTube cookies "
        "in Netscape cookies.txt format, base64-encode the file contents, and set "
        "ECLYPTE_YOUTUBE_COOKIES_B64 on the Railway API service."
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


def _safe_audio_basename(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    return (cleaned or "youtube_song")[:96]
