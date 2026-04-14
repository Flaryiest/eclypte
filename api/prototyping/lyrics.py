import syncedlyrics

def main(query="Dominic Fike Babydoll Official Audio"):
    print("running lyrics.py")
    lrc = syncedlyrics.search(query)
    with open("./content/lyrics.txt", "w", encoding="utf-8") as f:
        f.write(lrc or "")
    return lrc

if __name__ == "__main__":
    main()