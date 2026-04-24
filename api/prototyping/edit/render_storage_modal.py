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
    .add_local_python_source("edit")
)

app = modal.App("eclypte-render-r2")
storage_image = image


def _s3_client(config: dict):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name=config.get("region_name", "auto"),
    )


def _download(client, bucket: str, key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        client.download_fileobj(bucket, key, f)


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
    timeout=3600,
)
def render_r2(
    r2_config: dict,
    timeline_key: str,
    source_video_key: str,
    audio_key: str,
    output_key: str,
    output_filename: str = "output.mp4",
) -> dict:
    from edit.render.renderer import render_timeline

    client = _s3_client(r2_config)
    bucket = r2_config["bucket"]
    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        timeline_path = workdir / "timeline.json"
        source_path = workdir / "source.mp4"
        audio_path = workdir / "song.wav"
        output_path = workdir / Path(output_filename).name

        _download(client, bucket, timeline_key, timeline_path)
        _download(client, bucket, source_video_key, source_path)
        _download(client, bucket, audio_key, audio_path)

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

        render_timeline(
            timeline_path,
            output_path,
            preview=False,
            encode_preset="medium",
            threads=RENDER_PROFILES["standard"]["threads"],
        )

        body = output_path.read_bytes()
        client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=body,
            ContentType="video/mp4",
        )
        return {
            "storage_key": output_key,
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": "video/mp4",
        }
