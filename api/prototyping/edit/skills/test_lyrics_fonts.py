import re

import pytest

from api.prototyping.edit.skills import lyrics_fonts

_RAW_URL_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/google/fonts/([0-9a-f]{40})/(ofl|apache)/[a-z0-9]+/[A-Za-z0-9-]+\.ttf$"
)


def test_catalog_has_a_real_spread_of_fonts():
    assert len(lyrics_fonts.FONT_CATALOG) >= 8


def test_catalog_keys_match_spec_ids_and_are_snake_case():
    for font_id, spec in lyrics_fonts.FONT_CATALOG.items():
        assert font_id == spec.font_id
        assert re.fullmatch(r"[a-z][a-z0-9_]*", font_id), font_id


def test_filenames_are_unique_ttf_without_spaces():
    filenames = [s.filename for s in lyrics_fonts.FONT_CATALOG.values()]
    assert len(set(filenames)) == len(filenames)
    for name in filenames:
        assert name.endswith(".ttf")
        assert " " not in name


def test_families_are_unique_and_nonempty():
    # ASS styles reference fonts by family name; duplicates would be ambiguous.
    families = [s.family for s in lyrics_fonts.FONT_CATALOG.values()]
    assert all(f.strip() for f in families)
    assert len(set(families)) == len(families)


def test_urls_are_sha_pinned_to_one_google_fonts_commit():
    shas = set()
    for spec in lyrics_fonts.FONT_CATALOG.values():
        match = _RAW_URL_RE.match(spec.url)
        assert match, f"unpinned or malformed url: {spec.url}"
        shas.add(match.group(1))
        assert spec.url.endswith("/" + spec.filename)
    # One pin for the whole catalog — a single reproducible snapshot.
    assert len(shas) == 1


def test_license_matches_repo_directory():
    for spec in lyrics_fonts.FONT_CATALOG.values():
        if "/ofl/" in spec.url:
            assert spec.license == "OFL-1.1"
        else:
            assert spec.license == "Apache-2.0"


def test_vibes_are_descriptive():
    for spec in lyrics_fonts.FONT_CATALOG.values():
        assert len(spec.vibe) > 15, spec.font_id


def test_font_ids_and_get_font():
    ids = lyrics_fonts.font_ids()
    assert "anton" in ids
    assert lyrics_fonts.get_font("anton").family == "Anton"
    with pytest.raises(KeyError):
        lyrics_fonts.get_font("comic_sans")


def test_agent_font_menu_lists_every_font_with_its_vibe():
    menu = lyrics_fonts.agent_font_menu()
    for spec in lyrics_fonts.FONT_CATALOG.values():
        assert spec.font_id in menu
        assert spec.vibe in menu


def test_resolve_fonts_dir_prefers_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ECLYPTE_LYRICS_FONTS_DIR", str(tmp_path))
    assert lyrics_fonts.resolve_fonts_dir() == str(tmp_path)


def test_resolve_fonts_dir_skips_missing_env_dir_and_falls_back(tmp_path, monkeypatch):
    local = tmp_path / "fonts"
    local.mkdir()
    monkeypatch.setenv("ECLYPTE_LYRICS_FONTS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(lyrics_fonts, "MODAL_FONTS_DIR", str(tmp_path / "also-nope"))
    monkeypatch.setattr(lyrics_fonts, "LOCAL_FONTS_DIR", str(local))
    assert lyrics_fonts.resolve_fonts_dir() == str(local)


def test_resolve_fonts_dir_returns_none_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("ECLYPTE_LYRICS_FONTS_DIR", raising=False)
    monkeypatch.setattr(lyrics_fonts, "MODAL_FONTS_DIR", str(tmp_path / "a"))
    monkeypatch.setattr(lyrics_fonts, "LOCAL_FONTS_DIR", str(tmp_path / "b"))
    assert lyrics_fonts.resolve_fonts_dir() is None


def test_fetch_fonts_downloads_catalog_and_skips_existing(tmp_path):
    from api.prototyping.edit.skills import fetch_fonts

    calls: list[str] = []

    def fake_download(url: str) -> bytes:
        calls.append(url)
        return b"\x00\x01fontbytes"

    written = fetch_fonts.fetch_fonts(tmp_path, download=fake_download)
    assert len(written) == len(lyrics_fonts.FONT_CATALOG)
    for spec in lyrics_fonts.FONT_CATALOG.values():
        assert (tmp_path / spec.filename).read_bytes() == b"\x00\x01fontbytes"

    # Second run: everything exists, nothing re-downloaded.
    calls.clear()
    written = fetch_fonts.fetch_fonts(tmp_path, download=fake_download)
    assert written == []
    assert calls == []


def test_all_caps_flag_marks_caps_only_faces():
    # Bebas Neue draws lowercase input as caps glyphs; width estimates must know.
    assert lyrics_fonts.get_font("bebas_neue").all_caps is True
    assert lyrics_fonts.get_font("poppins").all_caps is False
