# CLAUDE.md

This file gives Claude Code working context for Eclypte. The repo-wide agent guide is `AGENTS.md`; this file keeps the same architecture in a Claude-oriented, operational form.

## Project Summary

Eclypte is an AMV creator monorepo. The dashboard is a Next.js 16 frontend; the backend is a FastAPI control plane that schedules media work, persists artifacts in Cloudflare R2, and delegates heavy audio/video/render/index jobs to Modal. Optional Postgres stores run manifests/events/progress; optional Redis broadcasts realtime run updates to the dashboard.

Core invariants:

- Audio and video analysis payloads use `schema_version: 1`.
- Time fields use seconds and the `_sec` suffix. Do not leak frame indices into shared schemas.
- `RunManifest.outputs` keys are frontend contracts. Change them only with coordinated API and frontend updates.
- Export behavior belongs in `api/export_options.py`; do not reimplement format/trim/crop logic in pages, planners, adapters, or renderers.
- Browser uploads are WAV audio and MP4 video only in the current v1 flow.

## Top-Level Layout

- `web/`: Next.js 16.2.3, React 19.2, TypeScript, App Router. `web/AGENTS.md` has frontend-specific warnings.
- `api/`: FastAPI app, workflow orchestration, storage substrate, YouTube downloader, and prototype media pipelines.
- `api/publishing.py`: review-gated Buffer publishing helpers for Instagram Reels, OpenAI/fallback caption generation, public R2 media copies, Buffer GraphQL payloads, and channel diagnostics.
- `api/content_radar.py`: TMDb-backed movie/TV discovery for new/trending available-now candidates, including watch-provider filtering and scoring.
- `api/auto_import.py`: parses incoming R2 collection media keys into bucket-import candidates for the auto-import/auto-draft lane.
- `api/storage/`: R2 object access, file manifests, file versions, upload reservations, run manifests/events/progress, prompt versions, references, content candidates, publishing posts, Postgres run store, Redis broadcaster, staging helpers, and tests.
- `api/prototyping/music/`: YouTube/audio ingestion, Modal allin1 analysis, lyrics lookup, optional R2 publish.
- `api/prototyping/video/`: scene detection, optical-flow motion analysis, impact detection, local CPU and Modal GPU runtimes, R2-aware Modal wrapper.
- `api/prototyping/edit/`: deterministic planner, CLIP index, OpenAI synthesis agent, reference consolidator, timeline schemas/validators, MoviePy renderer, Modal render/index wrappers.
- `api/COMMANDS.md`: command runbook. Prefer updating it when operational instructions change.
- `workers/r2-import-forwarder/`: Cloudflare Worker queue consumer for R2 object-create events. It filters `incoming/collections/` media keys and forwards accepted events to `POST /internal/import-events`.
- `docs/`: older plans/specs and Superpowers design artifacts.
- `.agent/`, `.superpowers/`: agent/process assets, not runtime app code.
- `content/` and `api/prototyping/**/content/`: local scratch/generated media.

## Development Commands

Run backend commands from the repo root unless a command says otherwise:

```bash
python -m pytest api -v
python -m pytest api/test_api_v1.py -v
python -m pytest api/storage -v
python -m pytest api/test_export_options.py -v
python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v
python -m api.main
```

Run frontend commands from `web/`:

```bash
npm run dev
npm run lint
npm run build
npm run start
```

Railway/Railpack uses the repo-root `requirements.txt` and starts with `python -m api.main`. Local prototype development can use `api/requirements.txt`; the heavy Modal audio image uses `api/requirements-modal.txt`.

## Cloud API

`api/main.py` imports `create_app()` from `api/app.py`. `api/app.py` owns FastAPI setup, CORS, temp auth, request/response models, route definitions, and background-task scheduling.

Temporary auth resolves user id from `X-User-Id`, falling back to `ECLYPTE_DEFAULT_USER_ID`. Frontend Clerk integration sends Clerk `user.id` in that header; backend JWT verification is deferred.

Real `/v1/*` calls need R2 env vars:

- `ECLYPTE_R2_ACCOUNT_ID`
- `ECLYPTE_R2_BUCKET`
- `ECLYPTE_R2_ACCESS_KEY_ID`
- `ECLYPTE_R2_SECRET_ACCESS_KEY`
- `ECLYPTE_R2_REGION_NAME`

Optional env vars:

- `DATABASE_URL`: stores run manifests, events, and latest progress in Postgres.
- `REDIS_URL`: publishes non-durable run-update stream messages for the dashboard.
- `ECLYPTE_INTERNAL_PROGRESS_URL` and `ECLYPTE_INTERNAL_PROGRESS_TOKEN`: let Modal workers post progress to `/internal/progress`. The Worker's `ECLYPTE_INTERNAL_TOKEN` secret must match `ECLYPTE_INTERNAL_PROGRESS_TOKEN`; both stay server-side only.
- `ECLYPTE_YOUTUBE_COOKIES_B64` or `ECLYPTE_YOUTUBE_COOKIES`: cookies for the `yt-dlp` YouTube fallback.
- `ECLYPTE_YOUTUBE_VISITOR_DATA` and `ECLYPTE_YOUTUBE_PO_TOKEN`: PO-token path for `pytubefix`.
- `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`: enable review-gated Buffer Instagram publishing from public R2 copies.
- `OPENAI_API_KEY`: enables AI caption generation for publishing packages. `ECLYPTE_CAPTION_MODEL` is optional and defaults to a small GPT-5.4-class model; deterministic fallback captions are used when OpenAI is unavailable.
- `TMDB_READ_ACCESS_TOKEN` or `TMDB_API_KEY`: enable Content Radar TMDb discovery. `ECLYPTE_CONTENT_RADAR_REGION` and `ECLYPTE_CONTENT_RADAR_MAX_PAGES` tune discovery defaults.
- `ECLYPTE_AUTO_IMPORT_MAX_ACTIVE`, `ECLYPTE_AUTO_DRAFT_MAX_ACTIVE`, and `ECLYPTE_AUTO_DRAFT_MAX_DAILY`: cap the auto-import/auto-draft queues.

Routes:

- Health: `GET /healthz`.
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Content Radar: `POST /v1/content-radar/discover`, `GET /v1/content-candidates`, `POST /v1/content-candidates/{candidate_id}/approve`, `POST /v1/content-candidates/{candidate_id}/reject`, `POST /v1/content-candidates/{candidate_id}/mark-imported`.
- Internal: `POST /internal/progress` and `POST /internal/import-events`, each requiring `X-Eclypte-Internal-Token`. `/internal/import-events` accepts Cloudflare R2 object-create payloads and creates `bucket_import` runs.

## Storage Substrate

`api/storage/models.py` defines strict Pydantic models:

- `FileManifest`
- `FileVersionMeta`
- `RunManifest`
- `RunEvent`
- `UploadReservation`
- `SynthesisReferenceRecord`
- `SynthesisPromptVersion`
- `SynthesisPromptState`
- `StoredSynthesisPromptState`
- `ContentProvider`
- `ContentCandidateRecord`
- `PublishingPostRecord`

Artifact kinds are:

- `source_video`
- `song_audio`
- `lyrics`
- `music_analysis`
- `video_analysis`
- `clip_index`
- `timeline`
- `render_output`

`StorageRepository` is the API-facing facade. It writes file/upload metadata to the object store, routes run state through Postgres when configured or R2 JSON otherwise, and publishes Redis updates after durable writes. Redis failures must not break persistence.

Default asset lists hide archived assets and render outputs. Use `kind=render_output` to list render outputs. Archive/restore instead of hard deletion for normal dashboard lifecycle.

## Workflow Orchestration

`api/workflows.py` defines `WorkflowRunner` and `DefaultWorkflowRunner`. Workflow endpoints create a `RunManifest` with `status="running"` and schedule FastAPI background work.

Important workflows:

- `run_music_analysis`: loads audio from R2, calls `eclypte-analysis::analyze_remote`, publishes a `music_analysis` asset.
- `run_youtube_song_import`: downloads/transcodes audio through `api/youtube_download.py`, records `youtube_download_attempt` events, publishes `song_audio`, then runs music analysis.
- `run_video_analysis`: calls `eclypte-video-r2::analyze_r2`, publishes `video_analysis`.
- `run_timeline_plan`: uses agent planning by default, deterministic planning when requested, and publishes `timeline`.
- `run_render`: calls `eclypte-render-r2::render_r2`, publishes `render_output`.
- `run_edit_pipeline`: parent workflow that selects saved assets, ensures missing analysis, plans, renders, and writes child run ids/output refs onto the parent run.
- `run_bucket_import`: normalizes incoming songs to WAV and videos to MP4, publishes managed `song_audio`/`source_video` assets tagged `auto_import` and `collection:{collection_slug}`, runs analysis, and may create one `auto_draft` for a same-collection song/video pair.
- Auto-draft renders tagged `auto_draft` create editable publishing packages, but Buffer queue/schedule remains review-gated and public R2 copies are created only when sending to Buffer.
- `run_content_radar_discovery`: fetches TMDb trending/list candidates, filters to available-now watch providers in the region, and saves `ContentCandidateRecord` review state.
- `run_synthesis_reference_ingest`: downloads/analyzes reference AMVs and records metrics.
- `run_synthesis_consolidation`: consolidates queued/completed references into generated prompt guidance and prompt versions.

Edit child run ids and render output ids are part of the dashboard contract. Preserve keys such as `music_run_id`, `video_run_id`, `timeline_run_id`, `render_run_id`, `render_output_file_id`, and `render_output_version_id`.

## Export Options

`api/export_options.py` owns:

- `reels_9_16`: 1080x1920, fill crop, `crop_focus_x`.
- `youtube_16_9`: 1920x1080, letterbox.
- `audio_start_sec` and `audio_end_sec`.
- `trim_song_analysis()`, which rewrites beats, downbeats, segments, energy, and source duration for the selected audio window.

Backend defaults to YouTube 16:9 when export options are omitted. The dashboard defaults the compose UI to Reels.

## YouTube Import

Use `api/youtube_download.py` for production API imports, not the older prototype script directly. Provider order is intentional:

1. prototype-style `pytubefix` audio stream,
2. configured `pytubefix` PO-token mode,
3. `pytubefix` WEB fallback,
4. `yt-dlp` fallback.

Do not add browser-side media extraction. Diagnose failures from `RunManifest.last_error` and `youtube_download_attempt` run events. Runtime downloader dependencies must be in root `requirements.txt` because Railway installs that file.

## Audio Pipeline

`api/prototyping/music/analysis.py` is the pure analyzer. It produces a song map with tempo, beats, downbeats, 10 Hz normalized energy, structural segments, `schema_version: 1`, and `_sec` timestamps.

`api/prototyping/music/analysis_modal.py` defines Modal app `eclypte-analysis` and `analyze_remote(audio_bytes, filename)`. It owns the heavy allin1/torch/natten image. Keep Modal imports out of `analysis.py`.

`api/prototyping/music/main.py` wires local YouTube download, Modal analysis, lyrics, and optional R2 publishing. `lyrics.py` uses `syncedlyrics`; lyrics are optional and separate from `song_analysis.json`.

Heavy audio landmines:

- allin1 and natten belong in Modal, not local installs.
- natten is pinned because allin1 imports deprecated camelCase ops.
- torch, torchaudio, torchvision, CUDA, and natten versions are coupled.
- missing allin1 transitive imports belong in `api/requirements-modal.txt`.

## Video Pipeline

`api/prototyping/video/analysis.py` is the local CPU orchestrator and must stay Modal-free. It uses:

- `scenes.py`: PySceneDetect scene boundaries, with whole-clip fallback.
- `motion.py`: Farneback optical flow, normalized motion curves, camera movement class, stability, and raw signals.
- `impact.py`: adaptive visual-energy impact/stillness detection.

`analysis_cuda.py` is the GPU orchestrator. It decodes sequentially and resets previous-frame state at scene boundaries so optical flow does not cross cuts.

Modal apps:

- `api/prototyping/video/analysis_modal.py`: volume-based prototype app `eclypte-video`.
- `api/prototyping/video/storage_modal.py`: R2-aware API app `eclypte-video-r2`, function `analyze_r2`.

OpenCV-CUDA has no friendly local wheel path. Keep CUDA/OpenCV build complexity inside Modal unless the task explicitly asks for dependency work.

## Edit Pipeline

`api/prototyping/edit/` takes song analysis, source analysis, audio, and video and produces a timeline or rendered MP4.

Subsystems:

- `patterns/`: pattern catalog and registry. Stable pattern ids are `<layer>.<slug>`.
- `knowledge/`: seed pattern YAML and generated/reference guidance markdown.
- `synthesis/timeline_schema.py`: Pydantic timeline schema.
- `synthesis/validators.py`: contiguity, bounds, and pattern-id validation.
- `synthesis/planner.py`: deterministic planner baseline.
- `synthesis/agent.py`: OpenAI Responses API synthesis loop.
- `synthesis/adapter.py`: converts agent output into renderable timelines, dedupes near-duplicate source timestamps, trims song-duration overshoot, and runs continuity post-processing.
- `index/frames.py`: sequential frame extraction. Do not revert to per-frame `CAP_PROP_POS_MSEC` seeking on long videos.
- `index/embed.py`: CLIP frame/text embeddings.
- `index/index_modal.py` and `index/query_modal.py`: volume-based prototype CLIP apps.
- `index/storage_modal.py`: R2-aware API CLIP app `eclypte-clip-index-r2`, with `build_index_r2` and `query_index_r2`.
- `reference/`: reference AMV download, metrics, ingest, consolidation, and prompt-weight parsing.
- `render/renderer.py`: MoviePy v2 renderer. It should read timeline JSON and media only, not planner internals.
- `render_modal.py`: volume-based prototype renderer, must be invoked from `api/prototyping/`.
- `render_storage_modal.py`: R2-aware API renderer `eclypte-render-r2`.

Agent planning defaults:

- `PlanningMode` is `"agent"` unless explicitly set to `"deterministic"`.
- `synthesis/agent.py` currently uses `MODEL = "gpt-5.4"`, `reasoning_effort="high"`, and `verbosity="low"`.
- Responses API state is carried through `previous_response_id`; do not re-upload full message history each loop.
- Tools are `query_clips(query, top_k)` and `finish_edit(timeline)`.
- Agent mode may create/reuse `clip_index` assets and records `clip_index_file_id`, `clip_index_version_id`, and `synthesis_prompt_version_id`.
- Agent failures should fail visibly; do not silently fall back to deterministic planning.

Rendering notes:

- `render_timeline` depends on timeline JSON, source video, and song audio.
- MoviePy v2 methods include `subclipped`, `with_duration`, `resized`, `concatenate_videoclips(method="compose")`, and `with_audio`.
- Effects/transitions are still mostly stubs/deferred. Avoid promising finished flash/whip/freeze/speed-ramp behavior unless implemented.
- CPU/vCPU count is the current render dial; GPU does not help without a CUDA ffmpeg/NVENC path.

## Frontend

Before changing Next.js code, read relevant docs under `web/node_modules/next/dist/docs/`. This project uses Next.js 16, where conventions may differ from memory. The proxy/middleware file is `web/src/proxy.ts`, not `middleware.ts`.

Frontend architecture:

- `web/src/app/layout.tsx`: fonts and app shell providers.
- `web/src/app/page.tsx`: marketing landing page.
- `web/src/app/pricing/page.tsx`: lightweight pricing page.
- `web/src/app/demo/page.tsx`: marketing demo-reel showcase page.
- `web/src/app/dashboard/layout.tsx`: dashboard shell/sidebar.
- `web/src/app/dashboard/page.tsx`: redirects to `/dashboard/new-edit`.
- `web/src/app/dashboard/new-edit/page.tsx`: compose/edit pipeline UI.
- `web/src/app/dashboard/assets/page.tsx`: upload/import/manage asset library.
- `web/src/app/dashboard/radar/page.tsx`: TMDb-powered available-now movie/TV candidate review with filters and approve/reject/imported actions.
- `web/src/app/dashboard/automation/page.tsx`: auto-import runs, failed normalizations, active/completed auto-draft jobs, and collection filters.
- `web/src/app/dashboard/synthesis/page.tsx`: references and prompt management.
- `web/src/app/dashboard/publish/page.tsx`: Buffer publishing queue with setup diagnostics, render preview, caption editing/regeneration, queue/schedule actions, and posted/error metadata.
- `web/src/app/dashboard/renders/page.tsx`: render outputs and recent render runs.
- `web/src/app/dashboard/settings/page.tsx`: API/user/prompt/YouTube-cookie health.
- `web/src/app/dashboard/dashboardCommon.tsx`: shared dashboard page wrapper.
- `web/src/components/dashboard/sidebar/`: dashboard navigation.
- `web/src/services/eclypteApi.ts`: typed browser API client. Extend this before adding ad hoc fetch calls.

Run streams are newline-delimited JSON. Use `readJsonLineStream()` and `drainJsonLines()` from `eclypteApi.ts`; keep polling fallback logic because Redis may be absent or stale.

The frontend depends on these output keys:

- `music_analysis_file_id`, `music_analysis_version_id`
- `video_analysis_file_id`, `video_analysis_version_id`
- `timeline_file_id`, `timeline_version_id`
- `render_output_file_id`, `render_output_version_id`
- `clip_index_file_id`, `clip_index_version_id`
- `synthesis_prompt_version_id`

Styling uses CSS Modules and the existing dashboard/landing visual language. Shared services and components should stay typed and colocated with their CSS where that pattern already exists.

## Modal Apps

API-facing R2-aware apps:

- `eclypte-analysis::analyze_remote` from `api/prototyping/music/analysis_modal.py`
- `eclypte-video-r2::analyze_r2` from `api/prototyping/video/storage_modal.py`
- `eclypte-clip-index-r2::build_index_r2` and `query_index_r2` from `api/prototyping/edit/index/storage_modal.py`
- `eclypte-render-r2::render_r2` from `api/prototyping/edit/render_storage_modal.py`

Prototype/volume apps:

- `eclypte-video`
- `eclypte-index`
- `eclypte-query`
- `eclypte-edit`

Modal wrappers should use pure local modules through `add_local_python_source()` or explicit storage wrappers. Pure analysis modules should not import Modal.

## Testing Guidance

- Backend behavior changes: run focused tests near the changed module, then `python -m pytest api -v` when feasible.
- API contract changes: run `python -m pytest api/test_api_v1.py -v` and update `web/src/services/eclypteApi.ts`.
- Storage changes: run `python -m pytest api/storage -v`.
- Publishing changes: run `python -m pytest api/test_publishing.py -v`.
- Content Radar changes: run `python -m pytest api/test_content_radar.py -v`.
- Export option changes: run `python -m pytest api/test_export_options.py -v`.
- Synthesis/index changes: run `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v`.
- Frontend changes: from `web/`, run `npm run lint` and `npm run build`.

`pytest.ini` disables pytest's cache provider and sets temp-path retention to zero to reduce `.pytest*` artifacts.

## Working Rules

- Prefer existing repository boundaries and helpers over new parallel abstractions.
- Keep storage, API, frontend client, and dashboard UI in sync when contracts change.
- Do not commit secrets, `.env` files, cookies, Modal tokens, or OpenAI keys.
- Do not install heavy ML stacks locally unless the task is explicitly dependency work.
- Keep `AGENTS.md`, `web/AGENTS.md`, `api/COMMANDS.md`, and this file reconciled when architecture or commands change.
- Preserve unrelated local changes. At the time this guide was refreshed, `README.md` already had local modifications and was intentionally left alone.
