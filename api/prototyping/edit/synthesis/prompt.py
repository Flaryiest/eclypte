"""
Section-label → intent string mapping.

Used in Phase 1 by the planner to bucket segments into a motion-intensity
quartile target, and in Phase 3 by the synthesis agent as a text query for
CLIP retrieval.

allin1 labels observed in practice: intro, verse, chorus, bridge, outro,
instrumental. Unknown labels fall back to DEFAULT_INTENT.
"""

SECTION_INTENT: dict[str, str] = {
    "intro": "calm establishing shot, wide landscape, character portrait",
    "verse": "character closeup, walking, dialogue scene, medium shot",
    "chorus": "action, fight, dynamic movement, high energy",
    "bridge": "emotional closeup, rain, reflection, contrast",
    "outro": "final shot, slow motion, hero pose, wide",
    "instrumental": "wide action, cinematic establishing, dynamic",
}

DEFAULT_INTENT = "cinematic action shot"


SECTION_ENERGY_TARGET: dict[str, float] = {
    "intro": 0.25,
    "verse": 0.45,
    "chorus": 0.85,
    "bridge": 0.40,
    "outro": 0.30,
    "instrumental": 0.70,
}

DEFAULT_ENERGY_TARGET = 0.5


def intent_for(label: str) -> str:
    return SECTION_INTENT.get(label, DEFAULT_INTENT)


def energy_target_for(label: str) -> float:
    return SECTION_ENERGY_TARGET.get(label, DEFAULT_ENERGY_TARGET)
