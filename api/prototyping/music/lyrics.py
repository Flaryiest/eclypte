import re
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


def main(query="Dominic Fike Babydoll Official Audio"):
    print("running lyrics.py")
    lrc = syncedlyrics.search(_clean_query(query))
    with open("./content/lyrics.txt", "w", encoding="utf-8") as f:
        f.write(lrc or "")
    return lrc

if __name__ == "__main__":
    main()