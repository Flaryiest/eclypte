# Eclypte — Architecture

A human-facing map of how Eclypte fits together. For agent/operational guidance see
[`AGENTS.md`](AGENTS.md) and [`CLAUDE.md`](CLAUDE.md); for the command runbook see
[`api/COMMANDS.md`](api/COMMANDS.md). This document stays high-level and diagram-oriented and defers
to the invariants documented in `CLAUDE.md` — it must not contradict them.

---

## What Eclypte is

Eclypte is an **AI AMV / short-form "reel" creator**. A user uploads a **song** (WAV or a common
audio format, auto-converted server-side) and a **source film/anime MP4**. The system analyzes both
deterministically, has an **LLM agent plan a beat-synced edit timeline**, renders it to an MP4, and
(optionally) publishes it to Instagram Reels via Buffer. A queue-driven **autopilot** can run the
whole loop unattended, stopping only at a human review gate before anything is posted.

It is deliberately **quality-over-speed**: every scene/frame of video and every beat of audio is
analyzed before an edit is composed, so a single finished video can take **hours** (movie analysis
dominates). It began as a personal/portfolio project (see [`README.md`](README.md)).

**Scale:** ~9k lines of application Python in `api/` (plus a large `api/prototyping/` worker tree),
~34 TS/TSX files in `web/src`.

---

## Three pillars

Each pillar is independently runnable and hostable.

| Pillar | Stack | Host | Role |
|---|---|---|---|
| **`web/`** | Next.js 16 (App Router), React 19, TypeScript, CSS Modules, Clerk, zustand | Vercel | Marketing site + authenticated dashboard "studio" |
| **`api/`** | FastAPI (Python 3.13), Pydantic v2, boto3 | Railway | Control plane — orchestrates runs, persists, gates publishing |
| **`api/prototyping/`** | torch/allin1, CLIP, OpenCV-CUDA, MoviePy/ffmpeg | **Modal** (GPU/CPU) | The actual analysis + render workers; also a modular test bed |

The control plane **never** runs heavy compute. It invokes named Modal functions
(`modal.Function.from_name(app, fn).remote(...)`) and reads results back from R2. Modal **snapshots
local worker code at `modal deploy` time**, so redeploying the relevant app is required after
changing bundled worker code.

**Backing services:** Cloudflare **R2** (object storage, zero egress — required), **Postgres**
(optional — run manifests/events/progress), **Redis** (optional — live run streaming), **Clerk**
(auth), **Buffer** (Instagram publishing), **OpenAI** (agent planning + captions).

---

## End-to-end pipeline

```
 Upload song (R2) ─► run_music_analysis ─► Modal: eclypte-analysis / analyze_remote
                                            tempo · beats · downbeats · 10Hz energy · segments
                                            (schema_version 1, _sec times)  + best-effort LRC lyrics

 Upload film (R2) ─► run_video_analysis ─► Modal: eclypte-video-r2 / analyze_r2
                                            scenes ─► per-scene GPU optical-flow motion ─► impacts,
                                            visual energy, poster frame, end-credit OCR cap
                        │
                        ▼
    run_timeline_plan ─► build/reuse CLIP index  (Modal: eclypte-clip-index-r2)
                       ─► OpenAI agent loop (gpt-5.5, Responses API):
                            query_clips(text) semantic search ─► finish_edit(shots, overlays)
                       ─► adapter: dedupe · re-time contiguous · beat-snap (±0.15s) ·
                            song-trim · tail fade · overlay resolve ─► validated Timeline JSON
                        │
                        ▼
          run_render ─► Modal: eclypte-render-r2 / render_r2
                         native ffmpeg filtergraph (fast)  OR  MoviePy fallback (effects/overlays)
                         ─► MP4 (H.264 CRF18, -tune animation, yuv420p, AAC 192k) + JPEG poster
                        │
                        ▼
   create_publish_post ─► OpenAI Gen-Z caption ─► status "ready"  ◄── HUMAN REVIEW GATE
                       ─► user approves ─► send-buffer (queue | schedule | now) ─► Instagram Reel
```

`run_edit_pipeline` is the parent workflow: it chains music → video → timeline → render **inline in
one background thread** (parallelism happens *inside* Modal, not across child runs), reusing any
already-completed analyses. **Autopilot** drives this same pipeline on a schedule.

---

## Subsystems

### Control plane — `api/`
- **`main.py`** — ASGI entrypoint (`app = create_app()`, uvicorn on `$PORT`).
- **`app.py`** (~2060 lines) — `create_app()` factory: CORS, dependency injection, all routes,
  background scheduling.
  - **Temp auth:** `user_id()` trusts the `X-User-Id` header verbatim (falling back to
    `ECLYPTE_DEFAULT_USER_ID`). There is **no verification yet** — so no real tenant isolation; the
    frontend simply forwards the Clerk user id. JWT verification is deferred.
  - **Route groups:** uploads/files/assets; workflow triggers (music / youtube-import / conversion,
    video, timelines, renders, edits — all `202` + background tasks); edit-job management; runs
    (list/get/events + NDJSON streams); synthesis (references / consolidations / prompt versions);
    publishing; autopilot; `/healthz`; and `/internal/progress` (Modal-worker callback, guarded by
    `X-Eclypte-Internal-Token`).
  - **`EDIT_STAGE_WEIGHTS`** (render .39, video .22, timeline .20, music .15, assets/result .02)
    produce a time-weighted overall progress bar.
- **`workflows.py`** (~1570 lines) — `WorkflowRunner` protocol + `DefaultWorkflowRunner`; every
  `run_*` workflow. Version-gates CLIP-index reuse via `CLIP_INDEX_BUILD_STEP`; caps usable source
  at `credits.content_end_sec`; fails a run if the timeline is >0.75s shorter than the trimmed song.
- **`autopilot.py`** (~500 lines) — `run_autopilot_tick` state machine
  (`pending → importing → analyzing → editing → packaged`). Ranks ~20–30s (≈25s) trim windows by
  energy (chorus bonus + 5s lead-in), dedupes `(video, song, window)`, always uses
  `reels_cinematic`, **halts after 3 consecutive failures**, and auto-creates `ready` review
  packages (`auto_created=true`) — it **never auto-posts**. Guarded by an in-process `STATE_LOCK`
  (single-replica only). Loop runs when `ECLYPTE_AUTOPILOT=1`.
- **`publishing.py`** (~680 lines) — `BufferClient` (GraphQL, Instagram `reel`), OpenAI caption
  generation (`ECLYPTE_CAPTION_MODEL`, default `gpt-5.4-mini`; deterministic fallback), public R2
  media copy, and Buffer status reconciliation. `now` posts via a near-future `dueAt` (Buffer has no
  instant publish).
- **`export_options.py`** — the single home for export behavior: `reels_9_16` (fill + `crop_focus_x`),
  `reels_cinematic` (letterbox, baked bars — autopilot default), `youtube_16_9` (letterbox — backend
  default), and `trim_song_analysis()`.
- **`youtube_download.py`** — multi-provider fallback (`pytubefix` variants → `yt-dlp`); every attempt
  logged as a run event.

### Storage substrate — `api/storage/`
- **`models.py`** — all Pydantic records (`extra="forbid"`): `FileManifest`, `FileVersionMeta`,
  `RunManifest`, `RunEvent`, `UploadReservation`, synthesis records, `PublishingPostRecord`; the
  `ArtifactKind` literal and status enums.
- **`repository.py`** — `StorageRepository`, the API-facing facade. File/upload/synthesis/publishing/
  autopilot state → **R2 JSON**; run manifests/events → a pluggable **RunStore**
  (`PostgresRunStore` when `DATABASE_URL` is set, else `R2RunStore`); durable run writes mirrored to
  **Redis** (best-effort — swallows failures, never breaks persistence).
- Supporting: `keys.py` (canonical object-key layout), `r2_client.py` (boto3 + presign + parallel
  `get_json_many`), `postgres_run_store.py`, `redis_run_broadcast.py` (user + run channels, 15s
  heartbeat), `factory.py`, `staging.py`, `backfill_runs.py` (R2→Postgres migration CLI).
- **Asset listing** hides internal kinds (render/source posters, render outputs) and archived assets
  by default, and presigns poster URLs **locally** from the deterministic version blob key (no extra
  round-trip). Prefer archive/restore over hard-delete.

### Music pipeline — `api/prototyping/music/`
- **`analysis.py`** — the pure analyzer (librosa RMS → 10 Hz normalized energy + allin1 structure);
  output is `schema_version: 1` with `_sec` timestamps.
- **`analysis_modal.py`** — Modal app `eclypte-analysis`, `analyze_remote(...)` on a T4 GPU (heavy
  torch/allin1 image; **natten pinned** to a torch/CUDA-specific wheel; persistent model-cache
  volume).
- **`lyrics.py`** — `search_synced_lyrics()` (timestamped LRC only, best-effort). Heavy deps live
  only in `requirements-modal.txt`.

### Video pipeline — `api/prototyping/video/`
- **`analysis.py`** (CPU reference) vs **`analysis_cuda.py`** (single-pass GPU decode) — only the
  CUDA path produces `credits` + `poster` and takes a progress callback.
- **`scenes.py`** (PySceneDetect), **`motion.py`** (Farneback flow → motion curve + camera-movement
  class), **`impact.py`** (impacts / stillness / visual energy), **`credits.py`** (pure
  `decide_content_end` + OCR `detect_content_end` → `content_end_sec`), **`poster.py`** (pure
  frame-scoring policy).
- **Modal apps:** `eclypte-video` (no OCR) and `eclypte-video-r2` (`analyze_r2`, bundles tesseract).
  Real credit trimming happens only on the R2 app.

### Edit — synthesis / patterns / skills — `api/prototyping/edit/`
- **`synthesis/agent.py`** — OpenAI Responses API loop (`gpt-5.5`, `reasoning_effort="high"`).
  Tools: `query_clips` and `finish_edit`. The system prompt is sent **once**; state is carried by
  `previous_response_id`.
- **`synthesis/system_prompt.py`** — the **single source of truth** for the baseline prompt (also
  imported by the control plane as `DEFAULT_SYNTHESIS_PROMPT`).
- **`synthesis/timeline_schema.py`** / **`adapter.py`** / **`validators.py`** — the strict Pydantic
  `Timeline`, the deterministic adapter (dedupe within 1.0s, **re-time all positions contiguously
  from 0** — the agent's absolute offsets are discarded, only per-shot durations survive — beat-snap
  ±0.15s, song-trim, tail fade, overlay resolution), and structural validation.
- **`patterns/`** — a declarative pattern catalog (currently **decoupled** from the live agent path).
- **`skills/`** — self-registering creative skills in three kinds: windowed overlays (`text.hook`,
  `text.caption`, `text.lower_third`, `mask.vignette`), whole-reel grades (`grade.cinematic`/
  `vibrant`/`moody`), and moment accents (`impact.shake`). Metadata is moviepy-free; `build_layers`
  (MoviePy) imports lazily, and skills with `ffmpeg_supported = True` provide an `ffmpeg_filter`
  fragment so they render on the fast native path.

### Edit — render + CLIP index — `api/prototyping/edit/render/`, `.../index/`
- **Dual render dispatch** in `render/renderer.py` via `can_render_with_ffmpeg()` (capability-driven):
  - **Native ffmpeg** (`ffmpeg_filtergraph.py` pure builder + `ffmpeg_run.py`) covers cuts/crossfade/
    whip/flash, freeze/punch_in/speed_ramp, and every ffmpeg-supported skill — one process, ~17×
    faster (frame-parity verified with MoviePy on the base montage).
  - **MoviePy fallback** only for features without a native port (now effectively legacy).
  - Both paths encode identically: **H.264 CRF 18, `-tune animation`, yuv420p, +faststart, AAC 192k**.
  - `whip` is silently a hard cut everywhere; `hold` is a no-op stub.
- **CLIP index** — `frames.py`, `embed.py` (ViT-L/14, 768-dim), `query.py`
  (`rank_with_content_filter` drops near-black/flat frames). `storage_modal.py` =
  `eclypte-clip-index-r2` (`build_index_r2`, `query_index_r2`).
- `render_storage_modal.py` = `eclypte-render-r2` (`render_r2`, bundles ffmpeg).

### Edit — reference learning — `api/prototyping/edit/reference/`
An offline CLI that ingests viral reference reels, runs the same Modal analyzers, computes
pure-Python metrics (cut-to-downbeat offsets, per-section cut density, motion-at-cuts, impact→cut
lag), and consolidates them (one OpenAI call) into `knowledge/references.md` with pattern
weight-multipliers. **Two parallel pipelines** share only download+analysis+metrics: the CLI (→
`store/*.json` + `references.md`) and the runtime path in `workflows.py` (→ Postgres records + a
deterministic guidance string that feeds active **synthesis prompt versions**). Completed runtime
references also parameterize the rhythm engine at plan time (`synthesis/style_profile.py` — cut lead
+ pacing bands from the metrics); the CLI's weight-multiplier loop remains unwired and superseded.

### Frontend — `web/`
- **Marketing** (dark "Building Dreams" theme): `/`, `/pricing`, `/demo`.
- **Dashboard "studio"** (light **"Ivory & Ink"** system — ivory `#F7F5F1`, ink `#26231E`, coral
  `#E86A4F` accent reserved for progress/attention; PP Neue Montreal; sentence case). **3-page IA:**
  Home (`/dashboard` pipeline feed — absorbed the old autopilot + publish pages), Library
  (`/dashboard/assets`), Settings (behind a gear). Power pages off-nav: `new-edit`, `synthesis`;
  old routes are redirect stubs.
- **Data layer** — `web/src/stores/` is a zustand **stale-while-revalidate** cache (30s TTL, keys
  scoped by user id, mutations patch in place). Signed media URLs are **never cached** except the
  deliberate `posterUrls.ts` `stableMediaUrl` pin.
- **`services/eclypteApi.ts`** (~1130 lines) is the typed client and the source of all domain types
  (all `/v1` endpoints, `X-User-Id` auth, NDJSON stream readers, chunked SHA256 upload).
- **`useRunStream.ts`** subscribes to `/v1/runs/stream` with a watchdog + polling fallback;
  `editEta.ts` `EDIT_STAGE_WEIGHTS` mirrors `api/app.py`.
- **Auth** is Clerk (`ClerkProvider` + `proxy.ts` — Next 16 renames `middleware.ts` → `proxy.ts`).

---

## Cross-cutting contracts & invariants

Breaking any of these silently breaks another layer:

- **Schemas** are `schema_version: 1`; time fields are seconds with the `_sec` suffix (never frame
  indices in shared schemas).
- **`RunManifest.outputs` keys are frontend contracts:** `music_analysis_file_id`/`_version_id`,
  `video_analysis_*`, `source_poster_*`, `timeline_*`, `clip_index_*`, `render_output_*`,
  `render_poster_*`, `lyrics_*`, `synthesis_prompt_version_id`, plus `<stage>_run_id` child pointers.
- **Modal app/function names** are cross-boundary contracts: `eclypte-analysis/analyze_remote`,
  `eclypte-video-r2/analyze_r2`, `eclypte-clip-index-r2/{build,query}_index_r2`,
  `eclypte-render-r2/render_r2`.
- **Export behavior lives only in `api/export_options.py`** — never reimplement format/trim/crop in
  pages, planners, adapters, or renderers.
- Keep storage / API / `eclypteApi.ts` / dashboard in sync when a contract changes, and **redeploy
  the relevant Modal app** after changing bundled worker code (especially `edit/render/**`,
  `edit/skills/**`, and the timeline schema/validators).

---

## Testing & deployment

- **Backend:** `python -m pytest api -v` (focused: `api/test_api_v1.py`, `api/storage -v`,
  `api/test_export_options.py`, `api/test_publishing.py`,
  `api/prototyping/edit/{synthesis,index} -v`). Heavy ML deps are **not** installed locally — worker
  modules import Modal-only packages at top level, so they're only importable inside the Modal image;
  tests fake librosa/allin1/CLIP/moviepy.
- **Frontend:** from `web/` — `npm run lint`, `npm run build`. Dev runs via `scripts/dev.mjs`
  (`next dev --webpack`).
- **Deploy:** Railway/Railpack uses the root `requirements.txt` + `python -m api.main` (Python 3.13);
  Modal apps deploy separately (`modal deploy`; prefix `PYTHONUTF8=1` on Windows); Vercel hosts
  `web/`.

---

## Current focus & known gaps

- **Active push:** edit quality. All four phases of the July 2026 roadmap are implemented: the
  rhythm engine (downbeat-preferred early snapping, impact→downbeat registration, section pacing),
  the ffmpeg polish foundation (skill kinds + capability-driven dispatch), the polish catalog
  (grades, impact.shake + auto-accents, real speed_ramp), and plan-time reference-derived style
  profiles. Autopilot Reels growth continues underneath (`reels_cinematic`, ~25s energy windows,
  review-gated Buffer publishing, AI captions).
- **Deferred:** `whip` transition and `hold` effect (cut/no-op); a YouTube publishing path (16:9
  renders exist, no upload integration); a single-scene vs. full-source-montage retention
  experiment; per-shot crop focus for fill-mode reels.
- **Notable soft spots:** temp auth is effectively no auth; the autopilot state lock is
  single-replica only; the pattern catalog and the CLI weight-multiplier loop
  (`reference/annotations.py`) remain unwired (superseded by the plan-time style-profile loop in
  `synthesis/style_profile.py`); a couple of stale Modal references / unused profiles exist in the
  edit prototype.
