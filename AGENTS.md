# Eclypte Agent Guide

Eclypte is an AMV creator monorepo. The product path is a Next.js dashboard backed by a FastAPI control plane. Heavy media and ML work runs in Modal, durable files and metadata live in Cloudflare R2, optional Postgres stores run state/progress, and optional Redis provides non-durable realtime dashboard updates.

## Repository Map

- `web/`: Next.js 16.2.3, React 19.2, TypeScript App Router frontend. Read `web/AGENTS.md` before changing frontend code.
- `web/src/app/`: marketing pages and dashboard routes.
- `web/src/services/eclypteApi.ts`: typed browser client for the FastAPI v1 API, including uploads, assets, edit jobs, run streams, download URLs, export options, and synthesis APIs.
- `web/src/components/`: shared landing/dashboard components with co-located CSS Modules.
- `api/app.py`: FastAPI app factory, CORS, temporary `X-User-Id` auth, Pydantic request/response models, and `/v1/*` plus `/internal/progress` routes.
- `api/workflows.py`: Railway-side background orchestration. It creates parent/child run manifests, reuses completed analysis, calls Modal wrappers, plans timelines, renders outputs, records events/progress, and handles edit-job lifecycle.
- `api/content_radar.py`: TMDb-backed movie/TV discovery for new/trending available-now candidates, including watch-provider filtering and scoring.
- `api/export_options.py`: canonical resolver for Reels 9:16, YouTube 16:9, audio trims, output size/crop, and crop focus. Keep API, planner, adapter, and renderer behavior routed through this helper.
- `api/publishing.py`: review-gated Buffer publishing helper for Instagram Reels, including caption generation/fallback, public R2 publish copies, Buffer GraphQL payloads, and channel diagnostics.
- `api/storage/`: canonical persistence layer for file manifests, file versions, uploads, runs/events/progress, synthesis references, prompt versions, R2 access, optional Postgres run storage, and optional Redis run broadcasting.
- `api/youtube_download.py`: backend-side YouTube download provider chain used by `/v1/music/youtube-imports`.
- `api/prototyping/music/`: audio ingestion, Modal-backed allin1 music analysis, lyrics lookup, and optional R2 publishing.
- `api/prototyping/video/`: scene, motion, impact, local CPU analysis, Modal GPU analysis, and R2-aware Modal video analysis.
- `api/prototyping/edit/`: deterministic and agentic timeline planning, CLIP index build/query, reference ingestion/consolidation, timeline schemas/validation, MoviePy rendering, and R2-aware Modal render/index wrappers.
- `api/prototyping/progress_events.py`: progress emitter used inside Modal workers. Prefer internal API progress writes when configured; otherwise it can append events through R2 config.
- `api/COMMANDS.md`: command runbook for local API, Modal, R2, timeline planning, rendering, and tests.
- `workers/r2-import-forwarder/`: Cloudflare Worker Queue consumer for R2 object-create events. It filters `incoming/collections/` media keys and forwards accepted events to `POST /internal/import-events`.
- `docs/`: older plans/specs and Superpowers design artifacts.
- `.agent/` and `.superpowers/`: agent profile/process assets, not application runtime code.
- `content/`, `api/prototyping/**/content/`, `youtube-worker-tmp/`, and pytest temp dirs: local scratch/generated media areas.

## Product Flow

- Users upload WAV audio and MP4 source video from the dashboard through presigned R2 PUT URLs.
- Private R2 automation also accepts media dropped into `incoming/collections/{collection_slug}/songs/` and `incoming/collections/{collection_slug}/videos/`. Cloudflare R2 notifications flow through the Worker and create `bucket_import` runs.
- Assets are stored as strict `FileManifest` and immutable `FileVersionMeta` records. Default asset lists hide archived files and render outputs unless requested.
- Workflow endpoints return `RunManifest` records immediately; `DefaultWorkflowRunner` continues work in FastAPI background tasks.
- Content Radar discovers TMDb movie/TV candidates from trending/list endpoints, filters them to available-now watch providers in the selected region, stores review state in R2, and leaves acquisition/import to the existing R2 lane.
- Content Radar is deployed on `main` as commit `2771717 Add TMDb content radar`. A production smoke on 2026-05-15 created `run_387afc91e2d1`, completed `content_radar_discovery`, and saved 77 US available-now candidates for test user `radar_verify_20260515`.
- Music analysis, video analysis, YouTube import, content radar discovery, bucket import, auto-draft, timeline planning, rendering, edit pipelines, and synthesis consolidation all surface status through run manifests and events.
- `POST /v1/edits` is the dashboard pipeline: select saved audio/video, ensure missing analysis, plan a timeline, render an MP4, and expose a signed download URL.
- `bucket_import` normalizes incoming songs to WAV and videos to MP4, publishes managed `song_audio` or `source_video` assets tagged `auto_import` and `collection:{collection_slug}`, runs analysis, and may create one `auto_draft` for a same-collection song/video pair.
- `auto_draft` defaults to Reels 9:16, clamps its 60-second target to analyzed song duration, falls back from agent timeline planning to deterministic planning when the agent timeline is too short, renders normally, tags outputs `auto_draft` and `collection:{collection_slug}`, and creates a review-gated publishing package.
- Buffer publishing is review-gated. `/dashboard/publish` lets users edit captions/hashtags/notes, then queue or schedule an approved render through Buffer. Public R2 copies under `public/publishing/{user_id}/{post_id}/` are created only when sending to Buffer.
- Edit jobs can be listed, canceled, archived/deleted, and redone. Child run ids are stored on the parent edit run outputs.
- Timeline planning defaults to `planning_mode: "agent"`. Agent mode can create or reuse a `clip_index` asset, load the active synthesis prompt, call the OpenAI-backed synthesis loop, validate coverage, and publish a timeline artifact. Use `"deterministic"` only when explicitly opting out. The synthesis loop (`api/prototyping/edit/synthesis/agent.py`) runs OpenAI `gpt-5.4` with `reasoning_effort="high"` and `verbosity="low"`, and must fail visibly rather than silently fall back to deterministic planning.
- Export options flow from the dashboard into timeline planning and rendering. `reels_9_16` renders 1080x1920 with fill crop and `crop_focus_x`; `youtube_16_9` renders 1920x1080 with letterbox. Audio trim fields trim the music analysis and set the timeline audio offset.
- Run streams are newline-delimited JSON from Redis when available, not SSE. Frontend callers must keep polling fallbacks because Redis is optional and not durable state.

## API Surface

- Health: `GET /healthz`.
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Content Radar: `POST /v1/content-radar/discover`, `GET /v1/content-candidates`, `POST /v1/content-candidates/{candidate_id}/approve`, `POST /v1/content-candidates/{candidate_id}/reject`, `POST /v1/content-candidates/{candidate_id}/mark-imported`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Internal worker progress: `POST /internal/progress`, requiring `X-Eclypte-Internal-Token`. Do not expose this token to the browser.
- Internal R2 import events: `POST /internal/import-events`, requiring `X-Eclypte-Internal-Token`. It accepts Cloudflare R2 object-create payloads and creates `bucket_import` runs for supported incoming collection media.

## Frontend Notes

- This is Next.js 16.2.3. Read local docs in `web/node_modules/next/dist/docs/` before changing Next APIs, routing conventions, proxy/middleware, cache behavior, server actions, metadata, `headers()`, `cookies()`, or `params`.
- Middleware/proxy lives at `web/src/proxy.ts`, following the Next.js 16 renamed convention.
- App Router pages live under `web/src/app/`.
- Marketing routes are `/` (landing), `/pricing` (lightweight), and `/demo` (demo-reel showcase).
- Dashboard routes are product code:
  - `/dashboard/new-edit`: saved asset selection, export controls, crop preview, edit creation, run streaming/poll fallback, stage progress, preview/download, cancel/delete/redo.
  - `/dashboard/assets`: direct R2 uploads, cleanup, asset library with archived items, manual analysis, YouTube song import, preview/download, delete/restore.
  - `/dashboard/radar`: TMDb-powered available-now movie/TV candidate review with filters and approve/reject/imported actions.
  - `/dashboard/automation`: import runs, failed normalizations, active draft jobs, completed auto-drafts, previews/downloads, and collection filters.
  - `/dashboard/publish`: review-gated Instagram Reels publishing queue for Buffer, including setup diagnostics, caption editing/regeneration, queue/schedule actions, and posted/error metadata.
  - `/dashboard/synthesis`: reference queueing, consolidation, active prompt viewing/editing/version activation.
  - `/dashboard/renders`: render-output library and recent render runs.
  - `/dashboard/settings`: API/user/prompt/YouTube-cookie health details.
- `NEXT_PUBLIC_ECLYPTE_API_BASE_URL` controls the API base and defaults to `http://127.0.0.1:8000`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`; backend Clerk JWT verification is intentionally deferred.
- Browser uploads only accept WAV audio and MP4 video in the current v1 path.
- Prefer extending `web/src/services/eclypteApi.ts` over ad hoc browser `fetch` calls.
- Keep visual work aligned with the existing landing/dashboard design language. The dashboard is utilitarian product UI, not a placeholder.

## Backend Notes

- `api/main.py` exposes `api.app.create_app()` for local and Railway startup.
- `railpack.json` starts the service with `python -m api.main` on Python 3.13; root `requirements.txt` is intentionally self-contained for Railpack/Railway.
- Real `/v1/*` calls require R2 env vars. Optional `DATABASE_URL` moves runs/events/progress to Postgres. Optional `REDIS_URL` enables realtime dashboard streams.
- Content Radar discovery requires `TMDB_READ_ACCESS_TOKEN` or `TMDB_API_KEY`; Railway production had TMDb credentials configured and verified on 2026-05-15. `ECLYPTE_CONTENT_RADAR_REGION` and `ECLYPTE_CONTENT_RADAR_MAX_PAGES` tune workflow defaults.
- Buffer publishing requires `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`. AI captions use `OPENAI_API_KEY` and optional `ECLYPTE_CAPTION_MODEL`; if unavailable or invalid, deterministic fallback captions are stored with `caption_source="fallback"`.
- The Worker secret `ECLYPTE_INTERNAL_TOKEN` must match the API service's `ECLYPTE_INTERNAL_PROGRESS_TOKEN`. Keep both server-side only.
- Auto-import queue caps are env-configurable: `ECLYPTE_AUTO_IMPORT_MAX_ACTIVE`, `ECLYPTE_AUTO_DRAFT_MAX_ACTIVE`, and `ECLYPTE_AUTO_DRAFT_MAX_DAILY`.
- Run and artifact models are strict Pydantic models. Preserve `schema_version: 1`, `_sec` timestamp naming, and existing `RunManifest.outputs` keys unless a coordinated migration is part of the task.
- Storage artifact kinds are `source_video`, `song_audio`, `lyrics`, `music_analysis`, `video_analysis`, `clip_index`, `timeline`, and `render_output`.
- Strict record models in `api/storage/models.py` include `FileManifest`, `FileVersionMeta`, `RunManifest`, `RunEvent`, `UploadReservation`, `SynthesisReferenceRecord`, `SynthesisPromptVersion`/`SynthesisPromptState`, `ContentProvider`, `ContentCandidateRecord`, and `PublishingPostRecord`.
- YouTube downloads stay backend-side. Surface `RunManifest.last_error` and `youtube_download_attempt` events instead of adding browser-side extraction.
- Do not commit secrets, exported cookies, Modal tokens, API keys, or `.env` files.

## Modal And ML Constraints

- Do not install the heavy ML stack locally unless the task explicitly asks for dependency work. Audio allin1, torch, natten, CLIP, OpenCV-CUDA, and related packages belong in Modal images.
- `api/requirements.txt` is for local backend/prototype development; `api/requirements-modal.txt` is for the heavy Modal audio image; root `requirements.txt` is for Railway.
- Keep pure analysis modules free of Modal imports. Modal wrappers should call pure functions through `add_local_python_source()` or explicit storage wrappers.
- R2-aware Modal apps used by the API include `eclypte-video-r2` (`api/prototyping/video/storage_modal.py`), `eclypte-clip-index-r2` (`api/prototyping/edit/index/storage_modal.py`), and `eclypte-render-r2` (`api/prototyping/edit/render_storage_modal.py`).
- Volume-based prototype Modal apps still exist for local CLI workflows: `eclypte-analysis`, `eclypte-video`, `eclypte-index`, `eclypte-query`, and `eclypte-edit`.

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
- Worker verification: from `workers/r2-import-forwarder/`, `npm test`
- Worker deploy: from `workers/r2-import-forwarder/`, `npm run deploy`
- R2 notification check: from `workers/r2-import-forwarder/`, `npx wrangler r2 bucket notification list eclypte`
- Content Radar production smoke: `POST https://api-production-8fb8.up.railway.app/v1/content-radar/discover` with `X-User-Id` and JSON `{"region":"US","max_pages":1}`, then poll `/v1/runs/{run_id}` and list `/v1/content-candidates`.
- Canonical PowerShell/bash runbook: `api/COMMANDS.md`

## Working Conventions

- Prefer existing repository boundaries and typed helpers over new parallel abstractions.
- Add or update tests near the changed module when behavior changes.
- When changing API contracts, update both `api/app.py` models/routes and `web/src/services/eclypteApi.ts`.
- Keep API behavior, planner behavior, and renderer behavior aligned through `api/export_options.py`.
- Keep acquisition/import private and lawful at the code boundary: do not add scraper, DRM bypass, or unauthorized downloader paths. Public publishing must stay review-gated unless a separate postability gate is explicitly designed.
- When changing auto-import or auto-draft behavior, update Worker/API tests and smoke-test with real-ish media. Synthetic tones can fail music analysis because allin1 may return no BPM.
- Treat `web/AGENTS.md`, `api/COMMANDS.md`, and root `CLAUDE.md` as living context; reconcile them if your change makes them stale.
- Preserve user work in the tree. Do not revert unrelated local changes.
