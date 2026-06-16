import hashlib
import json
from pathlib import Path
import tempfile

import modal

RENDER_PROFILES = {
    "standard": {"cpu": 16, "memory": 16384, "threads": 16},
    "boosted": {"cpu": 24, "memory": 32768, "threads": 24},
}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("moviepy>=2", "pydantic>=2", "pyyaml", "numpy", "imageio-ffmpeg", "boto3")
    .add_local_python_source("edit", "modal_s3", "progress_events")
)

app = modal.App("eclypte-render-r2")
storage_image = image


def _patch_timeline_paths(timeline: dict, *, video_path: Path, audio_path: Path) -> dict:
    patched = dict(timeline)
    if "source" in patched:
        source = dict(patched["source"])
        source["video"] = str(video_path)
        source["audio"] = str(audio_path)
        patched["source"] = source
    if "audio" in patched:
        audio = dict(patched["audio"])
        audio["path"] = str(audio_path)
        patched["audio"] = audio
    return patched


@app.function(
    image=storage_image,
    cpu=RENDER_PROFILES["standard"]["cpu"],
    memory=RENDER_PROFILES["standard"]["memory"],
    timeout=86400,
)
def render_r2(
    r2_config: dict,
    timeline_key: str,
    source_video_key: str,
    audio_key: str,
    output_key: str,
    output_filename: str = "output.mp4",
    progress_context: dict | None = None,
    poster_output_key: str | None = None,
) -> dict:
    from edit.render.renderer import render_timeline
    from modal_s3 import download, s3_client
    from progress_events import emit_progress

    client = s3_client(r2_config)
    bucket = r2_config["bucket"]
    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        timeline_path = workdir / "timeline.json"
        source_path = workdir / "source.mp4"
        audio_path = workdir / "song.wav"
        output_path = workdir / Path(output_filename).name
        poster_path = workdir / "poster.jpg"

        emit_progress(progress_context, 5, "Downloading timeline")
        download(client, bucket, timeline_key, timeline_path)
        emit_progress(progress_context, 12, "Downloading source video")
        download(client, bucket, source_video_key, source_path)
        emit_progress(progress_context, 18, "Downloading audio")
        download(client, bucket, audio_key, audio_path)

        emit_progress(progress_context, 25, "Preparing timeline")
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline_path.write_text(
            json.dumps(
                _patch_timeline_paths(
                    timeline,
                    video_path=source_path,
                    audio_path=audio_path,
                )
            ),
            encoding="utf-8",
        )

        emit_progress(progress_context, 35, "Rendering video")
        render_timeline(
            timeline_path,
            output_path,
            preview=False,
            encode_preset="medium",
            threads=RENDER_PROFILES["standard"]["threads"],
            progress_callback=lambda percent, detail: emit_progress(
                progress_context,
                35 + int((percent / 100) * 50),
                detail,
            ),
            poster_path=poster_path if poster_output_key else None,
        )

        body = output_path.read_bytes()
        emit_progress(progress_context, 92, "Uploading rendered MP4")
        client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=body,
            ContentType="video/mp4",
        )

        result = {
            "storage_key": output_key,
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": "video/mp4",
        }
        if poster_output_key and poster_path.exists():
            poster_bytes = poster_path.read_bytes()
            client.put_object(
                Bucket=bucket,
                Key=poster_output_key,
                Body=poster_bytes,
                ContentType="image/jpeg",
            )
            result.update(
                {
                    "poster_storage_key": poster_output_key,
                    "poster_size_bytes": len(poster_bytes),
                    "poster_sha256": hashlib.sha256(poster_bytes).hexdigest(),
                    "poster_content_type": "image/jpeg",
                }
            )

        emit_progress(progress_context, 100, "Render uploaded")
        return result
