from __future__ import annotations

from .base import OverlaySkill


class Registry:
    """Holds the set of available overlay skills.

    The agent's tool schema, timeline validation, and the renderer's dispatch
    all read from a registry, so adding/removing a capability is a single
    module plus one ``register`` call — nothing else hardcodes the skill list.
    """

    def __init__(self) -> None:
        self._skills: dict[str, OverlaySkill] = {}

    def register(self, skill: OverlaySkill) -> None:
        if skill.id in self._skills:
            raise ValueError(f"duplicate skill id {skill.id!r}")
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> OverlaySkill:
        return self._skills[skill_id]

    def ids(self) -> set[str]:
        return set(self._skills)

    def agent_catalog(self) -> list[dict]:
        return [
            {"id": s.id, "description": s.description}
            for s in self._skills.values()
        ]


# Process-wide default registry. Skill modules register into this on import;
# importing the ``skills`` package guarantees registration has run.
default_registry = Registry()


def register(skill: OverlaySkill) -> None:
    default_registry.register(skill)


def get(skill_id: str) -> OverlaySkill:
    return default_registry.get(skill_id)


def ids() -> set[str]:
    return default_registry.ids()


def agent_catalog() -> list[dict]:
    return default_registry.agent_catalog()
