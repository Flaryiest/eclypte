"""
Phase-1 CLI: plan a timeline from existing song + source analyses.

Run the audio and video analyses separately (Modal commands below), then:

    python -m api.prototyping.edit.main \\
        --song content/song.wav \\
        --source content/source.mp4

This writes `content/timeline.json`. Render on Modal:

    modal run api/prototyping/edit/render_modal.py \\
        --timeline content/timeline.json \\
        --out content/output.mp4

Required analyses (run first if their JSON isn't already on disk):

    modal run api/prototyping/music/analysis_modal.py::main --wav content/song.wav
    modal run api/prototyping/video/analysis_modal.py --filename source.mp4
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .synthesis.planner import plan
from .synthesis.timeline_schema import Timeline

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONTENT_DIR = PACKAGE_DIR / "content"
DEFAULT_TIMELINE_OUT = DEFAULT_CONTENT_DIR / "timeline.json"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    song_json = _resolve_analysis(args.song_analysis, args.song, ".json")
    video_json = _resolve_analysis(args.source_analysis, args.source, ".json")

    song = json.loads(Path(song_json).read_text(encoding="utf-8"))
    video = json.loads(Path(video_json).read_text(encoding="utf-8"))

    timeline = plan(
        song=song,
        video=video,
        source_video_path=str(args.source),
        audio_path=str(args.song),
        patterns_path=args.patterns,
        output_size=(args.width, args.height),
        output_fps=args.fps,
        max_duration_sec=args.max_duration,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(timeline.model_dump(mode="json"), indent=2))
    _report(timeline, out_path)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan an AMV timeline from analyses.")
    p.add_argument("--song", type=Path, required=True, help="path to song audio (wav)")
    p.add_argument("--source", type=Path, required=True, help="path to source video (mp4)")
    p.add_argument("--song-analysis", type=Path, default=None,
                   help="song_analysis.json (defaults to <song>.json)")
    p.add_argument("--source-analysis", type=Path, default=None,
                   help="source_analysis.json (defaults to <source>.json)")
    p.add_argument("--out", type=Path, default=DEFAULT_TIMELINE_OUT)
    p.add_argument("--patterns", type=Path, default=None,
                   help="override path to patterns.yaml")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--max-duration", type=float, default=None,
                   help="clip timeline to this length in seconds (optional)")
    return p.parse_args(argv)


def _resolve_analysis(explicit: Path | None, media: Path, suffix: str) -> Path:
    if explicit is not None:
        return explicit
    candidate = media.with_suffix(suffix)
    if not candidate.exists():
        raise FileNotFoundError(
            f"no analysis JSON found at {candidate}. Run the matching Modal "
            f"analysis command first, or pass --song-analysis / --source-analysis."
        )
    return candidate


def _report(tl: Timeline, path: Path) -> None:
    n_shots = len(tl.shots)
    dur = tl.output.duration_sec
    avg_shot = dur / n_shots if n_shots else 0.0
    print(f"wrote {path}  ({n_shots} shots, {dur:.2f}s, avg {avg_shot:.2f}s/shot)")
    print("next: cd api/prototyping && modal run edit/render_modal.py "
          f"--timeline {path} --out edit/content/output.mp4")


if __name__ == "__main__":
    raise SystemExit(main())
