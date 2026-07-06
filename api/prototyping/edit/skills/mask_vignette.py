from __future__ import annotations

from pydantic import BaseModel, Field

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register


class VignetteParams(BaseModel):
    strength: float = Field(default=0.6, ge=0.0, le=1.0)


class MaskVignette(OverlaySkill):
    id = "mask.vignette"
    description = (
        "Darkens the frame edges (radial vignette) to focus attention on the "
        "center — no text. Optional param: strength (0-1, default 0.6)."
    )
    params_model = VignetteParams
    ffmpeg_supported = True

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        strength = self.params_model(**overlay.params).strength
        angle = 0.2 + 0.9 * strength  # radians; stronger strength = darker edges
        return (
            f"vignette=a={angle:.4f}:"
            f"enable='between(t,{overlay.timeline_start_sec:.3f},{overlay.timeline_end_sec:.3f})'"
        )

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        import numpy as np
        from moviepy import ImageClip

        strength = self.params_model(**overlay.params).strength
        width, height = ctx.output_size
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        dist = np.sqrt(((xs - cx) / cx) ** 2 + ((ys - cy) / cy) ** 2)
        dist = np.clip(dist / np.sqrt(2.0), 0.0, 1.0)
        # Ease so the center stays fully clear and darkening ramps toward edges.
        alpha = (dist ** 2) * strength
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., 3] = (alpha * 255).astype(np.uint8)
        clip = ImageClip(rgba)  # transparent=True (default) builds mask from alpha
        return [clip.with_start(overlay.timeline_start_sec).with_duration(overlay.duration_sec)]


register(MaskVignette())
