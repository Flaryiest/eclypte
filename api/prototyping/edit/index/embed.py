import numpy as np
from typing import List, Union

try:
    import torch
    from transformers import CLIPProcessor, CLIPModel
    from PIL import Image
    _HAS_TRANSFORMERS = True
except ImportError:
    _HAS_TRANSFORMERS = False

# We load the model lazily
_model = None
_processor = None
_device = "cuda" if _HAS_TRANSFORMERS and torch.cuda.is_available() else "cpu"


def _load_model():
    global _model, _processor
    if not _HAS_TRANSFORMERS:
        raise RuntimeError("transformers and torch are required for CLIP embedding.")
    if _model is None:
        model_id = "openai/clip-vit-large-patch14"
        _model = CLIPModel.from_pretrained(model_id).to(_device)
        _processor = CLIPProcessor.from_pretrained(model_id)


def _is_tensor_like(value) -> bool:
    return callable(getattr(value, "norm", None)) and callable(getattr(value, "cpu", None))


def _coerce_feature_tensor(value):
    if _is_tensor_like(value):
        return value

    pooler_output = getattr(value, "pooler_output", None)
    if _is_tensor_like(pooler_output):
        return pooler_output

    return value


def embed_frames(frames: List[np.ndarray], batch_size: int = 32) -> np.ndarray:
    """
    Embed a list of BGR numpy frames (from cv2) using CLIP ViT-L/14.
    Returns an array of shape (N, 768) for ViT-L/14.
    
    Processes frames in batches to avoid CUDA OOM on long videos.
    """
    _load_model()
    
    all_features = []
    total = len(frames)
    
    for i in range(0, total, batch_size):
        batch = frames[i:i + batch_size]
        
        # Convert BGR (cv2) to RGB (PIL)
        pil_images = [Image.fromarray(f[:, :, ::-1]) for f in batch]
        
        inputs = _processor(images=pil_images, return_tensors="pt", padding=True).to(_device)
        
        with torch.no_grad():
            image_features = _model.get_image_features(**inputs)

        image_features = _coerce_feature_tensor(image_features)

        image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
        all_features.append(image_features.cpu().numpy())
        
        print(f"  Embedded batch {i // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({min(i + batch_size, total)}/{total} frames)")
    
    return np.concatenate(all_features, axis=0)

def embed_text(text: Union[str, List[str]]) -> np.ndarray:
    """
    Embed text query/queries using CLIP ViT-L/14.
    Returns an array of shape (N, 768).
    """
    _load_model()
    
    if isinstance(text, str):
        text = [text]
        
    inputs = _processor(text=text, return_tensors="pt", padding=True, truncation=True).to(_device)
    
    with torch.no_grad():
        text_features = _model.get_text_features(**inputs)

    text_features = _coerce_feature_tensor(text_features)

    text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
    return text_features.cpu().numpy()
