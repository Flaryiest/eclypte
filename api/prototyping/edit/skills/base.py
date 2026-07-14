from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class EmptyParams(BaseModel):
    """Params model for skills that take no parameters."""


@dataclass(frozen=True)
class ZoneStats:
    """Footage character of one candidate text band (0-1 normalized)."""

    luma: float    # mean brightness; letterbox bars read as 0
    detail: float  # edge/texture density; low = calm area where text sits well


@dataclass(frozen=True)
class ShotStats:
    """Sampled footage stats for one shot's timeline window (see
    render/footage_stats.py). ``zones`` follows lyrics_layout's candidate
    bands top→bottom."""

    start_sec: float
    end_sec: float
    zones: tuple[ZoneStats, ...]
    dominant_hue_deg: float  # 0-360
    saturation: float        # 0-1; near 0 = effectively monochrome footage


@dataclass(frozen=True)
class RenderContext:
    """Render-time context handed to a skill's ``build_layers``/``ffmpeg_filter``.

    ``asset_dir`` is the scratch dir where the executor materialized the
    skill's ``ffmpeg_assets`` files; ``fonts_dir`` is the resolved kinetic
    fonts dir (empty when unavailable); ``shot_stats`` carries the renderer's
    footage sampling pass (None when sampling failed or wasn't requested).
    All defaulted so existing constructor calls keep working."""

    output_size: tuple[int, int]
    fps: int
    font_path: str
    asset_dir: str = ""
    fonts_dir: str = ""
    shot_stats: tuple[ShotStats, ...] | None = None


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
    camera shake), ``lyrics`` (full-reel word-synced lyric text, selected via
    finish_edit's dedicated ``lyrics`` field). All kinds ride the timeline's
    ``overlays`` channel.

    A skill ported to the native ffmpeg renderer sets ``ffmpeg_supported=True``
    and implements ``ffmpeg_filter`` returning a label-free filter fragment
    (e.g. ``vignette=a=0.74:enable='between(t,0.000,6.000)'``) applied to the
    assembled video stream; timelines whose skills are all ffmpeg-supported
    stay on the fast native render path.

    A skill that needs a side file (e.g. an .ass subtitle document) implements
    ``ffmpeg_assets`` returning ``{filename: text}``. The render executor
    writes those files into a scratch dir before launching ffmpeg and passes
    the dir as ``ctx.asset_dir`` — content must be pure string building and
    must NOT depend on ``ctx.asset_dir`` (materialization order is not
    guaranteed); filenames must be namespaced by skill id. ``wants_shot_stats``
    asks the renderer to run its footage sampling pass; ``singleton`` skills
    may appear at most once per timeline (enforced by the validators).

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
    wants_shot_stats: bool = False
    singleton: bool = False

    def build_layers(self, overlay, ctx):  # pragma: no cover - overridden
        raise NotImplementedError

    def ffmpeg_filter(self, overlay, ctx) -> str:
        raise NotImplementedError

    def ffmpeg_assets(self, overlay, ctx) -> dict[str, str]:
        """Side files to materialize before ffmpeg runs ({filename: text})."""
        return {}
