# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Eclypte is an AMV (Anime Music Video) creator. Monorepo layout:

- **`web/`** — Next.js 16 frontend (React 19, TypeScript, App Router). [web/CLAUDE.md](web/CLAUDE.md) re-exports [web/AGENTS.md](web/AGENTS.md) — the Next.js 16 warning applies to anything under `web/`.
- **`api/`** — Python backend. `api/main.py` is still an empty FastAPI stub; real work lives in `api/prototyping/` (see Audio Pipeline below).

The audio pipeline emits `song_analysis.json` and the video pipeline emits a "clip map" JSON — both use `schema_version: 1` and the `_sec` suffix for timestamps. The edit pipeline (`api/prototyping/edit/`, see Edit Pipeline below) consumes both, so keep their timestamp conventions aligned (seconds, not frames) when extending either side.

## Development Commands

Web (run from `web/`):

```bash
cd web
npm run dev      # Next.js dev server
npm run build    # Production build
npm run start    # Production server
npm run lint     # ESLint (flat config: core-web-vitals + typescript)
```

### API setup — Modal (serverless GPU)

**The heavy audio analysis runs on Modal, not locally.** `allin1` depends on
`natten`, a compiled PyTorch extension with no Windows wheels and strict
Python/torch/CUDA version coupling. Rather than force everyone into WSL2,
we run `analyze()` inside a Modal container (Linux, T4 GPU) and keep the
rest of the pipeline (`ytdownload`, `lyrics`, `main.py`) native.

**Two requirements files:**

- [api/requirements.txt](api/requirements.txt) — local deps only (`modal`,
  `pytubefix`, `pydub`, `syncedlyrics`). Installs in under a minute on any OS.
- [api/requirements-modal.txt](api/requirements-modal.txt) — heavy ML stack
  (`torch==2.6.0`, `allin1`, `madmom`, `librosa`, plus the ~11 undeclared
  allin1 transitive deps). Installed into the Modal image once, then cached.

`natten` is not in either file — it's installed via `run_commands` inside
[api/prototyping/music/analysis_modal.py](api/prototyping/music/analysis_modal.py) because
its wheel URL is torch/CUDA/Python-specific (`natten==0.17.4+torch250cu121`
from `https://shi-labs.com/natten/wheels/cu121/torch2.5.0/`, via
`--trusted-host shi-labs.com` because their SSL cert is intermittently expired).

**Pinned versions (inside the Modal image):**

| Package | Version | Why |
|---|---|---|
| Python | 3.12 | Newest Python with cp312 natten 0.17.4 wheels. |
| torch | 2.5.0 | Newest torch with natten 0.17.4 wheels. Must pin torchaudio + torchvision to match or demucs drags in a newer torchaudio that demands libcudart.so.13. |
| natten | 0.17.4 | Last version that still exports `natten1dav`/`natten2dav`/etc — the camelCase ops allin1 imports. 0.17.5 dropped them. |
| CUDA | 12.1 | Matches the shi-labs wheel index + Modal T4 GPU (CUDA-forward compatible). |

Do not bump any of these without a plan: natten 0.17.5+ removes the deprecated
camelCase ops allin1 imports, natten 0.20+ removes the entire unfused backend,
and Python 3.13 has no natten wheels at all.

Deprecation warnings during inference (`natten.functional.natten1dav ... is
deprecated in favor of na1d_av`) are expected and harmless — allin1 hasn't
migrated to the new API yet.

**One-time setup (native Windows / macOS / Linux — no WSL needed):**

```bash
cd api
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
modal token new      # browser-based auth; writes ~/.modal.toml
```

**Running:**

```bash
cd api/prototyping/music

# End-to-end: download → Modal analyze → lyrics
python main.py

# Modal-only sanity check (skips ytdownload and lyrics):
modal run analysis_modal.py::main --wav ./content/output.wav
```

First remote call builds the image (~2–3 min) and downloads ~400MB of allin1
model weights into the `allin1-cache` Modal Volume at `/root/.cache`. Both are
cached — subsequent runs skip straight to ~15–25s of GPU inference.

**Costs:** T4 GPU ≈ $0.60/hr. Per-song cost ≈ $0.005. Modal's free tier
(~$30/mo credit) covers thousands of songs.

No test runner is configured yet.

### Dependency landmines

- **allin1 does not declare its full runtime dep tree** in its PyPI metadata.
  `requirements-modal.txt` adds ~11 deps (demucs, madmom, huggingface-hub,
  hydra-core, omegaconf, scipy, scikit-learn, timm, tqdm, mido, pandas) that
  allin1 imports but does not list. If you hit a new `ModuleNotFoundError`
  inside the Modal container, add the package to `requirements-modal.txt`.
- **madmom builds from source from a git fork** (`CPJKU/madmom@main`) because
  the PyPI release is from 2018 and doesn't compile on modern Python. The
  Modal image handles ordering: `pip install cython numpy` runs before
  `pip_install_from_requirements` so madmom's build sees them.
- **natten is pinned to 0.17.4+torch250cu121** on purpose. 0.17.5 dropped the
  deprecated camelCase ops (`natten1dav`, `natten2dqkrpb`, etc) that allin1
  still imports. Do not bump.
- **torchaudio and torchvision must be pinned to 2.5.0 / 0.20.0** next to
  torch 2.5.0. demucs pulls torchaudio transitively and will grab a newer
  release that requires libcudart.so.13 if left unpinned.
- **`/root/.cache` can't be a Volume mount point** in this image because the
  pip install layers leave files there even after `rm -rf`. The image creates
  a symlink `/root/.cache -> /cache` and mounts the `allin1-cache` Volume at
  `/cache` instead, so allin1's `~/.cache/allin1/` weights persist as expected.
- **analysis.py must stay pure** (no `import modal`). The Modal image loads
  it via `add_local_python_source("analysis")`; the wrapper in
  `analysis_modal.py` is the only place Modal knows about it.

### AWS deploy (not yet done)

Modal covers dev and early prod. If/when we move off Modal, the image
definition in `analysis_modal.py` maps directly to a Dockerfile: same Linux
base, same apt packages, same pip installs, same natten wheel. No code
changes expected.

## Audio Pipeline (`api/prototyping/music/`)

MVP audio analysis lives in the prototyping sandbox. Scripts are wired together by [api/prototyping/music/main.py](api/prototyping/music/main.py).

Note the name collision: [api/prototyping/music.py](api/prototyping/music.py) (a top-level file, not the `music/` directory) is an unused 10-line librosa `beat_track` scratch — ignore it when tracing the pipeline.

- **[ytdownload.py](api/prototyping/music/ytdownload.py)** — `main(video_url) -> title`. Downloads YouTube audio via `pytubefix` to `content/output.m4a`, transcodes to `content/output.wav` via `pydub`. The URL is currently a module-level `url` constant.
- **[analysis.py](api/prototyping/music/analysis.py)** — `analyze(audio_path, out_path=None) -> dict`. Pure function producing the "song map" JSON (`schema_version: 1`) with tempo, beats, downbeats, a 10Hz normalized energy curve, and structural segments. Uses `allin1` (PyTorch model) as the single source of truth for beats/downbeats/segments; `librosa` only for audio loading and RMS. All timestamps use the `_sec` suffix — no frame indices escape the module. **Does not import `modal`** — it runs inside the Modal container via `add_local_python_source`.
- **[analysis_modal.py](api/prototyping/music/analysis_modal.py)** — Modal image definition + `analyze_remote(audio_bytes, filename) -> dict`. Thin wrapper: writes bytes to a tempfile in-container, calls `analysis.analyze()`, returns the dict. One round-trip, stateless. T4 GPU, 600s timeout, `allin1-cache` Volume mounted at `/root/.cache`.
- **[lyrics.py](api/prototyping/music/lyrics.py)** — `main(query)`. Uses `syncedlyrics` to fetch an LRC, writes `content/lyrics.txt`. Intentionally separate from `song_analysis.json` (different source, optional).

Song-map consumers read `content/output.json`. Schema details and design decisions are in the approved plan at `.claude/plans/glistening-enchanting-bumblebee.md` (if present) — timestamps are seconds, `downbeats_sec` is a subset of `beats_sec`, `segments.label` passes through allin1's vocabulary unchanged.

Deferred to v2 (bump `schema_version` when adding): onsets, per-band energy (low/mid/high), key & mode.

## Video Pipeline (`api/prototyping/video/`)

Deterministic (non-AI) video analysis — scenes, motion, impacts — producing
a JSON "clip map" keyed by `schema_version: 1`. Consumed downstream by the AI
editing agent to sync cuts to music. Two runtimes share the same output shape:

- **Local CPU** — [api/prototyping/video/main.py](api/prototyping/video/main.py)
  `main()` → `analyze(clip, out_path)` from
  [analysis.py](api/prototyping/video/analysis.py). Uses
  `cv2.calcOpticalFlowFarneback` on the CPU. Fine for <2 min clips; ~30 fps
  throughput at 640×360.
- **Modal GPU** — `main_remote(filename)` → `VideoAnalyzer().analyze.remote(filename)`
  from [analysis_modal.py](api/prototyping/video/analysis_modal.py) →
  [analysis_cuda.py](api/prototyping/video/analysis_cuda.py) using
  `cv2.cuda.FarnebackOpticalFlow`. For multi-hour footage. ~6–15× faster on
  the flow kernel; single-pass decode, no per-scene seeking.

**Modules** (all under `api/prototyping/video/`):

- **[scenes.py](api/prototyping/video/scenes.py)** — `detect_scenes(video_path, duration_sec) -> [(start_sec, end_sec)]`. PySceneDetect ContentDetector, threshold 27.0. Returns a single whole-clip scene if nothing detected.
- **[motion.py](api/prototyping/video/motion.py)** — two entry points: `motion_per_scene(video_path, scene, fps_hz)` (CPU, opens capture + seeks) and `build_motion_dict(mags, vxs, vys, rads, diffs, start_sec, fps_hz)` (pure; reused by both CPU and GPU paths). Also exposes `flow_stats(flow)` and `to_gray_small(frame)` as shared helpers. Returns normalized motion curve, camera-movement class (`static`/`pan`/`tilt`/`whip_pan`/`zoom`/`handheld`), stability score, and underscore-prefixed raw signals consumed by `impact.py`.
- **[impact.py](api/prototyping/video/impact.py)** — `impacts_per_scene(scene, motion, fps_hz)`. Adaptive-threshold impact detection: `median + K*MAD` on a combined flow+frame-diff visual-energy signal. Classifies `flash` / `motion_spike` / `combined`. Also emits stillness points and the full `visual_energy` curve.
- **[analysis.py](api/prototyping/video/analysis.py)** — CPU orchestrator. `analyze(video_path, out_path=None) -> dict`. Must stay pure (no `import modal`) — loaded into the Modal image via `add_local_python_source`.
- **[analysis_cuda.py](api/prototyping/video/analysis_cuda.py)** — GPU orchestrator. Opens the video once, streams frames sequentially, dispatches per-frame signals to the scene they belong to via a `_SceneAccumulator`. Resets `prev_gpu`/`prev_gray` at scene boundaries so flow never crosses cuts.
- **[analysis_modal.py](api/prototyping/video/analysis_modal.py)** — Modal image build + wrappers. `VideoAnalyzer.analyze(filename)` (a `modal.Cls` method) reads from the `eclypte-video-input` Volume at `/input/{filename}`; `analyze_remote_bytes(video_bytes, filename)` writes to a tempfile for small test clips. The class shape exists so `with_options(gpu=...)` can override the T4 default at call time — a knob `modal.Function` does not expose.

All timestamps use the `_sec` suffix. `fps_hz` is the canonical sampling rate. Same `schema_version: 1` convention as the audio pipeline.

### Video — Modal setup (serverless GPU)

**Why Modal for video too:** `cv2.cuda.FarnebackOpticalFlow` needs OpenCV built
with CUDA support. There are no prebuilt OpenCV-CUDA wheels on any platform —
you must compile from source against a matching CUDA toolkit. That's fragile
locally (same class of pain as `natten` for audio). The Modal image builds
OpenCV 4.10.0 from source once, then caches the layer; subsequent runs skip
straight to GPU inference.

**Pinned versions (inside the Modal image):**

| Package | Version | Why |
|---|---|---|
| CUDA base | `nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04` | Matches T4 driver compatibility. Same CUDA 12.1 as the audio image. |
| OpenCV | 4.10.0 | Stable `cv2.cuda.FarnebackOpticalFlow` API. Built with `-DWITH_CUDA=ON -DWITH_CUDNN=ON -DOPENCV_DNN_CUDA=OFF`. |
| `CUDA_ARCH_BIN` | 7.5;8.0;8.6;9.0 | Fat binary covering T4 (7.5), A100 (8.0), A10G/A10 (8.6), H100/H200 (9.0). Use **semicolons**, not commas — commas silently fail on some cmake versions. |
| Python | 3.11 | Added to the CUDA base via `add_python="3.11"`. |
| scenedetect | (unpinned) | Pure-Python, low risk. |

The image is multi-arch, so `gpu=` is a free knob. Override at call time via `VideoAnalyzer.with_options(gpu="A100")().analyze.remote(...)`, or pass `--gpu A100` to the [local entrypoint](api/prototyping/video/analysis_modal.py). Adding a new arch (e.g. L4's 8.9) requires editing `CUDA_ARCH_BIN` and triggering a one-time OpenCV rebuild (~20–40 min).

**One-time upload of source video to a Modal Volume:**

```bash
modal volume put eclypte-video-input ./content/movie.mp4
```

**Running:**

```bash
cd api/prototyping/video

# Local CPU path (small clips):
python main.py

# Modal GPU path (hours of footage):
modal run analysis_modal.py --filename movie.mp4
```

First remote call builds OpenCV-CUDA inside the image (~20–40 min). The layer is cached; subsequent runs skip straight to GPU inference. A 10 h video takes ~20–40 min end-to-end post-build (GPU flow pass + CPU scene detection).

**Costs:** T4 ≈ $0.60/hr. A 10 h video ≈ ~$0.30. Modal's free tier covers many dozens of feature-length analyses.

### Video — fallback: 16 vCPU CPU container

If the OpenCV-CUDA image build becomes intractable on some future CUDA/driver bump, the fallback is a Modal CPU container with `modal.Image.debian_slim() + pip install opencv-python scenedetect` and `ProcessPoolExecutor(max_workers=16)` fanning out `cv2.calcOpticalFlowFarneback` over scenes. Expected ~12–15× speedup over the single-threaded local CPU path, ~$0.30 per 10 h job at Modal's CPU pricing — similar cost, simpler infra. Output schema is unchanged, so `analysis.py` and every consumer stay as-is.

## Edit Pipeline (`api/prototyping/edit/`)

Takes `(song_analysis.json, source_analysis.json, song.wav, source.mp4)` and produces a rendered AMV MP4. Three phases — all complete: Phase 1 is the deterministic planner (no LLM, no embeddings), Phase 2 is the reference-AMV consolidator, Phase 3 is the CLIP index + `gpt-5.4` synthesis agent (OpenAI Responses API, `reasoning_effort="high"`, `verbosity="low"`). What remains deferred: render effects/transitions (freeze, speed-ramp, whip, crossfade, flash — stubs in `render/effects.py` and `render/transitions.py`).

The user-facing runbook with every invocation lives at [api/COMMANDS.md](api/COMMANDS.md) — this file is the architecture reference; COMMANDS.md is "how do I actually run it".

**Two-step flow** — plan locally (fast, no GPU), render on Modal. Run `main.py` from the **repo root** (module invocation); run `render_modal.py` from **`api/prototyping/`** (for `add_local_python_source("edit")` to resolve).

```bash
# Phase-1 plan (deterministic):
python -m api.prototyping.edit.main \
    --song   api/prototyping/music/content/output.wav \
    --source api/prototyping/video/content/source.mp4 \
    --out    api/prototyping/edit/content/timeline.json

# Phase-3 plan (gpt-5.4 agent; requires CLIP index + OPENAI_API_KEY):
python -m api.prototyping.edit.main \
    --song   api/prototyping/music/content/output.wav \
    --source api/prototyping/video/content/source.mp4 \
    --out    api/prototyping/edit/content/timeline_agent.json \
    --agent \
    --instructions "Fast-paced action AMV, open strong, tell the full story chronologically."

# Plan + render in one command — add --render (and optional --render-out):
python -m api.prototyping.edit.main ... --render --render-out api/prototyping/edit/content/output.mp4

# Or render manually (must be run from api/prototyping/):
cd api/prototyping && modal run edit/render_modal.py \
    --timeline edit/content/timeline.json \
    --out      edit/content/output.mp4
```

One-off volume setup when a source/audio pair changes:

```bash
modal volume create eclypte-edit  # first time only
modal volume put    eclypte-edit api/prototyping/music/content/output.wav
modal volume put    eclypte-edit api/prototyping/video/content/source.mp4
```

**Subsystems:**

- **[patterns/](api/prototyping/edit/patterns/)** — 5-layer pattern catalog (`micro` / `transition` / `shot_move` / `meso` / `macro`) with stable `<layer>.<slug>` IDs. [knowledge/patterns.yaml](api/prototyping/edit/knowledge/patterns.yaml) seeds 12 patterns. [registry.py](api/prototyping/edit/patterns/registry.py) loads + filters by section/energy/bpm/motion/camera; [compose.py](api/prototyping/edit/patterns/compose.py) picks macro + meso-per-section and expands meso→required atoms.
- **[synthesis/](api/prototyping/edit/synthesis/)** — [timeline_schema.py](api/prototyping/edit/synthesis/timeline_schema.py) (pydantic v2), [validators.py](api/prototyping/edit/synthesis/validators.py) (contiguity within 1 ms, bounds, pattern-id refs), [prompt.py](api/prototyping/edit/synthesis/prompt.py) (allin1 label → intent + energy target), [planner.py](api/prototyping/edit/synthesis/planner.py) (deterministic Phase-1 baseline), [agent.py](api/prototyping/edit/synthesis/agent.py) (Phase-3 `gpt-5.4` Responses-API tool-use loop — see below), [adapter.py](api/prototyping/edit/synthesis/adapter.py) (converts agent output → validated `Timeline` — dedupes duplicate `source_timestamp`s, trims last shot to song duration, reuses the planner's contiguity post-pass).
- **[index/](api/prototyping/edit/index/)** — Phase-3 CLIP retrieval + Phase-1 motion-stat retrieval. [frames.py](api/prototyping/edit/index/frames.py) extracts `(timestamp_sec, bgr_array)` tuples by **sequentially decoding** and keeping every Nth frame (N = `round(source_fps / target_fps)`). Do NOT revert to the per-frame `CAP_PROP_POS_MSEC` seek — it's 10-20× slower on long videos because every seek resets to a keyframe. [embed.py](api/prototyping/edit/index/embed.py) encodes frames and text queries via CLIP ViT-L/14 → normalized 768-d vectors. [index_modal.py](api/prototyping/edit/index/index_modal.py) Modal T4 app: video → frames → embeddings → `.npz` committed to `eclypte-edit` volume. [query_modal.py](api/prototyping/edit/index/query_modal.py) Modal T4 app: loads `.npz`, embeds text, returns top-k `[{timestamp, score}]`. [query.py](api/prototyping/edit/index/query.py) exposes **two** functions: `query_clips(query, video_filename, top_k=5)` (Phase-3, CLIP via Modal) and `query_ranges(scenes, section, query_text, ...)` (Phase-1, pure motion-stat scoring). Both must stay.
- **[render/](api/prototyping/edit/render/)** — [renderer.py](api/prototyping/edit/render/renderer.py) (moviepy v2: `subclipped`, `with_duration`, `resized`, `concatenate_videoclips(method="compose")`, `with_audio` once at composite). `effects.py` and `transitions.py` are Phase-1 no-ops (freeze, speed-ramp, whip, crossfade, flash all deferred).
- **[main.py](api/prototyping/edit/main.py)** — CLI wrapper; defaults analysis JSON paths to `<media>.with_suffix(".json")` and fails with the correct Modal command to run if missing. Reconfigures `sys.stdout`/`stderr` to UTF-8 at import so the module prints safely on Windows (no `PYTHONIOENCODING` needed for the Python process itself). Flags: `--agent --instructions "..."` switches from the Phase-1 planner to the Phase-3 agent; `--render --render-out ...` subprocesses `modal run edit/render_modal.py` from `api/prototyping/` after writing the timeline. Planner imports are lazy inside `_run_planner` so the agent path doesn't pay Phase-1's dependency surface.
- **[render_modal.py](api/prototyping/edit/render_modal.py)** — Modal wrapper. App `eclypte-edit`, volume `eclypte-edit` at `/workdir`. Image is a fresh `debian_slim(python_version="3.12")` + ffmpeg + moviepy>=2 + pydantic>=2 + pyyaml + numpy + imageio-ffmpeg + `add_local_python_source("edit")` — no torch, no allin1, no OpenCV. **16 vCPU / 16 GB / 1800 s timeout, no GPU.** Renderer is CPU-bound (stock x264 encode via moviepy/ffmpeg) — an A100 would not help unless the image ships a CUDA ffmpeg build and the pipeline is rewritten to use NVENC/NVDEC. vCPU count is the dial that actually moves render time.

**Rules and landmines:**

- **`render_modal.py` must be invoked from `api/prototyping/`.** `add_local_python_source("edit")` resolves relative to the invocation cwd; running it from the repo root or from `edit/` won't upload the package correctly.
- **`eclypte-edit` volume must exist before `modal volume put`** — `modal volume create eclypte-edit` is a one-off prerequisite. Was a first-run foot-gun.
- **Windows → Linux path handling.** Timeline JSON may contain Windows-style paths (`video\content\foo.mp4`). `_patch_paths` in `render_modal.py` uses `PureWindowsPath(p).name` — Linux `pathlib.Path` treats `\` as a literal, not a separator, and silently returns the whole string.
- **Planner output is always contiguous.** `_pick_range` has a 4-level fallback so it never returns None; a post-pass then rewrites every `timeline_start_sec` / `timeline_end_sec` via `shot.model_copy(update=...)` so shots stitch perfectly regardless of segment-boundary math. Don't remove either — the validator rejects gaps ≥ 1 ms.
- **Renderer reads JSON only.** `render_timeline` has no dependency on patterns, sections, or embeddings. Keep it that way so timelines stay re-renderable, diff-able, and portable across Phase boundaries.
- **Stable `query_clips` signature.** `index/query.py`'s `query_clips(query, video_filename, top_k)` is the contract between the Phase-3 agent and the Modal index. Don't change the arg list without also updating `synthesis/agent.py`.
- **Agent `.env` location is fixed.** [synthesis/agent.py](api/prototyping/edit/synthesis/agent.py) loads env vars from `api/prototyping/edit/synthesis/.env` via `load_dotenv(_ENV_PATH)` where `_ENV_PATH = Path(__file__).resolve().parent / ".env"`. Put `OPENAI_API_KEY=...` there. `.env` is gitignored. Note: adding `PYTHONIOENCODING=utf-8` to this file has **no effect** — Python reads that env var at interpreter startup, before `load_dotenv()` runs. Use `setx` / `$env:` / the `sys.stdout.reconfigure` call in `main.py` instead.
- **Agent-output adapter has two safety nets that are load-bearing.** (1) Duplicate-`source_timestamp` dedupe at 0.1s tolerance — LLMs reliably emit near-duplicate timestamps from the top of a `query_clips` result set; without dedupe the renderer shows the same clip back-to-back. Drops with a warning print. (2) Song-duration trim — agents round `end_time` up a fraction (e.g., 99.60 for a 99.59s song) and moviepy's audio `subclipped` rejects out-of-bounds ends. The adapter shortens the last shot's `timeline_end_sec` AND `source.end_sec` by the overshoot. Both live in [adapter.py](api/prototyping/edit/synthesis/adapter.py); removing either breaks real agent outputs.
- **Agent Responses-API state lives on OpenAI's side.** Each loop iteration passes `previous_response_id=response.id` instead of re-uploading the full message history. Breaking this means passing `input=[...everything...]` on every call — expensive and never what you want for Responses.
- **`edit/content/` is gitignored** like the music and video content folders.

**Phase 2 — Reference consolidator (`api/prototyping/edit/reference/`):**

- `download.py` — `download_reference(url, workdir)` downloads viral AMVs via yt-dlp → `ReferenceMedia(audio_wav, video_mp4, meta)`.
- `metrics.py` — `compute_metrics(music, video)` extracts cut-timing stats: `cut_offsets_to_downbeats`, `cut_density_per_section`, `motion_at_cuts`, `impact_to_cut_lag`, `shot_duration_per_section`.
- `ingest.py` — `ingest(url, likes, views, store_dir)` full pipeline: download → Modal analyses → stores `store/<ref_id>.json`.
- `consolidate.py` — `consolidate(store_dir, references_md_path, model)` calls GPT-4o; LLM rewrites `knowledge/references.md` whole (three H2 sections: Discovered Patterns, Weighted Annotations, Correlations).
- `annotations.py` — `parse_annotations(md_path, known_pattern_ids)` extracts `{pattern_id: multiplier}` dict (clamped [0.5, 1.5]) for use by `main.py`.
- Run via `python -m api.prototyping.edit.reference <ingest|consolidate|list|show>`.

**Phase 3 — CLIP index + synthesis agent:**

One-time prerequisites:

```bash
# Build the CLIP index for this source (Modal T4; ~100s image build, ~30s inference):
cd api/prototyping && modal run edit/index/index_modal.py --video-filename "source.mp4"

# Deploy the query endpoint (one-time; `query_clips` uses modal.Function.from_name):
cd api/prototyping && modal deploy edit/index/query_modal.py

# Put OPENAI_API_KEY in api/prototyping/edit/synthesis/.env
```

Then plan + render through the standard CLI:

```bash
python -m api.prototyping.edit.main \
    --song   api/prototyping/music/content/output.wav \
    --source api/prototyping/video/content/source.mp4 \
    --out    api/prototyping/edit/content/timeline_agent.json \
    --agent --instructions "Fast-paced action AMV, open strong, tell the full story chronologically." \
    --render --render-out api/prototyping/edit/content/output_agent.mp4
```

Under the hood, `--agent` calls `run_synthesis_loop(video_filename, instructions, song=<song_analysis_dict>)` in [synthesis/agent.py](api/prototyping/edit/synthesis/agent.py), which:

- Hits **`client.responses.create(model="gpt-5.4", reasoning={"effort":"high"}, text={"verbosity":"low"}, tool_choice="auto", ...)`** on OpenAI.
- Carries state across turns via `previous_response_id` (no message-history re-upload).
- Exposes two tools with the flatter Responses-API schema (`{"type":"function","name":...,"parameters":...}`, no nested `"function"` key):
  - `query_clips(query, top_k)` — proxies to Modal CLIP index.
  - `finish_edit(timeline)` — submits final `[{start_time, end_time, source_timestamp}]` and ends loop.
- Injects the song's duration, tempo, and section list into the user message via `_format_song_context(song)` so the agent sizes the edit to the music (dense cuts in choruses, longer holds in verses, etc.).
- Appends a `{"type":"message","role":"user","content": REMINDER_TEXT}` after every `query_clips` tool turn — keeps the "unique timestamps + chronological" rule in active attention across up to `MAX_LOOPS = 10` iterations.
- If the model emits non-tool content, the loop pushes a "please call `finish_edit`" nudge and continues.

The raw `run_synthesis_loop` output is `list[{start_time, end_time, source_timestamp}]`. Conversion to a renderable `Timeline` is done by [synthesis/adapter.py](api/prototyping/edit/synthesis/adapter.py) — see the load-bearing adapter landmines above. The **adapter is where quality-control happens**: prompt engineering + agent reasoning get you 90% there; dedupe + duration trim are what make the output reliably renderable.

Model/param overrides live at module-scope constants in `agent.py`: `MODEL`, `REASONING_EFFORT`, `VERBOSITY`, `MAX_LOOPS`. Revert to `"gpt-4o"` + Chat Completions is one model-constant line if `gpt-5.4` ever misbehaves; the Responses-API scaffolding stays as a strict upgrade regardless.

## Next.js 16 — READ BEFORE WRITING CODE

This project uses **Next.js 16.2.3** with **React 19.2**. These versions postdate common training data and have breaking API/convention changes from Next.js 13–15. Do not assume APIs from memory.

Before writing or modifying anything touching Next.js (routing, data fetching, `headers()`/`cookies()`/`params`, caching, config, metadata, middleware, server actions, etc.), consult `web/node_modules/next/dist/docs/` and heed any deprecation notices you find there. See also [web/AGENTS.md](web/AGENTS.md).

Middleware lives at [web/src/proxy.ts](web/src/proxy.ts) (not `middleware.ts`) — Next.js 16's renamed convention. Export a default function and a `config.matcher`; the filename is what the framework recognizes.

## Architecture Notes

- **App Router** — pages live in `web/src/app/`. Components use CSS Modules (`.module.css` co-located with each component).
- **Path aliases** — `@/*` maps to `web/src/*` and `@components/*` maps to `web/src/components/*` (configured in `web/tsconfig.json`).
- **Components** — shared UI lives in `web/src/components/` (e.g. `navbar/`, `hero/`, `stepCard/`, `statCard/`, `reveal/`, `login/`). Each component is a directory with a `.tsx` file and a co-located `.module.css` file.
- **Page layout** — the root layout (`layout.tsx`) provides fonts and the `ThemeProvider` but no shared navigation. Each page imports `<Navbar />` individually — there is no global layout-level nav.
- **Home page (`web/src/app/page.tsx`)** — section order, top to bottom: hero (`<HeroLayers />` + tagline) → `#steps` (3× `<StepCard>` in a grid) → about band → stats (placeholder image + 3× `<StatCard>`) → CTA button. All section styles live in [web/src/app/page.module.css](web/src/app/page.module.css).
- **Scroll-reveal animations** — wrap a section in [`<Reveal>`](web/src/components/reveal/reveal.tsx) to get a `data-revealed` attribute set once it enters the viewport (IntersectionObserver, threshold 0.2, fires once then disconnects). Children opt in via `[data-revealed] .yourClass { ... }` selectors in the parent's CSS module — see `.stepsTitle` in `page.module.css`. Always pair with a `@media (prefers-reduced-motion: reduce)` override.
- **Presentational cards** — [`<StepCard>`](web/src/components/stepCard/stepCard.tsx) (`number` / `title` / `description`) and [`<StatCard>`](web/src/components/statCard/statCard.tsx) (`value` / `label` / `description`) are pure prop-driven components with no state. Reuse before adding new card variants.
- **Theming** — `next-themes` with `attribute="data-theme"` on `<ThemeProvider>`. Default theme is dark. CSS variables defined in `:root` and overridden via `[data-theme="dark"]` in `globals.css`:
  - `--color-background`, `--color-primary`, `--color-secondary`, `--color-subtitle`, `--color-highlight` (gold accent, #e8a838)
- **Fonts** — loaded in `web/src/app/layout.tsx` and applied to `<body>` as CSS variable classes:
  - Google fonts: `--font-inter`, `--font-inter-tight`, `--font-outfit`
  - Local fonts (from `web/public/fonts/`): `--font-neue` (PP Neue Montreal), `--font-eiko` (PP Eiko)
  - The bootstrapped `web/README.md`'s mention of Geist is stale — ignore it.
- **Global styles** — `web/src/app/globals.css` includes a CSS reset, theme variables, and base element styles. A `.page` utility class provides a centered full-width page wrapper. Do not use `#root` selectors — Next.js has no `#root` element.
- **Images** — uses native `<picture>`/`<source>` elements, not `next/image`. This is intentional; do not migrate to `<Image>`.
- **Static assets** — images live in `web/public/assets/` (e.g. `hero/` subdirectory).
- **Z-index hierarchy** — navbar sits at 50000, hero layers at 1–10000, page content at default. New components should respect this stacking order.
- **Responsive breakpoint** — 768px (`max-width`) is the standard mobile breakpoint used throughout the CSS Modules.
- **Reduced motion** — animations respect `@media (prefers-reduced-motion: reduce)`. New animations must do the same.
