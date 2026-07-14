"""Local-dev font downloader for the kinetic-lyrics catalog.

    python -m api.prototyping.edit.skills.fetch_fonts

Downloads every catalog font (stdlib only) into the gitignored local fonts
dir. The Modal render image fetches the same pinned URLs at build time, so
this is only needed to render locally.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from typing import Callable

from .lyrics_fonts import FONT_CATALOG, LOCAL_FONTS_DIR


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def fetch_fonts(
    dest_dir: str | Path,
    *,
    download: Callable[[str], bytes] = _download,
) -> list[str]:
    """Download missing catalog fonts into ``dest_dir``; returns written filenames."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for spec in FONT_CATALOG.values():
        target = dest / spec.filename
        if target.exists():
            continue
        target.write_bytes(download(spec.url))
        written.append(spec.filename)
    return written


def main() -> int:
    written = fetch_fonts(LOCAL_FONTS_DIR)
    skipped = len(FONT_CATALOG) - len(written)
    print(f"fonts dir: {LOCAL_FONTS_DIR}")
    print(f"downloaded {len(written)}, already present {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
