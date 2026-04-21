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
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

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
RENDER_PROFILES = {
    "standard": {"cpu": 16, "memory": 16384, "threads": 16},
    "boosted": {"cpu": 24, "memory": 32768, "threads": 24},
}


def _resolve_render_profile(render_profile: str) -> dict:
    try:
        return RENDER_PROFILES[render_profile]
    except KeyError as exc:
        choices = ", ".join(sorted(RENDER_PROFILES))
        raise ValueError(f"unknown render profile {render_profile!r}; expected one of: {choices}") from exc


def _resolve_threads(render_profile: str, threads: int | None) -> int:
    if threads is not None:
        return threads
    return _resolve_render_profile(render_profile)["threads"]


def _log_timing(step: str, started_at: float) -> None:
    elapsed = time.perf_counter() - started_at
    print(f"[render-modal] {step}: {elapsed:.2f}s")


def _copy_to_local_staging(src_path: str, staging_dir: Path, staged_stem: str) -> str:
    source = Path(src_path)
    suffix = "".join(source.suffixes) or source.suffix
    dest = staging_dir / f"{staged_stem}{suffix}"
    shutil.copy2(source, dest)
    return str(dest)


def _stage_inputs_local(tl: dict, staging_dir: Path) -> dict:
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = dict(tl)

    if "source" in staged:
        src = dict(staged["source"])
        src["video"] = _copy_to_local_staging(src["video"], staging_dir, "source_video")
        src["audio"] = _copy_to_local_staging(src["audio"], staging_dir, "source_audio")
        staged["source"] = src

    if "audio" in staged:
        aud = dict(staged["audio"])
        aud["path"] = _copy_to_local_staging(aud["path"], staging_dir, "timeline_audio")
        staged["audio"] = aud

    return staged


def _render_impl(
    timeline_bytes: bytes,
    out_path: str,
    *,
    preview: bool,
    encode_preset: str,
    threads: int | None,
    stage_inputs_local: bool,
) -> Path:
    from edit.render.renderer import render_timeline

    overall_started = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        tl_path = os.path.join(td, "timeline.json")
        prep_started = time.perf_counter()
        tl = json.loads(timeline_bytes.decode())
        tl = _patch_paths(tl, WORKDIR)
        _log_timing("timeline load/patch", prep_started)

        if stage_inputs_local:
            stage_started = time.perf_counter()
            tl = _stage_inputs_local(tl, Path(td) / "inputs")
            _log_timing("input staging", stage_started)

        Path(tl_path).write_text(json.dumps(tl), encoding="utf-8")
        render_started = time.perf_counter()
        render_timeline(
            tl_path,
            out_path,
            preview=preview,
            encode_preset=encode_preset,
            threads=threads,
        )
        _log_timing("render_timeline", render_started)
    _log_timing("total container render work", overall_started)
    return Path(out_path)


@app.function(
    image=image,
    cpu=RENDER_PROFILES["standard"]["cpu"],
    memory=RENDER_PROFILES["standard"]["memory"],
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
    stage_inputs_local: bool = False,
) -> bytes:
    resolved_threads = _resolve_threads("standard", threads)
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, Path(out_filename).name)
        rendered = _render_impl(
            timeline_bytes,
            out_path,
            preview=preview,
            encode_preset=encode_preset,
            threads=resolved_threads,
            stage_inputs_local=stage_inputs_local,
        )
        read_started = time.perf_counter()
        output_bytes = rendered.read_bytes()
        _log_timing("final byte read", read_started)
        return output_bytes


@app.function(
    image=image,
    cpu=RENDER_PROFILES["boosted"]["cpu"],
    memory=RENDER_PROFILES["boosted"]["memory"],
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote_boosted(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
    stage_inputs_local: bool = False,
) -> bytes:
    resolved_threads = _resolve_threads("boosted", threads)
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, Path(out_filename).name)
        rendered = _render_impl(
            timeline_bytes,
            out_path,
            preview=preview,
            encode_preset=encode_preset,
            threads=resolved_threads,
            stage_inputs_local=stage_inputs_local,
        )
        read_started = time.perf_counter()
        output_bytes = rendered.read_bytes()
        _log_timing("final byte read", read_started)
        return output_bytes


@app.function(
    image=image,
    cpu=RENDER_PROFILES["standard"]["cpu"],
    memory=RENDER_PROFILES["standard"]["memory"],
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote_to_volume(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
    stage_inputs_local: bool = False,
) -> dict:
    resolved_threads = _resolve_threads("standard", threads)
    remote_out = os.path.join(WORKDIR, Path(out_filename).name)
    rendered = _render_impl(
        timeline_bytes,
        remote_out,
        preview=preview,
        encode_preset=encode_preset,
        threads=resolved_threads,
        stage_inputs_local=stage_inputs_local,
    )
    commit_started = time.perf_counter()
    edit_volume.commit()
    _log_timing("final volume commit", commit_started)
    return {
        "remote_path": remote_out,
        "size_bytes": rendered.stat().st_size,
        "preview": preview,
        "encode_preset": encode_preset,
        "threads": resolved_threads,
    }


@app.function(
    image=image,
    cpu=RENDER_PROFILES["boosted"]["cpu"],
    memory=RENDER_PROFILES["boosted"]["memory"],
    timeout=3600,
    volumes={WORKDIR: edit_volume},
)
def render_remote_boosted_to_volume(
    timeline_bytes: bytes,
    out_filename: str = "output.mp4",
    *,
    preview: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
    stage_inputs_local: bool = False,
) -> dict:
    resolved_threads = _resolve_threads("boosted", threads)
    remote_out = os.path.join(WORKDIR, Path(out_filename).name)
    rendered = _render_impl(
        timeline_bytes,
        remote_out,
        preview=preview,
        encode_preset=encode_preset,
        threads=resolved_threads,
        stage_inputs_local=stage_inputs_local,
    )
    commit_started = time.perf_counter()
    edit_volume.commit()
    _log_timing("final volume commit", commit_started)
    return {
        "remote_path": remote_out,
        "size_bytes": rendered.stat().st_size,
        "preview": preview,
        "encode_preset": encode_preset,
        "threads": resolved_threads,
    }


@app.local_entrypoint()
def main(
    timeline: str = "./edit/content/timeline.json",
    out: str = "./edit/content/output.mp4",
    preview: bool = False,
    store_only: bool = False,
    render_profile: str = "standard",
    render_stage_inputs_local: bool = False,
    encode_preset: str = "medium",
    threads: int | None = None,
):
    timeline_bytes = Path(timeline).read_bytes()
    resolved_threads = _resolve_threads(render_profile, threads)
    print(
        f"rendering {timeline} -> {out} "
        f"(preview={preview}, store_only={store_only}, profile={render_profile}, "
        f"stage_inputs_local={render_stage_inputs_local}, preset={encode_preset}, "
        f"threads={resolved_threads})"
    )

    out_name = Path(out).name
    remote_render = render_remote if render_profile == "standard" else render_remote_boosted
    remote_render_to_volume = (
        render_remote_to_volume
        if render_profile == "standard"
        else render_remote_boosted_to_volume
    )
    if store_only:
        meta = remote_render_to_volume.remote(
            timeline_bytes,
            out_name,
            preview=preview,
            encode_preset=encode_preset,
            threads=resolved_threads,
            stage_inputs_local=render_stage_inputs_local,
        )
        size_mb = meta["size_bytes"] / 1_048_576
        print(
            f"rendered to Modal volume at {meta['remote_path']} "
            f"({size_mb:.1f} MB)"
        )
        return

    output_bytes = remote_render.remote(
        timeline_bytes,
        out_name,
        preview=preview,
        encode_preset=encode_preset,
        threads=resolved_threads,
        stage_inputs_local=render_stage_inputs_local,
    )

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(output_bytes)
    size_mb = len(output_bytes) / 1_048_576
    print(f"wrote {out}  ({size_mb:.1f} MB)")


def _patch_paths(tl: dict, workdir: str) -> dict:
    """Remap bare filenames to /workdir/<basename> so the container finds them."""
    def _name(p: str) -> str:
        windows_name = PureWindowsPath(p).name
        if windows_name and windows_name != p:
            return windows_name
        return PurePosixPath(p).name

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
