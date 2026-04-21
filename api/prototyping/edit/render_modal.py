"""
Modal wrapper for the moviepy renderer.

MUST be invoked from api/prototyping/ so that add_local_python_source("edit")
picks up the edit/ package correctly:

    cd api/prototyping
    modal run edit/render_modal.py \
        --timeline ./edit/content/timeline.json \
        --out     ./edit/content/output.mp4

One-time source-file upload (only needed when source video or audio changes):

    modal volume put eclypte-edit edit/content/source.mp4
    modal volume put eclypte-edit edit/content/song.wav

The renderer reads source.mp4 and song.wav from the Volume at /workdir/.
For fastest runs, use `--store-only` so the encoded MP4 stays on the Modal
volume instead of being returned as RPC bytes.
"""
import json
import os
import tempfile
from pathlib import Path

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


def _render_impl(
    timeline_bytes: bytes,
    out_path: str,
    *,
    preview: bool,
    encode_preset: str,
    threads: int | None,
) -> Path:
    from edit.render.renderer import render_timeline

    with tempfile.TemporaryDirectory() as td:
        tl_path = os.path.join(td, "timeline.json")
        tl = json.loads(timeline_bytes.decode())
        tl = _patch_paths(tl, WORKDIR)
        Path(tl_path).write_text(json.dumps(tl), encoding="utf-8")
        render_timeline(
            tl_path,
            out_path,
            preview=preview,
            encode_preset=encode_preset,
            threads=threads,
        )
    return Path(out_path)


@app.function(
    image=image,
    cpu=16,
    memory=16384,
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int = 16,
) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, Path(out_filename).name)
        rendered = _render_impl(
            timeline_bytes,
            out_path,
            preview=preview,
            encode_preset=encode_preset,
            threads=threads,
        )
        return rendered.read_bytes()


@app.function(
    image=image,
    cpu=16,
    memory=16384,
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote_to_volume(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int = 16,
) -> dict:
    remote_out = os.path.join(WORKDIR, Path(out_filename).name)
    rendered = _render_impl(
        timeline_bytes,
        remote_out,
        preview=preview,
        encode_preset=encode_preset,
        threads=threads,
    )
    edit_volume.commit()
    return {
        "remote_path": remote_out,
        "size_bytes": rendered.stat().st_size,
        "preview": preview,
        "encode_preset": encode_preset,
        "threads": threads,
    }


@app.local_entrypoint()
def main(
    timeline: str = "./edit/content/timeline.json",
    out: str = "./edit/content/output.mp4",
    preview: bool = False,
    store_only: bool = False,
    encode_preset: str = "medium",
    threads: int = 16,
):
    timeline_bytes = Path(timeline).read_bytes()
    print(
        f"rendering {timeline} -> {out} "
        f"(preview={preview}, store_only={store_only}, preset={encode_preset}, threads={threads})"
    )

    out_name = Path(out).name
    if store_only:
        meta = render_remote_to_volume.remote(
            timeline_bytes,
            out_name,
            preview=preview,
            encode_preset=encode_preset,
            threads=threads,
        )
        size_mb = meta["size_bytes"] / 1_048_576
        print(
            f"rendered to Modal volume at {meta['remote_path']} "
            f"({size_mb:.1f} MB)"
        )
        return

    output_bytes = render_remote.remote(
        timeline_bytes,
        out_name,
        preview=preview,
        encode_preset=encode_preset,
        threads=threads,
    )

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(output_bytes)
    size_mb = len(output_bytes) / 1_048_576
    print(f"wrote {out}  ({size_mb:.1f} MB)")


def _patch_paths(tl: dict, workdir: str) -> dict:
    """Remap bare filenames to /workdir/<basename> so the container finds them."""
    from pathlib import PureWindowsPath

    def _name(p: str) -> str:
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
