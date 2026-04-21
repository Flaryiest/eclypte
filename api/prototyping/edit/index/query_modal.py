from pathlib import Path

import modal
import numpy as np

app = modal.App("eclypte-query")
volume = modal.Volume.from_name("eclypte-edit", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.5.0", "transformers", "numpy", "pillow")
    .add_local_python_source("embed")
)

_INDEX_CACHE: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def _load_index(video_filename: str) -> tuple[np.ndarray, np.ndarray]:
    index_filename = Path(video_filename).with_suffix(".npz").name
    index_path = f"/workdir/{index_filename}"

    if not Path(index_path).exists():
        raise FileNotFoundError(
            f"Index {index_path} not found. Ensure build_index ran successfully."
        )

    cached = _INDEX_CACHE.get(index_path)
    if cached is not None:
        return cached

    with np.load(index_path) as data:
        timestamps = data["timestamps"]
        embeddings = data["embeddings"]
    _INDEX_CACHE[index_path] = (timestamps, embeddings)
    return timestamps, embeddings


def _top_k_results(
    timestamps: np.ndarray,
    similarities: np.ndarray,
    *,
    top_k: int,
) -> list[dict]:
    top_indices = np.argsort(similarities)[::-1][:top_k]
    return [
        {
            "timestamp": float(timestamps[idx]),
            "score": float(similarities[idx]),
        }
        for idx in top_indices
    ]


@app.function(image=image, volumes={"/workdir": volume}, gpu="T4", scaledown_window=600)
def query_index(query: str, video_filename: str, top_k: int = 5) -> list[dict]:
    """
    Load the video's CLIP index, embed one text query, and return the best
    matching timestamps.
    """
    from embed import embed_text

    timestamps, embeddings = _load_index(video_filename)
    query_emb = embed_text(query)[0]
    similarities = np.dot(embeddings, query_emb)
    return _top_k_results(timestamps, similarities, top_k=top_k)
