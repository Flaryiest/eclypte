from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

TransitionType = Literal["cut", "crossfade", "whip", "flash"]
EffectType = Literal["freeze", "speed_ramp", "hold"]
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


class AudioSpec(BaseModel):
    path: str
    start_sec: float = 0.0
    gain_db: float = 0.0


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


class Timeline(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: SourceRef
    output: OutputSpec
    audio: AudioSpec
    shots: list[Shot]
    markers: Markers = Field(default_factory=Markers)
