from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

TAIL_FADE_SEC = 2.5


def tail_fade_for(duration_sec: float) -> float:
    """End-of-reel audio+video fade length, clamped so it never exceeds a third
    of the reel (so very short edits still keep most of their content)."""
    if duration_sec <= 0:
        return 0.0
    return round(min(TAIL_FADE_SEC, duration_sec / 3.0), 3)

TransitionType = Literal["cut", "crossfade", "whip", "flash"]
EffectType = Literal["freeze", "speed_ramp", "hold", "punch_in"]
CropMode = Literal["letterbox", "center", "fill", "per_shot"]


class SourceRef(BaseModel):
    video: str
    audio: str


class OutputSpec(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration_sec: float
    crop: CropMode = "letterbox"
    crop_focus_x: float = Field(default=0.5, ge=0, le=1)
    fade_out_sec: float = 0.0


class AudioSpec(BaseModel):
    path: str
    start_sec: float = 0.0
    gain_db: float = 0.0
    fade_out_sec: float = 0.0


class ShotSource(BaseModel):
    start_sec: float
    end_sec: float


class Effect(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: EffectType
    pattern_ref: str | None = None


class Transition(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: TransitionType = "cut"
    duration_sec: float = 0.0
    pattern_ref: str | None = None


class Shot(BaseModel):
    index: int
    timeline_start_sec: float
    timeline_end_sec: float
    source: ShotSource
    speed: float = 1.0
    effects: list[Effect] = Field(default_factory=list)
    transition_in: Transition = Field(default_factory=Transition)
    pattern_refs: list[str] = Field(default_factory=list)

    @property
    def duration_sec(self) -> float:
        return self.timeline_end_sec - self.timeline_start_sec


class Markers(BaseModel):
    model_config = ConfigDict(extra="allow")
    beats_used_sec: list[float] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)


class Overlay(BaseModel):
    """A creative overlay (text/mask) composited over the reel.

    `skill_id` names a registered overlay skill; `params` is the validated
    parameter dict that skill expects. Optional + back-compat: an older
    renderer that doesn't know `overlays` simply ignores them.
    """

    skill_id: str
    timeline_start_sec: float
    timeline_end_sec: float
    params: dict[str, Any] = Field(default_factory=dict)


class Timeline(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: SourceRef
    output: OutputSpec
    audio: AudioSpec
    shots: list[Shot]
    markers: Markers = Field(default_factory=Markers)
    overlays: list[Overlay] = Field(default_factory=list)
