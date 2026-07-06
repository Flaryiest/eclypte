"""Camera-shake moment accent (kind="moment").

A short jitter placed on a downbeat where a visual impact lands — either by
the agent (via the overlays channel) or automatically by the adapter's
rhythm engine (auto accents on the strongest impact registrations).

ffmpeg-native: a constant 16px pad border plus a crop whose x/y jitter only
inside the enable window (if/between expressions), so frame geometry is
identical outside the accent. MoviePy fallback no-ops with a log.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .base import OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register

PAD_PX = 16          # border added on each side; jitter stays inside it
BASE_AMP_PX = 4.0    # amplitude at intensity 0 (1080p reference height)
AMP_RANGE_PX = 10.0  # additional amplitude at intensity 1
SHAKE_FREQ_X = 73    # rad/s — fast, non-harmonic frequencies read as handheld
SHAKE_FREQ_Y = 61


class ShakeParams(BaseModel):
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


class ImpactShake(OverlaySkill):
    id = "impact.shake"
    kind = "moment"
    description = (
        "A ~0.4s camera shake accenting a hard hit. Place it exactly on a "
        "downbeat where the footage has a visual impact. Optional param: "
        "intensity (0-1, default 0.5)."
    )
    params_model = ShakeParams
    ffmpeg_supported = True

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        intensity = self.params_model(**overlay.params).intensity
        height = ctx.output_size[1]
        amp_x = (BASE_AMP_PX + AMP_RANGE_PX * intensity) * height / 1080.0
        amp_y = 0.8 * amp_x
        window = f"between(t,{overlay.timeline_start_sec:.3f},{overlay.timeline_end_sec:.3f})"
        return (
            f"pad=w=iw+{2 * PAD_PX}:h=ih+{2 * PAD_PX}:x={PAD_PX}:y={PAD_PX},"
            f"crop=w=iw-{2 * PAD_PX}:h=ih-{2 * PAD_PX}:"
            f"x='if({window},{PAD_PX}+{amp_x:.1f}*sin(t*{SHAKE_FREQ_X}),{PAD_PX})':"
            f"y='if({window},{PAD_PX}+{amp_y:.1f}*cos(t*{SHAKE_FREQ_Y}),{PAD_PX})'"
        )

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        print(f"[skills] {self.id} is ffmpeg-only; skipped on the MoviePy path")
        return []


register(ImpactShake())
