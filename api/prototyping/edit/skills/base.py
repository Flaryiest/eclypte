from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class EmptyParams(BaseModel):
    """Params model for skills that take no parameters."""


@dataclass(frozen=True)
class RenderContext:
    """Render-time context handed to a skill's ``build_layers``."""

    output_size: tuple[int, int]
    fps: int
    font_path: str


class ResolvedOverlay(BaseModel):
    """A single overlay placement (skill + window + validated params)."""

    skill_id: str
    timeline_start_sec: float
    timeline_end_sec: float
    params: dict = {}

    @property
    def duration_sec(self) -> float:
        return self.timeline_end_sec - self.timeline_start_sec


class OverlaySkill:
    """Base class for a creative skill (text, mask, grade, moment accent, ...).

    A skill is one self-contained module: it declares its ``id``, ``kind``,
    agent-facing ``description`` and a ``params_model``, and implements
    ``build_layers`` to produce the moviepy layers composited over the reel.

    Kinds: ``overlay`` (windowed layer composited over the video), ``grade``
    (whole-reel color treatment), ``moment`` (short windowed accent such as a
    camera shake). All kinds ride the timeline's ``overlays`` channel.

    A skill ported to the native ffmpeg renderer sets ``ffmpeg_supported=True``
    and implements ``ffmpeg_filter`` returning a label-free filter fragment
    (e.g. ``vignette=a=0.74:enable='between(t,0.000,6.000)'``) applied to the
    assembled video stream; timelines whose skills are all ffmpeg-supported
    stay on the fast native render path.

    IMPORTANT: keep module-level imports moviepy-free. The control plane
    (adapter/validators/agent, which run on Railway without moviepy) imports
    skill *metadata*; only ``build_layers`` — which runs inside the Modal
    renderer — may touch moviepy, and it must import it lazily inside the body.
    ``ffmpeg_filter`` is pure string building and must stay dependency-free.
    """

    id: str = ""
    kind: str = "overlay"
    description: str = ""
    params_model: type[BaseModel] = EmptyParams
    ffmpeg_supported: bool = False

    def build_layers(self, overlay, ctx):  # pragma: no cover - overridden
        raise NotImplementedError

    def ffmpeg_filter(self, overlay, ctx) -> str:
        raise NotImplementedError
