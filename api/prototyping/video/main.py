import json
from pathlib import Path

from analysis import analyze


def main():
    here = Path(__file__).parent
    clip = here / "content" / "movie_clip.mp4"
    out = here / "content" / "movie_clip.json"
    analyze(str(clip), out_path=str(out))
    print(f"Wrote {out}")


def main_remote(filename="movie.mp4", gpu="T4"):
    from analysis_modal import app, VideoAnalyzer

    here = Path(__file__).parent
    out = here / "content" / f"{Path(filename).stem}.json"
    with app.run():
        result = VideoAnalyzer.with_options(gpu=gpu)().analyze.remote(filename)
    out.write_text(json.dumps(result, indent=2))
    scenes = len(result["scenes"])
    impacts = sum(len(s["impacts"]["impact_frames"]) for s in result["scenes"])
    print(f"Wrote {out}  ({scenes} scenes, {impacts} impacts, gpu={gpu})")


if __name__ == "__main__":
    main()
