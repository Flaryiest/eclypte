from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Layer = Literal["micro", "transition", "shot_move", "meso", "macro"]
EmitKind = Literal["cut", "transition", "effect", "section_plan", "story_beat"]
ParamType = Literal["int", "float", "enum", "ratio"]


class AppliesWhen(BaseModel):
    section_labels: list[str] = Field(default_factory=list)
    min_energy: float = 0.0
    tempo_range_bpm: tuple[float, float] = (0.0, 999.0)
    motion_intensity: tuple[float, float] = (0.0, 1.0)
    camera_movements: list[str] = Field(default_factory=list)


class ParamSpec(BaseModel):
    type: ParamType
    default: Any
    range: list[Any] | None = None


class ComposesWith(BaseModel):
    requires: list[str] = Field(default_factory=list)
    forbids: list[str] = Field(default_factory=list)


class Emits(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: EmitKind


class Pattern(BaseModel):
    id: str
    layer: Layer
    name: str
    description: str = ""
    applies_when: AppliesWhen = Field(default_factory=AppliesWhen)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    weight: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)
    composes_with: ComposesWith = Field(default_factory=ComposesWith)
    emits: Emits
