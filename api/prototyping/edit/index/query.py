"""
Clip-result ranking for the synthesis agent.

`rank_with_content_filter` ranks CLIP results and drops dead frames
(near-black / flat) so black intros, title cards, and credits are never
picked. It runs inside the `eclypte-clip-index-r2` Modal app
(index/storage_modal.py); the control plane reaches it through
`query_index_r2`, passed into the agent as `query_clips_fn`.
"""

# Content-filter thresholds (0-255 scale) for excluding dead frames from CLIP
# results: frames dimmer than MIN_BRIGHTNESS (black/dark credits) or flatter than
# MIN_DETAIL (solid colors, title cards) are never returned. Tuned to err toward
# filtering; lower MIN_BRIGHTNESS if legitimately dark/moody shots get dropped.
MIN_BRIGHTNESS = 30.0
MIN_DETAIL = 12.0

# Semantic text-frame filter: bright title cards and colored-background credits
# pass the brightness/detail gate, but CLIP itself recognizes on-screen text.
# Each frame's max similarity to these prompts is compared against its on-query
# similarity — a frame that reads more like a title/credits card than like the
# actual query is dropped. Works retroactively (frame embeddings are stored).
TEXT_NEGATIVE_PROMPTS = (
    "a movie title card with large text on screen",
    "opening credits with names on the screen",
    "end credits, a rolling list of names",
    "a studio logo on a plain background",
    "a screen filled with text",
)
# A frame is only "texty" above this absolute similarity — below it, the
# negative comparison is noise and must never drop anything.
TEXT_NEG_THRESHOLD = 0.24


def rank_with_content_filter(
    timestamps,
    similarities,
    brightness=None,
    detail=None,
    *,
    top_k: int = 5,
    min_brightness: float = MIN_BRIGHTNESS,
    min_detail: float = MIN_DETAIL,
    text_negative_sims=None,
) -> list[dict]:
    """Return the top_k ``{timestamp, score}`` matches, excluding dead frames.

    Near-black (low brightness) and flat/solid (low detail) frames are dropped so
    black intros/outros and dark credits can never be selected; frames that CLIP
    judges more similar to title-card/credits prompts than to the query
    (`text_negative_sims`, when provided) are dropped so BRIGHT text frames can't
    slip through either. When signals are absent (an older index / caller), the
    corresponding filter is skipped. If every frame is flagged (degenerate clip),
    falls back to the unfiltered ranking so a result is still returned.
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
    if text_negative_sims is not None:
        neg = np.asarray(text_negative_sims, dtype=np.float64)
        texty = (neg >= TEXT_NEG_THRESHOLD) & (neg > sims)
        live &= ~texty

    live_idx = np.nonzero(live)[0]
    if live_idx.size == 0:
        live_idx = np.arange(n)

    order = live_idx[np.argsort(sims[live_idx])[::-1][:top_k]]
    return [
        {"timestamp": float(timestamps[i]), "score": float(sims[i])}
        for i in order
    ]
