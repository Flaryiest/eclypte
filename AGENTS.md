# Eclypte Agent Guide

Eclypte is an AMV creator monorepo. The product path is a Next.js dashboard backed by a FastAPI control plane. Heavy media and ML work runs in Modal, durable files and metadata live in Cloudflare R2, optional Postgres stores run state/progress, and optional Redis provides non-durable realtime dashboard updates.

## Repository Map

- `web/`: Next.js 16.2.3, React 19.2, TypeScript App Router frontend. Read `web/AGENTS.md` before changing frontend code.
- `web/src/app/`: marketing pages and dashboard routes.
- `web/src/services/eclypteApi.ts`: typed browser client for the FastAPI v1 API, including uploads, assets, edit jobs, run streams, download URLs, export options, synthesis, and publishing APIs.
- `web/src/components/`: shared landing/dashboard components with co-located CSS Modules.
- `api/app.py`: FastAPI app factory, CORS, temporary `X-User-Id` auth, Pydantic request/response models, and `/v1/*` plus `/internal/progress` routes.
- `api/workflows.py`: Railway-side background orchestration. It creates parent/child run manifests, reuses completed analysis, calls Modal wrappers, plans timelines, renders outputs, records events/progress, and handles edit-job lifecycle.
- `api/export_options.py`: canonical resolver for Reels 9:16, YouTube 16:9, audio trims, output size/crop, and crop focus. Keep API, planner, adapter, and renderer behavior routed through this helper.
- `api/publishing.py`: review-gated Buffer publishing for Instagram Reels — Gen-Z-voiced caption generation/fallback, public R2 publish copies, Buffer GraphQL payloads (declares the Instagram `reel` post type), channel diagnostics, and post-status refresh that back-fills the live permalink from Buffer's `externalLink`.
- `api/storage/`: canonical persistence layer for file manifests, file versions, uploads, runs/events/progress, synthesis references, prompt versions, R2 access, optional Postgres run storage, and optional Redis run broadcasting.
- `api/youtube_download.py`: backend-side YouTube download provider chain used by `/v1/music/youtube-imports`.
- `api/prototyping/music/`: audio ingestion, Modal-backed allin1 music analysis, lyrics lookup, and optional R2 publishing.
- `api/prototyping/video/`: scene, motion, impact, local CPU analysis, Modal GPU analysis, and R2-aware Modal video analysis.
- `api/prototyping/edit/`: deterministic and agentic timeline planning, CLIP index build/query, reference ingestion/consolidation, timeline schemas/validation, MoviePy rendering (MP4 + poster frame), and R2-aware Modal render/index wrappers.
- `api/prototyping/progress_events.py`: progress emitter used inside Modal workers. Prefer internal API progress writes when configured; otherwise it can append events through R2 config.
- `api/COMMANDS.md`: command runbook for local API, Modal, R2, timeline planning, rendering, and tests.
- `docs/`: older plans/specs and Superpowers design artifacts.
- `.agent/` and `.superpowers/`: agent profile/process assets, not application runtime code.
- `content/`, `api/prototyping/**/content/`, `youtube-worker-tmp/`, and pytest temp dirs: local scratch/generated media areas.

## Product Flow

- Users upload audio (WAV, or any common format such as MP3/M4A/FLAC auto-converted to WAV server-side) and MP4 source video from the dashboard through presigned R2 PUT URLs.
- Assets are stored as strict `FileManifest` and immutable `FileVersionMeta` records. Default asset lists hide archived files, render outputs, and render posters unless requested.
- Workflow endpoints return `RunManifest` records immediately; `DefaultWorkflowRunner` continues work in FastAPI background tasks.
- Music analysis, video analysis, YouTube import, timeline planning, rendering, edit pipelines, and synthesis consolidation all surface status through run manifests and events.
- `POST /v1/edits` is the dashboard pipeline: select saved audio/video, ensure missing analysis, plan a timeline, render an MP4, and expose a signed download URL.
- Each render publishes both a `render_output` MP4 and a `render_poster` JPEG thumbnail; the dashboard shows the poster instantly and lazy-loads the MP4 on play. Edit `progress_percent` is weighted by typical stage duration and the render stage fills from real encode progress.
- Buffer publishing is review-gated. `/dashboard/publish` lets users edit captions/hashtags/notes, then queue or schedule an approved render through Buffer as an Instagram Reel. Public R2 copies under `public/publishing/{user_id}/{post_id}/` are created only when sending to Buffer; the page polls Buffer once on load to back-fill the live permalink when it is missing.
- Edit jobs can be listed, canceled, archived/deleted, and redone. Child run ids are stored on the parent edit run outputs.
- Timeline planning defaults to `planning_mode: "agent"`. Agent mode can create or reuse a `clip_index` asset, load the active synthesis prompt, call the OpenAI-backed synthesis loop, validate coverage, and publish a timeline artifact. Use `"deterministic"` only when explicitly opting out. The synthesis loop (`api/prototyping/edit/synthesis/agent.py`) runs OpenAI `gpt-5.5` with `reasoning_effort="high"` and `verbosity="low"`, and must fail visibly rather than silently fall back to deterministic planning.
- Both planning paths span the full source start→end regardless of song length, so trimmed/short edits still cover the whole film. The agent is given the source duration and instructed (via per-run user content, independent of the active prompt) to traverse the entire source; the deterministic planner maps each shot's song-progress fraction to a source-position window. This is guidance, not hard enforcement — the agent may still dwell on standout moments.
- Export options flow from the dashboard into timeline planning and rendering. `reels_9_16` renders 1080x1920 with fill crop and `crop_focus_x`; `youtube_16_9` renders 1920x1080 with letterbox. Audio trim fields trim the music analysis and set the timeline audio offset.
- Run streams are newline-delimited JSON from Redis when available, not SSE. Frontend callers must keep polling fallbacks because Redis is optional and not durable state.

## API Surface

- Health: `GET /healthz` (also reports non-secret YouTube-cookie, realtime/Redis, and Modal worker-progress configuration booleans).
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/music/conversions`, `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer`, `POST /v1/publishing/posts/{post_id}/refresh-status`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Internal worker progress: `POST /internal/progress`, requiring `X-Eclypte-Internal-Token`. Do not expose this token to the browser.

## Frontend Notes

- This is Next.js 16.2.3. Read local docs in `web/node_modules/next/dist/docs/` before changing Next APIs, routing conventions, proxy/middleware, cache behavior, server actions, metadata, `headers()`, `cookies()`, or `params`.
- Middleware/proxy lives at `web/src/proxy.ts`, following the Next.js 16 renamed convention.
- App Router pages live under `web/src/app/`.
- Marketing routes are `/` (landing), `/pricing` (three-tier pricing + FAQ), and `/demo` ("Screening Room" demo with poster-first lazy video; `web/src/components/demo/demoPlayer.tsx`).
- Dashboard routes are product code:
  - `/dashboard/new-edit`: saved asset selection, export controls, crop preview, edit creation, run streaming/poll fallback, stage progress, preview/download, cancel/delete/redo.
  - `/dashboard/assets`: direct R2 uploads, cleanup, asset library with archived items, manual analysis, YouTube song import, preview/download, delete/restore.
  - `/dashboard/publish`: review-gated Instagram Reels publishing queue for Buffer, including setup diagnostics, caption editing/regeneration, queue/schedule actions, posted/error metadata, and a post-status refresh that polls Buffer once for the live permalink.
  - `/dashboard/synthesis`: reference queueing, consolidation, active prompt viewing/editing/version activation.
  - `/dashboard/renders`: render-output library and recent render runs.
  - `/dashboard/settings`: API/user/prompt/YouTube-cookie health plus realtime (Redis) and worker-progress status.
- `NEXT_PUBLIC_ECLYPTE_API_BASE_URL` controls the API base and defaults to `http://127.0.0.1:8000`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`; backend Clerk JWT verification is intentionally deferred.
- Browser audio uploads accept WAV or any common audio format (MP3/M4A/AAC/FLAC/OGG), with non-WAV audio auto-converted to WAV server-side via `POST /v1/music/conversions`; video uploads are MP4-only.
- Prefer extending `web/src/services/eclypteApi.ts` over ad hoc browser `fetch` calls.
- Keep visual work aligned with the existing landing/dashboard design language. The dashboard is utilitarian product UI, not a placeholder.

## Backend Notes

- `api/main.py` exposes `api.app.create_app()` for local and Railway startup.
- `railpack.json` starts the service with `python -m api.main` on Python 3.13; root `requirements.txt` is intentionally self-contained for Railpack/Railway.
- Real `/v1/*` calls require R2 env vars. Optional `DATABASE_URL` moves runs/events/progress to Postgres. Optional `REDIS_URL` enables realtime dashboard streams.
- Buffer publishing requires `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`. AI captions use `OPENAI_API_KEY` and optional `ECLYPTE_CAPTION_MODEL`; if unavailable or invalid, deterministic fallback captions are stored with `caption_source="fallback"`.
- `ECLYPTE_INTERNAL_PROGRESS_TOKEN` gates `/internal/progress`; Modal workers must send a matching `X-Eclypte-Internal-Token`. Keep it server-side only.
- Run and artifact models are strict Pydantic models. Preserve `schema_version: 1`, `_sec` timestamp naming, and existing `RunManifest.outputs` keys unless a coordinated migration is part of the task.
- Storage artifact kinds are `source_video`, `song_audio`, `lyrics`, `music_analysis`, `video_analysis`, `clip_index`, `timeline`, `render_output`, and `render_poster`.
- Strict record models in `api/storage/models.py` include `FileManifest`, `FileVersionMeta`, `RunManifest`, `RunEvent`, `UploadReservation`, `SynthesisReferenceRecord`, `SynthesisPromptVersion`/`SynthesisPromptState`, and `PublishingPostRecord`.
- YouTube downloads stay backend-side. Surface `RunManifest.last_error` and `youtube_download_attempt` events instead of adding browser-side extraction.
- Do not commit secrets, exported cookies, Modal tokens, API keys, or `.env` files.

## Modal And ML Constraints

- Do not install the heavy ML stack locally unless the task explicitly asks for dependency work. Audio allin1, torch, natten, CLIP, OpenCV-CUDA, and related packages belong in Modal images.
- `api/requirements.txt` is for local backend/prototype development; `api/requirements-modal.txt` is for the heavy Modal audio image; root `requirements.txt` is for Railway.
- Keep pure analysis modules free of Modal imports. Modal wrappers should call pure functions through `add_local_python_source()` or explicit storage wrappers.
- R2-aware Modal apps used by the API include `eclypte-video-r2` (`api/prototyping/video/storage_modal.py`), `eclypte-clip-index-r2` (`api/prototyping/edit/index/storage_modal.py`), and `eclypte-render-r2` (`api/prototyping/edit/render_storage_modal.py`).
- `eclypte-analysis` (`api/prototyping/music/analysis_modal.py`) and `eclypte-video` (`api/prototyping/video/analysis_modal.py`) are non-R2 Modal apps used in production by music analysis and synthesis reference ingest, respectively.

## Commands

- Backend broad check: `python -m pytest api -v`
- Focused API check: `python -m pytest api/test_api_v1.py -v`
- Storage check: `python -m pytest api/storage -v`
- Export option check: `python -m pytest api/test_export_options.py -v`
- Edit synthesis/index checks: `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v`
- Publishing checks: `python -m pytest api/test_publishing.py -v`
- Run API locally: `python -m api.main`
- Frontend dev: from `web/`, `npm run dev`
- Frontend verification: from `web/`, `npm run lint` and `npm run build`
- Canonical PowerShell/bash runbook: `api/COMMANDS.md`

## Working Conventions

- Prefer existing repository boundaries and typed helpers over new parallel abstractions.
- Add or update tests near the changed module when behavior changes.
- When changing API contracts, update both `api/app.py` models/routes and `web/src/services/eclypteApi.ts`.
- Keep API behavior, planner behavior, and renderer behavior aligned through `api/export_options.py`.
- Keep acquisition/import private and lawful at the code boundary: do not add scraper, DRM bypass, or unauthorized downloader paths. Public publishing must stay review-gated unless a separate postability gate is explicitly designed.
- Treat `web/AGENTS.md`, `api/COMMANDS.md`, and root `CLAUDE.md` as living context; reconcile them if your change makes them stale.
- Preserve user work in the tree. Do not revert unrelated local changes.
