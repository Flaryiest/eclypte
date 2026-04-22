from contextlib import contextmanager
from pathlib import Path
import re
import os
import syncedlyrics


def _clean_query(q: str) -> str:
    # Strip quotes/brackets and common YouTube title decorations so
    # syncedlyrics doesn't treat them as search operators.
    q = re.sub(r'[\"\'()\[\]]', ' ', q)
    q = re.sub(
        r'\b(official\s+(music\s+)?(audio|video|lyric\s+video|visualizer)|lyrics|audio|hd|4k)\b',
        ' ', q, flags=re.I,
    )
    return re.sub(r'\s+', ' ', q).strip()


def _lyrics_path() -> Path:
    return Path("./content/lyrics.txt")


@contextmanager
def _local_syncedlyrics_cache():
    if os.name != "nt":
        yield
        return

    cache_root = Path("./content/.cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    previous_localappdata = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(cache_root)
    try:
        yield
    finally:
        if previous_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = previous_localappdata


def main(query="Dominic Fike Babydoll Official Audio"):
    print("running lyrics.py")
    with _local_syncedlyrics_cache():
        lrc = syncedlyrics.search(_clean_query(query))

    lyrics_path = _lyrics_path()
    lyrics_path.parent.mkdir(parents=True, exist_ok=True)
    with lyrics_path.open("w", encoding="utf-8") as f:
        f.write(lrc or "")
    return lrc

if __name__ == "__main__":
    main()
