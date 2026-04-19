"""
Modal wrapper for the moviepy renderer.

MUST be invoked from api/prototyping/ so that add_local_python_source("edit")
picks up the edit/ package correctly:

    cd api/prototyping
    modal run edit/render_modal.py \\
        --timeline ./edit/content/timeline.json \\
        --out     ./edit/content/output.mp4

One-time source-file upload (only needed when source video or audio changes):

    modal volume put eclypte-edit edit/content/source.mp4
    modal volume put eclypte-edit edit/content/song.wav

The renderer reads source.mp4 and song.wav from the Volume at /workdir/
and writes output.mp4 back. The local entrypoint downloads output.mp4 to --out.
"""
from pathlib import Path
import json
import os
import tempfile

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("moviepy>=2", "pydantic>=2", "pyyaml", "numpy", "imageio-ffmpeg")
    .add_local_python_source("edit")
)

app = modal.App("eclypte-edit")
edit_volume = modal.Volume.from_name("eclypte-edit", create_if_missing=True)

WORKDIR = "/workdir"


@app.function(
    image=image,
    cpu=4,
    memory=4096,
    timeout=1800,
    volumes={WORKDIR: edit_volume},
)
def render_remote(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
) -> bytes:
    from edit.render.renderer import render_timeline

    with tempfile.TemporaryDirectory() as td:
        tl_path = os.path.join(td, "timeline.json")
        out_path = os.path.join(td, out_filename)

        tl = json.loads(timeline_bytes.decode())
        tl = _patch_paths(tl, WORKDIR)
        Path(tl_path).write_text(json.dumps(tl))

        render_timeline(tl_path, out_path, preview=preview)
        return Path(out_path).read_bytes()


@app.local_entrypoint()
def main(
    timeline: str = "./edit/content/timeline.json",
    out: str = "./edit/content/output.mp4",
    preview: bool = False,
):
    timeline_bytes = Path(timeline).read_bytes()
    print(f"rendering {timeline} → {out}  (preview={preview})")

    output_bytes = render_remote.remote(
        timeline_bytes,
        Path(out).name,
        preview=preview,
    )

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(output_bytes)
    size_mb = len(output_bytes) / 1_048_576
    print(f"wrote {out}  ({size_mb:.1f} MB)")


def _patch_paths(tl: dict, workdir: str) -> dict:
    """Remap bare filenames to /workdir/<basename> so the container finds them."""
    from pathlib import PureWindowsPath

    def _name(p: str) -> str:
        # PureWindowsPath handles backslash separators correctly on Linux too.
        return PureWindowsPath(p).name

    tl = dict(tl)
    if "source" in tl:
        src = dict(tl["source"])
        src["video"] = f"{workdir}/{_name(src['video'])}"
        src["audio"] = f"{workdir}/{_name(src['audio'])}"
        tl["source"] = src
    if "audio" in tl:
        aud = dict(tl["audio"])
        aud["path"] = f"{workdir}/{_name(aud['path'])}"
        tl["audio"] = aud
    return tl
