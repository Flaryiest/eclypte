import json
from pathlib import Path

import ytdownload
import lyrics
from analysis_modal import app, analyze_remote


def main():
    title = ytdownload.main(ytdownload.url)

    wav = Path("./content/output.wav")
    out = Path("./content/output.json")
    with app.run():
        result = analyze_remote.remote(wav.read_bytes(), wav.name)
    result["source"]["path"] = str(wav)
    out.write_text(json.dumps(result, indent=2))

    lyrics.main(title)


if __name__ == "__main__":
    main()
