import modal
import numpy as np
from pathlib import Path

app = modal.App("eclypte-query")
volume = modal.Volume.from_name("eclypte-edit", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.5.0", "transformers", "numpy", "pillow")
    .add_local_python_source("embed")
)

@app.function(image=image, volumes={"/workdir": volume}, gpu="T4")
def query_index(query: str, video_filename: str, top_k: int = 5) -> list[dict]:
    """
    Loads the npz index for the video, embeds the text query,
    computes cosine similarity, and returns the top_k matching timestamps.
    """
    from embed import embed_text
    
    index_filename = Path(video_filename).with_suffix(".npz").name
    index_path = f"/workdir/{index_filename}"
    
    if not Path(index_path).exists():
        raise FileNotFoundError(f"Index {index_path} not found. Ensure build_index ran successfully.")
        
    data = np.load(index_path)
    timestamps = data["timestamps"]
    embeddings = data["embeddings"]
    
    # Embed the text query
    query_emb = embed_text(query)[0] # shape (768,)
    
    # Compute cosine similarity
    # embeddings shape (N, 768), query_emb shape (768,)
    # both are normalized to length 1
    similarities = np.dot(embeddings, query_emb)
    
    # Get top_k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]
    
    results = []
    for idx in top_indices:
        results.append({
            "timestamp": float(timestamps[idx]),
            "score": float(similarities[idx])
        })
        
    return results
