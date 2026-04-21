"""
Edit-pipeline CLI: plan a timeline from existing song + source analyses.

Two planning paths share this CLI:

- **Phase 1 (default)** — deterministic planner, beat-aligned, motion-stat clip
  retrieval. No LLM, no embeddings:

        python -m api.prototyping.edit.main \\
            --song content/song.wav \\
            --source content/source.mp4

- **Phase 3 (`--agent`)** — GPT-4o synthesis loop + CLIP retrieval. Requires the
  CLIP index to already be built on the `eclypte-edit` Modal volume
  (`modal run edit/index/index_modal.py --video-filename source.mp4`) and the
  `OPENAI_API_KEY` env var to be set:

        python -m api.prototyping.edit.main \\
            --song content/song.wav \\
            --source content/source.mp4 \\
            --agent \\
            --instructions "fast-paced action AMV, cut on every downbeat in choruses"

Both paths write `content/timeline.json`. Render on Modal:

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
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from .synthesis.timeline_schema import Timeline

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONTENT_DIR = PACKAGE_DIR / "content"
DEFAULT_TIMELINE_OUT = DEFAULT_CONTENT_DIR / "timeline.json"
DEFAULT_ANNOTATIONS_PATH = PACKAGE_DIR / "knowledge" / "references.md"
RENDER_PROFILE_THREADS = {
    "standard": 16,
    "boosted": 24,
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    song_json = _resolve_analysis(args.song_analysis, args.song, ".json")
    video_json = _resolve_analysis(args.source_analysis, args.source, ".json")

    song = json.loads(Path(song_json).read_text(encoding="utf-8"))
    video = json.loads(Path(video_json).read_text(encoding="utf-8"))

    if args.agent:
        timeline = _run_agent(args, song, video)
    else:
        timeline = _run_planner(args, song, video)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(timeline.model_dump(mode="json"), indent=2))
    _report(timeline, out_path)

    if args.render:
        _render(
            out_path,
            Path(args.render_out),
            store_only=args.render_store_only,
            render_profile=args.render_profile,
            render_stage_inputs_local=args.render_stage_inputs_local,
            encode_preset=args.render_preset,
            threads=args.render_threads,
        )
    return 0


def _render(
    timeline_path: Path,
    video_out: Path,
    *,
    store_only: bool = False,
    render_profile: str = "standard",
    render_stage_inputs_local: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
) -> None:
    """Invoke `modal run edit/render_modal.py` from api/prototyping/."""
    prototyping_dir = Path(__file__).resolve().parent.parent
    timeline_abs = timeline_path.resolve()
    video_out_abs = video_out.resolve()
    video_out_abs.parent.mkdir(parents=True, exist_ok=True)
    resolved_threads = _resolve_render_threads(render_profile, threads)

    cmd = [
        "modal", "run", "edit/render_modal.py",
        "--timeline", str(timeline_abs),
        "--out", str(video_out_abs),
        "--render-profile", render_profile,
        "--encode-preset", encode_preset,
        "--threads", str(resolved_threads),
    ]
    if store_only:
        cmd.append("--store-only")
    if render_stage_inputs_local:
        cmd.append("--render-stage-inputs-local")

    print(
        f"rendering via Modal: {timeline_abs} -> {video_out_abs} "
        f"(store_only={store_only}, profile={render_profile}, "
        f"stage_inputs_local={render_stage_inputs_local}, preset={encode_preset}, "
        f"threads={resolved_threads})"
    )
    subprocess.run(cmd, cwd=str(prototyping_dir), check=True)
    if store_only:
        print(f"rendered remotely to volume as {video_out_abs.name}")
    else:
        print(f"wrote {video_out_abs}")


def _resolve_render_threads(render_profile: str, threads: int | None) -> int:
    try:
        default_threads = RENDER_PROFILE_THREADS[render_profile]
    except KeyError as exc:
        choices = ", ".join(sorted(RENDER_PROFILE_THREADS))
        raise ValueError(f"unknown render profile {render_profile!r}; expected one of: {choices}") from exc
    return default_threads if threads is None else threads


def _run_planner(args: argparse.Namespace, song: dict, video: dict) -> Timeline:
    from .patterns import registry
    from .reference.annotations import parse_annotations
    from .synthesis.planner import plan

    patterns = None
    patterns_path = args.patterns
    if args.use_annotations:
        patterns = registry.load(args.patterns)
        multipliers = parse_annotations(
            args.annotations_path,
            known_pattern_ids=registry.ids(patterns),
        )
        if multipliers:
            patterns = [
                p.model_copy(update={"weight": p.weight * multipliers[p.id]})
                if p.id in multipliers else p
                for p in patterns
            ]
            print(f"applied {len(multipliers)} annotation multipliers "
                  f"from {args.annotations_path}")
        else:
            print(f"no annotations found at {args.annotations_path} (weights unchanged)")
        patterns_path = None

    return plan(
        song=song,
        video=video,
        source_video_path=str(args.source),
        audio_path=str(args.song),
        patterns=patterns,
        patterns_path=patterns_path,
        output_size=(args.width, args.height),
        output_fps=args.fps,
        max_duration_sec=args.max_duration,
    )


def _run_agent(args: argparse.Namespace, song: dict, video: dict) -> Timeline:
    from .synthesis.adapter import adapt
    from .synthesis.agent import run_synthesis_loop

    if args.use_annotations:
        print("warning: --use-annotations has no effect with --agent (patterns not used)")
    if args.max_duration is not None:
        print("warning: --max-duration has no effect with --agent")

    print(f"running synthesis agent on {args.source.name}...")
    agent_output = run_synthesis_loop(
        video_filename=args.source.name,
        instructions=args.instructions,
        song=song,
    )
    print(f"agent produced {len(agent_output)} shots; adapting to timeline...")

    return adapt(
        agent_output=agent_output,
        song=song,
        video=video,
        source_video_path=str(args.source),
        audio_path=str(args.song),
        output_size=(args.width, args.height),
        output_fps=args.fps,
    )


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
    p.add_argument("--use-annotations", action="store_true",
                   help="apply weight multipliers from references.md "
                        "(Phase-2 Weighted Annotations section)")
    p.add_argument("--annotations-path", type=Path, default=DEFAULT_ANNOTATIONS_PATH,
                   help="path to references.md (default: knowledge/references.md)")
    p.add_argument("--agent", action="store_true",
                   help="use the Phase-3 GPT-4o synthesis agent instead of the "
                        "deterministic planner (requires OPENAI_API_KEY and a "
                        "prebuilt CLIP index on the eclypte-edit Modal volume)")
    p.add_argument("--instructions", type=str, default=None,
                   help="English AMV brief for the synthesis agent "
                        "(required with --agent)")
    p.add_argument("--render", action="store_true",
                   help="after writing the timeline, invoke modal run to "
                        "render it (requires Modal CLI on PATH)")
    p.add_argument("--render-out", type=Path,
                   default=DEFAULT_CONTENT_DIR / "output.mp4",
                   help="rendered MP4 path when --render is set")
    p.add_argument("--render-store-only", action="store_true",
                   help="render into the Modal volume only; skip returning the MP4 bytes locally")
    p.add_argument("--render-profile", choices=sorted(RENDER_PROFILE_THREADS), default="standard",
                   help="Modal capacity profile for render workloads")
    p.add_argument("--render-stage-inputs-local", action="store_true",
                   help="stage source media from the Modal volume into container-local temp storage before rendering")
    p.add_argument("--render-preset", default="medium",
                   help="ffmpeg/x264 preset passed through to the Modal renderer (e.g. ultrafast, veryfast, medium)")
    p.add_argument("--render-threads", type=int, default=None,
                   help="thread count passed through to the Modal renderer (defaults vary by --render-profile)")
    args = p.parse_args(argv)
    if args.agent and not args.instructions:
        p.error("--agent requires --instructions")
    return args


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
