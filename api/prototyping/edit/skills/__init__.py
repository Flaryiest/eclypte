"""Creative overlay skills (text, masks, ...) for the edit agent.

Importing this package registers every available skill into the default
registry, so consumers can call ``skills.ids()`` / ``skills.get(id)`` /
``skills.agent_catalog()`` and be sure registration has happened.
"""

from .registry import agent_catalog, default_registry, get, ids, register  # noqa: F401

# Importing each skill module runs its register(...) call. Add a skill = new
# module + one import line here; remove a skill = delete the module + its line.
from . import mask_vignette, text_caption, text_hook, text_lower_third, text_lyric  # noqa: E402,F401

__all__ = ["agent_catalog", "default_registry", "get", "ids", "register"]
