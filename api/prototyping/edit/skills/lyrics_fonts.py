"""Curated font catalog for kinetic lyrics.

Pure module (control plane imports it for the agent's font menu). Fonts are
NOT committed to the repo: the Modal render image downloads them at build
time and local dev fetches them with ``python -m api.prototyping.edit.skills.fetch_fonts``.

Every entry is a STATIC single-instance TTF (libass handling of variable
fonts is unreliable), pinned to one google/fonts commit SHA so image builds
are reproducible. ``family`` must match the TTF's internal family name
(name ID 1) exactly — libass matches by family and silently falls back to a
default font on mismatch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_GOOGLE_FONTS_SHA = "03781cf7a714af8431d14b6f337f923c774429d7"
_RAW_BASE = f"https://raw.githubusercontent.com/google/fonts/{_GOOGLE_FONTS_SHA}"

# Fonts-dir resolution order for the ass filter's `fontsdir` option.
ENV_FONTS_DIR = "ECLYPTE_LYRICS_FONTS_DIR"
MODAL_FONTS_DIR = "/fonts/kinetic"
LOCAL_FONTS_DIR = str(Path(__file__).resolve().parents[1] / "content" / "fonts")


@dataclass(frozen=True)
class FontSpec:
    font_id: str
    family: str    # TTF internal family name (name ID 1) — what ASS styles reference
    filename: str
    url: str
    vibe: str      # agent-facing description; taste guidance, not marketing copy
    license: str
    width_factor: float  # rough avg glyph width / font size, for line fitting
    all_caps: bool = False  # face draws lowercase input as caps-width glyphs
    spacing_frac: float = 0.0  # letter-spacing (tracking) as a fraction of font size


def _spec(
    font_id: str, family: str, repo_path: str, vibe: str, width_factor: float,
    all_caps: bool = False, spacing_frac: float = 0.0,
) -> FontSpec:
    return FontSpec(
        font_id=font_id,
        family=family,
        filename=repo_path.rsplit("/", 1)[-1],
        url=f"{_RAW_BASE}/{repo_path}",
        vibe=vibe,
        license="Apache-2.0" if repo_path.startswith("apache/") else "OFL-1.1",
        width_factor=width_factor,
        all_caps=all_caps,
        spacing_frac=spacing_frac,
    )


FONT_CATALOG: dict[str, FontSpec] = {
    spec.font_id: spec
    for spec in (
        _spec(
            "anton", "Anton", "ofl/anton/Anton-Regular.ttf",
            "heavy brutalist condensed sans — shouty and modern, the classic bold edit caption",
            0.42, spacing_frac=0.03,
        ),
        _spec(
            "bebas_neue", "Bebas Neue", "ofl/bebasneue/BebasNeue-Regular.ttf",
            "tall condensed all-caps sans — cinematic poster energy, clean and punchy",
            0.38, all_caps=True, spacing_frac=0.045,
        ),
        _spec(
            "archivo_black", "Archivo Black", "ofl/archivoblack/ArchivoBlack-Regular.ttf",
            "ultra-heavy grotesk block letters — loud streetwear weight, hits hard",
            0.60, spacing_frac=0.01,
        ),
        _spec(
            "poppins", "Poppins SemiBold", "ofl/poppins/Poppins-SemiBold.ttf",
            "clean geometric sans — friendly modern social-video default, safe on anything",
            0.55, spacing_frac=0.015,
        ),
        _spec(
            "dm_serif_display", "DM Serif Display", "ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf",
            "high-contrast editorial serif — elegant magazine headline, dramatic and classy",
            0.52,
        ),
        _spec(
            "italiana", "Italiana", "ofl/italiana/Italiana-Regular.ttf",
            "thin fashion-magazine serif — delicate, romantic, quiet luxury",
            0.45, spacing_frac=0.08,
        ),
        _spec(
            "marcellus", "Marcellus", "ofl/marcellus/Marcellus-Regular.ttf",
            "classical inscription serif — epic, mythic, movie-title gravitas",
            0.50, spacing_frac=0.03,
        ),
        _spec(
            "special_elite", "Special Elite", "apache/specialelite/SpecialElite-Regular.ttf",
            "worn typewriter — gritty, noir, documentary grunge",
            0.55,
        ),
        _spec(
            "permanent_marker", "Permanent Marker", "apache/permanentmarker/PermanentMarker-Regular.ttf",
            "thick handwritten marker — raw, personal, scrapbook energy",
            0.55,
        ),
        _spec(
            "righteous", "Righteous", "ofl/righteous/Righteous-Regular.ttf",
            "rounded retro-futuristic display — playful neon, synthwave nights",
            0.52, spacing_frac=0.02,
        ),
    )
}


def font_ids() -> set[str]:
    return set(FONT_CATALOG)


def get_font(font_id: str) -> FontSpec:
    return FONT_CATALOG[font_id]


def agent_font_menu() -> str:
    """One line per font for the agent's per-run context block."""
    return "\n".join(
        f"- {spec.font_id}: {spec.vibe}" for spec in FONT_CATALOG.values()
    )


def resolve_fonts_dir() -> str | None:
    """First existing fonts dir: env override, Modal image dir, local dev dir.

    None when nothing exists — the renderer logs and omits `fontsdir`, letting
    libass fall back to system fonts (wrong face, but the render survives)."""
    candidates = [os.environ.get(ENV_FONTS_DIR), MODAL_FONTS_DIR, LOCAL_FONTS_DIR]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return candidate
    return None
