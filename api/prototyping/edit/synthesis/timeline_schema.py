from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

TAIL_FADE_SEC = 2.5
# Reels at or under this length hard-end: a visible fade-to-black reads as
# "it's over" mid-scroll and costs replays (which count as views). Matches the
# agent's SHORT_EDIT_MAX_SEC threshold.
SHORT_REEL_MAX_SEC = 40.0
SHORT_REEL_AUDIO_FADE_SEC = 0.3

# speed_ramp contract shared by the adapter (source-window sizing) and both
# renderers (re-timing): 1x first half, SPEED_RAMP_END x second half, so a
# ramped shot consumes SPEED_RAMP_SOURCE_FACTOR x its duration of source.
SPEED_RAMP_END = 1.5
SPEED_RAMP_SOURCE_FACTOR = 0.5 + 0.5 * SPEED_RAMP_END


def tail_fades_for(duration_sec: float) -> tuple[float, float]:
    """(audio_fade_sec, video_fade_sec) for the end of the reel.

    Short reels get a click-prevention audio fade only — the picture hard-ends
    on the final shot. Long form keeps the classic audio+video tail fade,
    clamped to a third of the piece.
    """
    if duration_sec <= 0:
        return 0.0, 0.0
    if duration_sec <= SHORT_REEL_MAX_SEC:
        return SHORT_REEL_AUDIO_FADE_SEC, 0.0
    fade = round(min(TAIL_FADE_SEC, duration_sec / 3.0), 3)
    return fade, fade

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
    fade_out_sec: float = Field(default=0.0, ge=0)


class AudioSpec(BaseModel):
    path: str
    start_sec: float = 0.0
    gain_db: float = 0.0
    fade_out_sec: float = Field(default=0.0, ge=0)


class ShotSource(BaseModel):
    start_sec: float
    end_sec: float


class Effect(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: EffectType


class Transition(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: TransitionType = "cut"
    duration_sec: float = 0.0


class Shot(BaseModel):
    index: int
    timeline_start_sec: float
    timeline_end_sec: float
    source: ShotSource
    speed: float = 1.0
    effects: list[Effect] = Field(default_factory=list)
    transition_in: Transition = Field(default_factory=Transition)

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
