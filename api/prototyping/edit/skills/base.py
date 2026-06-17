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
    """Base class for a creative overlay capability (text, mask, ...).

    A skill is one self-contained module: it declares its ``id``,
    agent-facing ``description`` and a ``params_model``, and implements
    ``build_layers`` to produce the moviepy layers composited over the reel.

    IMPORTANT: keep module-level imports moviepy-free. The control plane
    (adapter/validators/agent, which run on Railway without moviepy) imports
    skill *metadata*; only ``build_layers`` — which runs inside the Modal
    renderer — may touch moviepy, and it must import it lazily inside the body.
    """

    id: str = ""
    description: str = ""
    params_model: type[BaseModel] = EmptyParams

    def build_layers(self, overlay, ctx):  # pragma: no cover - overridden
        raise NotImplementedError
