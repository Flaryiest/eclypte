# Eclypte Agent Guide

Eclypte is an AMV creator monorepo. The production-facing path is a Next.js dashboard that talks to a FastAPI control plane; heavy media work stays in Modal workers, and durable artifacts live in Cloudflare R2.

## Repository Map

- `web/`: Next.js 16, React 19, TypeScript App Router frontend. See `web/AGENTS.md` for framework-specific warnings and dashboard notes.
- `api/app.py`: FastAPI app factory, CORS, temporary `X-User-Id` auth, Pydantic request/response models, and `/v1/*` routes.
- `api/workflows.py`: Railway-side background orchestration. It creates run manifests, reuses or schedules analyses, calls Modal wrappers, plans timelines, renders outputs, and records progress.
- `api/export_options.py`: shared export-option resolver for 9:16 Reels, 16:9 YouTube, audio trimming, and crop focus. Keep API, planner, adapter, and renderer behavior routed through this helper.
- `api/storage/`: canonical persistence layer for artifacts, uploads, runs, prompt versions, references, R2 object access, optional Postgres run storage, and optional Redis run streaming.
- `api/prototyping/music/`: YouTube/audio ingestion, Modal-backed allin1 music analysis, lyrics lookup, and optional R2 publishing.
- `api/prototyping/video/`: scene, motion, and impact analysis with local CPU and Modal GPU paths.
- `api/prototyping/edit/`: deterministic and agentic timeline planning, CLIP index build/query, reference ingestion/consolidation, timeline schemas, validation, and MoviePy/Modal rendering.
- `api/prototyping/progress_events.py`: Modal-worker progress emitter. Prefer internal API progress writes when configured; otherwise it can append progress events through R2 config.
- `api/youtube_download.py`: backend-side YouTube download provider chain used by `/v1/music/youtube-imports`.
- `docs/`: older plans/specs and Superpowers design artifacts.
- `.agent/`: Antigravity/Superpowers profile assets; not application runtime code.
- `content/`: local media/output scratch area.

## Current Product Flow

- Users upload WAV songs and MP4 source videos from the dashboard through presigned R2 PUT URLs.
- Assets are stored as `FileManifest` plus immutable `FileVersionMeta` records.
- Workflow endpoints return `RunManifest` records immediately, then `DefaultWorkflowRunner` performs background work.
- Music analysis, video analysis, timeline planning, rendering, YouTube import, edit pipelines, and synthesis consolidation all surface status through run manifests/events.
- `POST /v1/edits` is the higher-level dashboard pipeline: select saved audio/video, ensure missing analysis, plan a timeline, render an MP4, then expose a signed download URL.
- Edit jobs can be listed, canceled, archived/deleted, and redone. Asset records can be archived and restored; default asset lists hide archived records and render outputs unless explicitly requested.
- Export options flow from the dashboard into timeline planning and rendering: `reels_9_16` renders 1080x1920 with fill crop and `crop_focus_x`; `youtube_16_9` renders 1920x1080 with letterbox. Audio trim fields are applied by trimming the music analysis and setting the timeline audio offset.
- Agent timeline planning defaults to `planning_mode: "agent"` and may create or reuse a `clip_index` asset, load the active synthesis prompt, call OpenAI-backed synthesis, validate coverage, and publish a timeline artifact. Use `"deterministic"` only when explicitly opting out.

## Frontend Notes

- The frontend uses Next.js 16. Read the local Next docs in `web/node_modules/next/dist/docs/` before changing Next APIs or conventions.
- App Router pages live under `web/src/app/`.
- Dashboard routes are product code, not placeholders:
  - `/dashboard/new-edit`: saved-asset selection, export controls, edit pipeline creation, run streaming/poll fallback, stage progress, preview/download, cancel/delete/redo.
  - `/dashboard/assets`: direct R2 uploads, upload cleanup, asset library with archived items, manual analysis, YouTube song import, preview/download, delete/restore.
  - `/dashboard/synthesis`: reference queueing, consolidation, active prompt versions.
  - `/dashboard/renders`: render-output library plus recent render runs.
  - `/dashboard/settings`: API/user/prompt/YouTube-cookie health details.
- `web/src/services/eclypteApi.ts` is the typed browser client for the FastAPI v1 surface, including edit-job lifecycle, run streaming, asset archive/restore, export options, and synthesis APIs. Prefer extending it over ad hoc `fetch` calls in pages.
- `NEXT_PUBLIC_ECLYPTE_API_BASE_URL` controls the API base and defaults to `http://127.0.0.1:8000`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`; backend Clerk JWT verification is intentionally deferred.

## Backend Notes

- `api/main.py` exposes `api.app.create_app()` for local and Railway startup.
- `railpack.json` starts the service with `python -m api.main`; root `requirements.txt` is intentionally self-contained for Railpack.
- Real `/v1/*` calls need R2 env vars. Optional `DATABASE_URL` moves runs/events/progress to Postgres; optional `REDIS_URL` enables realtime dashboard streams but is not durable state.
- Run and artifact models are strict Pydantic models. Preserve `schema_version: 1`, `_sec` timestamp naming, and existing `RunManifest.outputs` keys unless a coordinated migration is part of the task.
- The `/v1/runs/stream` and `/v1/runs/{run_id}/stream` endpoints stream newline-delimited JSON from Redis when available; callers must keep polling fallbacks because Redis is not durable and may be absent.
- `/internal/progress` requires `X-Eclypte-Internal-Token` and records latest stage progress for long Modal work. Do not expose this token to the browser.
- Browser uploads only accept WAV audio and MP4 video in the current v1 path.
- YouTube downloads stay backend-side. Surface `RunManifest.last_error` and `youtube_download_attempt` events instead of adding browser-side extraction.
- Do not commit secrets, exported cookies, Modal tokens, or `.env` files.

## Modal And ML Constraints

- Do not install the heavy ML stack locally unless the task explicitly asks for dependency work. Audio allin1, torch, natten, and related packages belong in Modal images.
- `api/requirements.txt` is for local backend/prototype development; `api/requirements-modal.txt` is for the heavy Modal image; root `requirements.txt` is for Railway.
- Keep pure analysis modules free of Modal imports. Modal wrappers should call pure functions through `add_local_python_source()` or explicit storage wrappers.
- R2-aware Modal wrappers used by the API include:
  - `api/prototyping/video/storage_modal.py`
  - `api/prototyping/edit/index/storage_modal.py`
  - `api/prototyping/edit/render_storage_modal.py`

## Commands

- Backend broad check: `python -m pytest api -v`
- Focused API check: `python -m pytest api/test_api_v1.py -v`
- Storage check: `python -m pytest api/storage -v`
- Export option check: `python -m pytest api/test_export_options.py -v`
- Edit synthesis/index checks: `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v`
- Run API locally: `python -m api.main`
- Frontend dev: from `web/`, `npm run dev`
- Frontend verification: from `web/`, `npm run lint` and `npm run build`
- Canonical runbook with PowerShell/bash examples: `api/COMMANDS.md`

## Working Conventions

- Prefer existing repository boundaries and typed helpers over new parallel abstractions.
- Add or update tests near the changed module when behavior changes.
- Keep frontend visual changes aligned with the current landing/dashboard design language.
- When changing API contracts, update both `api/app.py` models/routes and `web/src/services/eclypteApi.ts`.
- Treat `web/AGENTS.md`, `api/COMMANDS.md`, and root `CLAUDE.md` as living context; reconcile them if your change makes them stale.
