from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile

import modal

CLIP_INDEX_CONTENT_TYPE = "application/x-numpy-data"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install(
        "torch==2.5.0",
        "transformers",
        "opencv-python-headless",
        "numpy",
        "pillow",
        "boto3",
    )
    .add_local_python_source("edit", "modal_s3", "progress_events")
)

app = modal.App("eclypte-clip-index-r2")
storage_image = image

_INDEX_CACHE = {}


@app.function(image=storage_image, gpu="T4", timeout=1800)
def build_index_r2(
    r2_config: dict,
    source_key: str,
    filename: str,
    output_key: str,
    progress_context: dict | None = None,
) -> dict:
    from edit.index.embed import embed_frames
    from edit.index.frames import extract_frames
    from modal_s3 import download, s3_client
    from progress_events import emit_progress
    import numpy as np

    client = s3_client(r2_config)
    bucket = r2_config["bucket"]
    suffix = Path(filename).suffix or ".mp4"
    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        source_path = workdir / f"source{suffix}"
        index_path = workdir / "clip_index.npz"

        emit_progress(progress_context, 5, "Downloading source video")
        download(client, bucket, source_key, source_path)
        frames_data = extract_frames(source_path, fps=1)
        if not frames_data:
            raise ValueError(f"No frames extracted from {filename}")
        emit_progress(progress_context, 25, f"Extracted {len(frames_data)} frames")

        timestamps = np.array([frame[0] for frame in frames_data], dtype=np.float32)
        # Per-frame content signals so query-time can drop dead frames (black
        # intros/outros, end credits, solid title cards) from results.
        brightness = np.array([float(frame[1].mean()) for frame in frames_data], dtype=np.float32)
        detail = np.array([float(frame[1].std()) for frame in frames_data], dtype=np.float32)
        embeddings = embed_frames(
            [frame[1] for frame in frames_data],
            on_progress=lambda processed, total: emit_progress(
                progress_context,
                25 + int((processed / max(total, 1)) * 60),
                f"Embedded {processed}/{total} frames",
            ),
        )
        np.savez(
            index_path,
            timestamps=timestamps,
            embeddings=embeddings,
            brightness=brightness,
            detail=detail,
        )

        body = index_path.read_bytes()
        emit_progress(progress_context, 90, "Uploading CLIP index")
        client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=body,
            ContentType=CLIP_INDEX_CONTENT_TYPE,
        )
        emit_progress(progress_context, 100, "CLIP index ready")
        return {
            "storage_key": output_key,
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": CLIP_INDEX_CONTENT_TYPE,
        }


def _load_index_from_r2(r2_config: dict, index_key: str):
    from modal_s3 import download, s3_client
    import numpy as np

    cached = _INDEX_CACHE.get(index_key)
    if cached is not None:
        return cached

    client = s3_client(r2_config)
    with tempfile.TemporaryDirectory() as td:
        index_path = Path(td) / "clip_index.npz"
        download(client, r2_config["bucket"], index_key, index_path)
        with np.load(index_path) as data:
            timestamps = data["timestamps"]
            embeddings = data["embeddings"]
            # Older indexes (built before the content filter) lack these.
            brightness = data["brightness"] if "brightness" in data else None
            detail = data["detail"] if "detail" in data else None

    _INDEX_CACHE[index_key] = (timestamps, embeddings, brightness, detail)
    return timestamps, embeddings, brightness, detail


@app.function(image=storage_image, gpu="T4", scaledown_window=600)
def query_index_r2(
    r2_config: dict,
    index_key: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    from edit.index.embed import embed_text
    from edit.index.query import TEXT_NEGATIVE_PROMPTS, rank_with_content_filter
    import numpy as np

    timestamps, embeddings, brightness, detail = _load_index_from_r2(r2_config, index_key)
    query_embedding = embed_text(query)[0]
    similarities = np.dot(embeddings, query_embedding)
    # Per-frame max similarity to the title-card/credits prompts — computed
    # from the STORED frame embeddings, so this works on old indexes too.
    negative_embeddings = embed_text(list(TEXT_NEGATIVE_PROMPTS))
    text_negative_sims = np.dot(embeddings, negative_embeddings.T).max(axis=1)
    return rank_with_content_filter(
        timestamps, similarities, brightness, detail, top_k=top_k,
        text_negative_sims=text_negative_sims,
    )
