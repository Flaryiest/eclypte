import modal
import numpy as np
from pathlib import Path

app = modal.App("eclypte-index")
volume = modal.Volume.from_name("eclypte-edit", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.5.0", "transformers", "opencv-python-headless", "numpy", "pillow")
    .add_local_python_source("frames")
    .add_local_python_source("embed")
)

@app.function(image=image, volumes={"/workdir": volume}, gpu="T4", timeout=1800)
def build_index(video_filename: str):
    """
    Extracts frames from a video, runs CLIP embedding, and saves to an npz index.
    The video is expected to be present in /workdir/.
    """
    from frames import extract_frames
    from embed import embed_frames
    
    video_path = f"/workdir/{video_filename}"
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video {video_path} not found in eclypte-edit volume.")
        
    print(f"Extracting frames from {video_filename}...")
    # frames is a list of (timestamp_sec, frame_bgr)
    frames_data = extract_frames(video_path, fps=1)
    
    if not frames_data:
        raise ValueError(f"No frames extracted from {video_filename}")
        
    timestamps = np.array([f[0] for f in frames_data], dtype=np.float32)
    bgr_arrays = [f[1] for f in frames_data]
    
    print(f"Embedding {len(bgr_arrays)} frames using CLIP ViT-L/14...")
    embeddings = embed_frames(bgr_arrays)
    
    # Save the index to /workdir/
    output_filename = Path(video_filename).with_suffix(".npz").name
    output_path = f"/workdir/{output_filename}"
    
    np.savez(output_path, timestamps=timestamps, embeddings=embeddings)
    print(f"Saved index to {output_path}")
    
    # Commit volume
    volume.commit()
    return output_path
