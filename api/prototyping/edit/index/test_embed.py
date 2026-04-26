import numpy as np
from unittest.mock import patch, MagicMock
from api.prototyping.edit.index import embed as embed_module


class FakeTensor:
    def __init__(self, values):
        self._values = np.array(values, dtype=np.float32)

    def norm(self, p=2, dim=-1, keepdim=True):
        del p
        return FakeTensor(np.linalg.norm(self._values, axis=dim, keepdims=keepdim))

    def cpu(self):
        return self

    def numpy(self):
        return self._values

    def __truediv__(self, other):
        other_values = other._values if isinstance(other, FakeTensor) else other
        return FakeTensor(self._values / other_values)


class FakeModelOutput:
    def __init__(self, pooler_output):
        self.pooler_output = pooler_output


def _reset_embed_cache():
    embed_module._model = None
    embed_module._processor = None


@patch("api.prototyping.edit.index.embed._HAS_TRANSFORMERS", True)
@patch("api.prototyping.edit.index.embed.CLIPProcessor", create=True)
@patch("api.prototyping.edit.index.embed.CLIPModel", create=True)
@patch("api.prototyping.edit.index.embed.torch", create=True)
@patch("api.prototyping.edit.index.embed.Image", create=True)
def test_embed_frames_accepts_direct_tensor_like_features_when_torch_is_mocked(
    mock_image,
    mock_torch,
    mock_model,
    mock_proc,
):
    del mock_image
    _reset_embed_cache()

    dummy_frames = [np.zeros((224, 224, 3), dtype=np.uint8)]
    mock_model_instance = MagicMock()
    mock_model.from_pretrained.return_value.to.return_value = mock_model_instance

    mock_proc_instance = MagicMock()
    mock_proc_instance.return_value.to.return_value = {"pixel_values": "unused"}
    mock_proc.from_pretrained.return_value = mock_proc_instance
    mock_model_instance.get_image_features.return_value = FakeTensor(np.ones((1, 768)))

    vecs = embed_module.embed_frames(dummy_frames)

    assert vecs.shape == (1, 768)


@patch("api.prototyping.edit.index.embed._HAS_TRANSFORMERS", True)
@patch("api.prototyping.edit.index.embed.CLIPProcessor", create=True)
@patch("api.prototyping.edit.index.embed.CLIPModel", create=True)
@patch("api.prototyping.edit.index.embed.torch", create=True)
@patch("api.prototyping.edit.index.embed.Image", create=True)
def test_embed_frames_reports_batch_progress(
    mock_image,
    mock_torch,
    mock_model,
    mock_proc,
):
    del mock_image
    _reset_embed_cache()

    dummy_frames = [np.zeros((224, 224, 3), dtype=np.uint8) for _ in range(3)]
    mock_model_instance = MagicMock()
    mock_model.from_pretrained.return_value.to.return_value = mock_model_instance

    mock_proc_instance = MagicMock()
    mock_proc_instance.return_value.to.return_value = {"pixel_values": "unused"}
    mock_proc.from_pretrained.return_value = mock_proc_instance
    mock_model_instance.get_image_features.side_effect = [
        FakeTensor(np.ones((2, 768))),
        FakeTensor(np.ones((1, 768))),
    ]
    events = []

    vecs = embed_module.embed_frames(
        dummy_frames,
        batch_size=2,
        on_progress=lambda processed, total: events.append((processed, total)),
    )

    assert vecs.shape == (3, 768)
    assert events == [(2, 3), (3, 3)]


@patch("api.prototyping.edit.index.embed._HAS_TRANSFORMERS", True)
@patch("api.prototyping.edit.index.embed.CLIPProcessor", create=True)
@patch("api.prototyping.edit.index.embed.CLIPModel", create=True)
@patch("api.prototyping.edit.index.embed.torch", create=True)
def test_embed_text_unwraps_pooler_output_when_torch_is_mocked(
    mock_torch,
    mock_model,
    mock_proc,
):
    _reset_embed_cache()

    mock_model_instance = MagicMock()
    mock_model.from_pretrained.return_value.to.return_value = mock_model_instance

    mock_proc_instance = MagicMock()
    mock_proc_instance.return_value.to.return_value = {"input_ids": "unused"}
    mock_proc.from_pretrained.return_value = mock_proc_instance
    mock_model_instance.get_text_features.return_value = FakeModelOutput(
        FakeTensor(np.ones((1, 768)))
    )

    vec = embed_module.embed_text("dummy text")

    assert vec.shape == (1, 768)
