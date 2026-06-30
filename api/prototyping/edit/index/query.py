"""
Clip retrieval for the synthesis agent.

- `query_clips`: CLIP semantic similarity via Modal.
- `rank_with_content_filter`: ranks CLIP results and drops dead frames
  (near-black / flat) so black intros, title cards, and credits are never picked.
"""
from types import SimpleNamespace

try:
    import modal
except ImportError:  # pragma: no cover - exercised only in lightweight test envs.
    modal = SimpleNamespace(
        Function=SimpleNamespace(from_name=None),
        exception=SimpleNamespace(NotFoundError=RuntimeError),
    )

_QUERY_FUNC = None

# Content-filter thresholds (0-255 scale) for excluding dead frames from CLIP
# results: frames dimmer than MIN_BRIGHTNESS (black/dark credits) or flatter than
# MIN_DETAIL (solid colors, title cards) are never returned. Tuned to err toward
# filtering; lower MIN_BRIGHTNESS if legitimately dark/moody shots get dropped.
MIN_BRIGHTNESS = 30.0
MIN_DETAIL = 12.0


def rank_with_content_filter(
    timestamps,
    similarities,
    brightness=None,
    detail=None,
    *,
    top_k: int = 5,
    min_brightness: float = MIN_BRIGHTNESS,
    min_detail: float = MIN_DETAIL,
) -> list[dict]:
    """Return the top_k ``{timestamp, score}`` matches, excluding dead frames.

    Near-black (low brightness) and flat/solid (low detail) frames are dropped so
    black intros/outros, title cards, and end credits can never be selected. When
    `brightness`/`detail` are absent (an older index built before the filter), no
    filtering is applied. If every frame is flagged (degenerate clip), falls back to
    the unfiltered ranking so a result is still returned.
    """
    import numpy as np

    sims = np.asarray(similarities, dtype=np.float64)
    n = int(sims.shape[0])
    if n == 0:
        return []

    live = np.ones(n, dtype=bool)
    if brightness is not None and detail is not None:
        brightness = np.asarray(brightness, dtype=np.float64)
        detail = np.asarray(detail, dtype=np.float64)
        live = (brightness >= min_brightness) & (detail >= min_detail)

    live_idx = np.nonzero(live)[0]
    if live_idx.size == 0:
        live_idx = np.arange(n)

    order = live_idx[np.argsort(sims[live_idx])[::-1][:top_k]]
    return [
        {"timestamp": float(timestamps[i]), "score": float(sims[i])}
        for i in order
    ]


def _lookup_query_func(function_name: str):
    if getattr(modal.Function, "from_name", None) is None:
        raise RuntimeError(
            "Modal is not installed in this environment. Install the `modal` package "
            "or run the query paths where it is available."
        )
    try:
        return modal.Function.from_name("eclypte-query", function_name)
    except modal.exception.NotFoundError as exc:
        raise RuntimeError(
            f"Could not find Modal function eclypte-query::{function_name}. "
            "Have you deployed it?"
        ) from exc


def query_clips(query: str, video_filename: str, top_k: int = 5) -> list[dict]:
    """
    Locally callable proxy to the Modal CLIP query endpoint.
    Retrieves the top K matching timestamps for the text query from the
    video's prebuilt CLIP index on the eclypte-edit volume.
    """
    global _QUERY_FUNC
    if _QUERY_FUNC is None:
        _QUERY_FUNC = _lookup_query_func("query_index")
    return _QUERY_FUNC.remote(query, video_filename, top_k)
