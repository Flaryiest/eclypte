"""Whole-reel color grade presets (kind="grade").

The agent picks at most one per reel via finish_edit's optional `grade` field;
the adapter turns it into a full-reel overlay so it rides the existing
overlays channel. Grades are ffmpeg-native (eq/colorbalance fragments): on the
MoviePy fallback path they no-op with a log — after the Phase 2 port that path
only runs for features with no native port, so this is effectively unreachable
for real reels.
"""
from __future__ import annotations

from .base import EmptyParams, OverlaySkill, RenderContext, ResolvedOverlay
from .registry import register


class _GradePreset(OverlaySkill):
    kind = "grade"
    params_model = EmptyParams
    ffmpeg_supported = True
    # eq/colorbalance chain WITHOUT the enable gate; the base class windows it.
    _chain: tuple[str, ...] = ()

    def ffmpeg_filter(self, overlay: ResolvedOverlay, ctx: RenderContext) -> str:
        window = f"enable='between(t,{overlay.timeline_start_sec:.3f},{overlay.timeline_end_sec:.3f})'"
        return ",".join(f"{f}:{window}" for f in self._chain)

    def build_layers(self, overlay: ResolvedOverlay, ctx: RenderContext) -> list:
        print(f"[skills] {self.id} is ffmpeg-only; skipped on the MoviePy path")
        return []


class GradeCinematic(_GradePreset):
    id = "grade.cinematic"
    description = (
        "Filmic grade: slightly lifted contrast, cool shadows, warm highlights. "
        "Fits dramatic or epic footage."
    )
    _chain = (
        "eq=contrast=1.05:saturation=1.08",
        "colorbalance=bs=0.06:rh=0.03:bh=-0.03",
    )


class GradeVibrant(_GradePreset):
    id = "grade.vibrant"
    description = (
        "Punchy grade: boosted saturation and a touch of brightness. Fits "
        "colorful, high-energy footage."
    )
    _chain = ("eq=contrast=1.04:saturation=1.22:brightness=0.01",)


class GradeMoody(_GradePreset):
    id = "grade.moody"
    description = (
        "Desaturated, darker grade with cool tones. Fits somber, tense, or "
        "melancholic footage."
    )
    _chain = (
        "eq=contrast=1.08:saturation=0.85:brightness=-0.02",
        "colorbalance=bs=0.05:bm=0.02",
    )


register(GradeCinematic())
register(GradeVibrant())
register(GradeMoody())
