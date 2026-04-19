import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from api.prototyping.edit.index.embed import embed_frames, embed_text

@patch('api.prototyping.edit.index.embed._HAS_TRANSFORMERS', True)
@patch('api.prototyping.edit.index.embed.CLIPProcessor', create=True)
@patch('api.prototyping.edit.index.embed.CLIPModel', create=True)
@patch('api.prototyping.edit.index.embed.torch', create=True)
@patch('api.prototyping.edit.index.embed.Image', create=True)
def test_embed_frames(mock_image, mock_torch, mock_model, mock_proc):
    dummy_frames = [np.zeros((224, 224, 3), dtype=np.uint8)]
    
    mock_model_instance = MagicMock()
    mock_model.from_pretrained.return_value.to.return_value = mock_model_instance
    
    mock_proc_instance = MagicMock()
    # When _processor(images=...) is called
    mock_proc_instance.return_value.to.return_value = MagicMock()
    mock_proc.from_pretrained.return_value = mock_proc_instance
    
    mock_features = MagicMock()
    mock_features.norm.return_value = 1.0
    mock_features.__truediv__.return_value.cpu.return_value.numpy.return_value = np.zeros((1, 768))
    mock_model_instance.get_image_features.return_value = mock_features
    
    vecs = embed_frames(dummy_frames)
    assert vecs.shape == (1, 768)

@patch('api.prototyping.edit.index.embed._HAS_TRANSFORMERS', True)
@patch('api.prototyping.edit.index.embed.CLIPProcessor', create=True)
@patch('api.prototyping.edit.index.embed.CLIPModel', create=True)
@patch('api.prototyping.edit.index.embed.torch', create=True)
def test_embed_text(mock_torch, mock_model, mock_proc):
    mock_model_instance = MagicMock()
    mock_model.from_pretrained.return_value.to.return_value = mock_model_instance
    
    mock_proc_instance = MagicMock()
    mock_proc_instance.return_value.to.return_value = MagicMock()
    mock_proc.from_pretrained.return_value = mock_proc_instance
    
    mock_features = MagicMock()
    mock_features.norm.return_value = 1.0
    mock_features.__truediv__.return_value.cpu.return_value.numpy.return_value = np.zeros((1, 768))
    mock_model_instance.get_text_features.return_value = mock_features
    
    vec = embed_text("dummy text")
    assert hasattr(vec, 'shape')
