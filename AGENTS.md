# Eclypte Agent Guide

Eclypte is an AMV creator monorepo. The product path is a Next.js dashboard backed by a FastAPI control plane. Heavy media and ML work runs in Modal, durable files and metadata live in Cloudflare R2, optional Postgres stores run state/progress, and optional Redis provides non-durable realtime dashboard updates.

## Repository Map

- `web/`: Next.js 16.2.3, React 19.2, TypeScript App Router frontend. Read `web/AGENTS.md` before changing frontend code.
- `web/src/app/`: marketing pages and dashboard routes.
- `web/src/services/eclypteApi.ts`: typed browser client for the FastAPI v1 API, including uploads, assets, edit jobs, run streams, download URLs, export options, synthesis, and publishing APIs.
- `web/src/components/`: shared landing/dashboard components with co-located CSS Modules.
- `api/app.py`: FastAPI app factory, CORS, temporary `X-User-Id` auth, Pydantic request/response models, and `/v1/*` plus `/internal/progress` routes.
- `api/workflows.py`: Railway-side background orchestration. It creates parent/child run manifests, reuses completed analysis, calls Modal wrappers, plans timelines, renders outputs, records events/progress, and handles edit-job lifecycle.
- `api/export_options.py`: canonical resolver for Reels 9:16, YouTube 16:9, audio trims, output size/crop, and crop focus. Keep API, adapter, and renderer behavior routed through this helper.
- `api/publishing.py`: review-gated Buffer publishing for Instagram Reels — Gen-Z-voiced caption generation/fallback (fed the source movie/anime + song names resolved from the render's run lineage and persisted on the post as `source_name`/`song_name`, producing context-relevant AI hashtags), public R2 publish copies, Buffer GraphQL payloads (declares the Instagram `reel` post type), channel diagnostics, and post-status refresh (`apply_buffer_status`) that marks a post `published` as soon as Buffer reports it sent (`sentAt`/sent status) and independently back-fills the permalink from `externalLink` when it appears.
- `api/autopilot.py`: review-gated autopilot tick state machine — advances a per-user content queue (song import → (analyze if needed) → cinematic 9:16 Reels edit with an energy-ranked ~20–30s trim window (≈25s target), section-anchored windows starting ~5s early (`CHORUS_LEAD_IN_SEC`) to capture the build-in → auto-created publishing package awaiting approval), with combo dedupe, a daily target, and a 3-failure halt. Songs lacking a music analysis are analyzed first (`analyzing` state) so the trim window is always energy-ranked, never the full song. Runs via the env-gated FastAPI lifespan loop (`ECLYPTE_AUTOPILOT=1`) or `POST /v1/autopilot/tick`.
- `api/storage/`: canonical persistence layer for file manifests, file versions, uploads, runs/events/progress, synthesis references, prompt versions, autopilot state, R2 access, optional Postgres run storage, and optional Redis run broadcasting.
- `api/youtube_download.py`: backend-side YouTube download provider chain used by `/v1/music/youtube-imports`.
- `api/prototyping/music/`: the pure allin1 music analyzer, its Modal app (`eclypte-analysis`), and lyrics lookup. (Ingestion lives in `api/youtube_download.py`; R2 publishing of the `music_analysis`/`lyrics` assets is done by `api/workflows.py`.) `search_synced_lyrics` (synced LRC only) is fetched opportunistically during analysis and stored as a `lyrics` asset (kept for future use; no longer rendered as an overlay).
- `api/prototyping/video/`: scene, motion, and impact analysis modules orchestrated by the GPU analyzer (`analysis_cuda.py`), shipped as Modal GPU analysis and R2-aware Modal video analysis apps. `credits.py` adds OCR-based end-credit detection that writes a `content_end_sec` into the `video_analysis` payload to hard-cap the usable source. `poster.py` is a pure, unit-tested poster-frame picker (brightness/detail/window-position scoring, same pure-decision style as `credits.py`); the GPU orchestrator (`analysis_cuda.py`) uses it to pick a representative frame during the decode pass, and `run_video_analysis` publishes it as a best-effort `source_poster` asset (never fails the run).
- `api/prototyping/edit/`: agentic timeline planning, CLIP index build/query, reference ingestion/metrics, timeline schemas/validation, a pure rhythm engine (`synthesis/rhythm.py` — downbeat-preferred beat snapping with a 0.04s early-cut lead, impact→downbeat source-window registration, tempo-scaled per-section pacing bands with a deterministic split backstop, and `sync_report` telemetry), a registry of agent-placed creative overlay skills (`skills/` — text/masks composited over the reel), and rendering (MP4 + poster frame), plus R2-aware Modal render/index wrappers. `render/renderer.py::render_timeline` dispatches capability-driven: cuts/crossfade/whip/flash, freeze/punch_in effects, and every overlay skill with an ffmpeg port (`ffmpeg_supported` + `ffmpeg_filter` fragments, drawtext with double escaping) render through a single native ffmpeg filtergraph (`render/ffmpeg_filtergraph.py` + `render/ffmpeg_run.py`, ~17× faster than MoviePy on the same hardware); only unported features fall back to the MoviePy v2 path. Both paths share identical encode flags and the poster/progress contract, and both apply an end-of-reel audio fade-out + video fade-to-black (`fade_out_sec` on the timeline, set by the adapter via `tail_fade_for`; native ffmpeg emits `afade`/`fade`, the MoviePy path uses `render/fades.py`).
- `api/prototyping/progress_events.py`: progress emitter used inside Modal workers. Prefer internal API progress writes when configured; otherwise it can append events through R2 config.
- `api/prototyping/modal_s3.py`: shared S3/R2 client and object-download helpers used inside the R2-aware Modal wrappers; mounted by bare module name like `progress_events`.
- Modal apps snapshot local code at `modal deploy` time (`add_local_python_source`); a Railway push does not update them. After changing `edit/render/**`, `edit/skills/**`, or the timeline schema/validators, redeploy `eclypte-render-r2` from `api/prototyping/` (`modal deploy edit/render_storage_modal.py`). After changing `video/analysis_cuda.py`/`video/credits.py`/`video/poster.py` (credit OCR + poster-frame picker; image bundles `tesseract-ocr`), redeploy `eclypte-video-r2` (`PYTHONUTF8=1 modal deploy video/storage_modal.py` on Windows) and re-analyze a film to populate the new `credits` block and/or its poster thumbnail.
- `api/COMMANDS.md`: command runbook for local API, Modal, R2, timeline planning, rendering, and tests.
- `.agent/` and `.superpowers/`: agent profile/process assets, not application runtime code. (The old `docs/` plans/specs directory has been removed.)
- `content/`, `api/prototyping/**/content/`, `youtube-worker-tmp/`, and pytest temp dirs: local scratch/generated media areas.

## Product Flow

- Users upload audio (WAV, or any common format such as MP3/M4A/FLAC auto-converted to WAV server-side) and MP4 source video from the dashboard through presigned R2 PUT URLs.
- Assets are stored as strict `FileManifest` and immutable `FileVersionMeta` records. Default asset lists hide archived files, render outputs, render posters, and source posters unless requested. `AssetSummary.poster` carries an optional thumbnail ref (a `source_poster` for source videos, a `render_poster` for render outputs) and `AssetSummary.poster_url` a ready-to-use signed URL, presigned locally in the listing from the deterministic version blob key (zero extra network ops). Publishing post routes respond with `PublishingPostView` — the stored record plus per-response `poster_url`/`render_url`; signed URLs are never persisted (posts store only `render_poster_file_id/version_id` refs, captured at creation and lazily backfilled for legacy posts).
- Workflow endpoints return `RunManifest` records immediately; `DefaultWorkflowRunner` continues work in FastAPI background tasks.
- Music analysis, video analysis, YouTube import, timeline planning, rendering, edit pipelines, and synthesis consolidation all surface status through run manifests and events.
- `POST /v1/edits` is the dashboard pipeline: select saved audio/video, ensure missing analysis, plan a timeline, render an MP4, and expose a signed download URL.
- Each render publishes both a `render_output` MP4 and a `render_poster` JPEG thumbnail; the dashboard shows the poster instantly and lazy-loads the MP4 on play. Edit `progress_percent` is weighted by typical stage duration and the render stage fills from real encode progress.
- Autopilot (managed from the Home feed at `/dashboard`; `/dashboard/autopilot` now redirects there) turns a curated backlog of (source video × song) pairs into ready-to-review publishing packages on a daily target; it never sends to Buffer itself — packages land as `ready` + `auto_created` for human approval in the same Home feed.
- Buffer publishing is review-gated. The Home feed's "Ready for you" review sheet (`/dashboard/publish` now redirects to `/dashboard`) lets users edit captions/hashtags/notes, then post now, queue, or schedule an approved render through Buffer as an Instagram Reel ("Post now" sends a `customScheduled` post due a minute out so it publishes near-immediately instead of waiting for the next queue slot). Public R2 copies under `public/publishing/{user_id}/{post_id}/` are created only when sending to Buffer; the page polls in-flight posts against Buffer (~25s interval + on tab refocus) so a queued post that goes live auto-advances to Posted and its permalink back-fills, and a manual "Refresh from Buffer" button re-checks on demand (surfacing Buffer errors the background poll swallows).
- Edit jobs can be listed, canceled, archived/deleted, and redone. Child run ids are stored on the parent edit run outputs.
- Timeline planning always runs the OpenAI/CLIP agent: it can create or reuse a `clip_index` asset, load the active synthesis prompt, call the OpenAI-backed synthesis loop, validate coverage, and publish a timeline artifact. The synthesis loop (`api/prototyping/edit/synthesis/agent.py`) runs OpenAI `gpt-5.5` with `reasoning_effort="high"` and `verbosity="low"`, and must fail visibly via `RunManifest.last_error` rather than silently degrade (there is no fallback planner). The baseline prompt has ONE source of truth — `synthesis/system_prompt.py` (`SYSTEM_PROMPT`), imported by `agent.py` as its fallback and by `workflows.py`/`app.py` as `DEFAULT_SYNTHESIS_PROMPT` (the default prompt-version text + consolidation base); edit the prompt only there.
- The agent spans the full source start→end regardless of song length, so trimmed/short edits still cover the whole film. It is given the source duration and instructed (via per-run user content, independent of the active prompt) to traverse the entire source. This is guidance, not hard enforcement — the agent may still dwell on standout moments.
- Musicality is layered: the agent gets per-run pacing targets (tempo-scaled shot-length bands per song section) and `query_clips` results enriched with scene `motion`/`camera`/`impact_near` metadata (`_enrich_clip_results` in `api/workflows.py`); the adapter's rhythm engine then deterministically splits egregiously long fast-section shots at downbeats, snaps interior cuts to downbeat-preferred anchors 0.04s early, and shifts source windows so visual impacts land on downbeats. Completed synthesis references parameterize this at plan time (`synthesis/style_profile.py::derive_style_profile` → cut lead + pacing-band overrides, threaded into both the agent context and `adapt`). Each timeline run records a `timeline_sync_report` event (on-beat %, registrations, splits, active style profile).
- The agent must not select black frames, solid colors, title cards, logos, or end credits, and spans the end of the *content* rather than trailing credits. This is enforced data-side: the CLIP index records per-frame brightness/detail and `query_index_r2` filters dead frames out of `query_clips` results (`api/prototyping/edit/index/`). Bump `CLIP_INDEX_BUILD_STEP` (`api/workflows.py`) and redeploy `eclypte-clip-index-r2` when the index format changes; stale indexes rebuild once. End credits (bright, dense text — invisible to the brightness/detail filter) are additionally cut by a hard `content_end_sec` (video-analysis credit detection): it caps the agent's source duration, clamps every shot's source range in the adapter, and drops CLIP results past it. Analyses without a `credits` block fall back to full duration. Because colored-background credits escape the brightness/detail filter and older analyses may lack the cap, the prompt (`system_prompt.py` + the per-run source context in `agent.py`) also tells the agent to treat any text-heavy frame as credits regardless of background color and to pull the CLOSING shot's source timestamp back from the very end of the source.
- Export options flow from the dashboard into timeline planning and rendering. `reels_9_16` renders 1080x1920 with fill crop and `crop_focus_x`; `reels_cinematic` renders 1080x1920 with the full widescreen picture letterboxed on the vertical canvas; `youtube_16_9` renders 1920x1080 with letterbox. Audio trim fields trim the music analysis and set the timeline audio offset.
- Creative skills come from a registry (`edit/skills/`) in three kinds: windowed overlays (text/masks), whole-reel `grade.*` presets (agent picks at most one via finish_edit's `grade` field; adapter maps it to a full-reel overlay under the others), and `moment` accents (`impact.shake` — agent-placed or auto-placed by the adapter on the strongest impact+downbeat registrations). Adding/removing a skill is a single self-contained module; the agent tool enums, validators, and both render paths all read the registry. Effects now include a real `speed_ramp` (1x first half, 1.5x second half; adapter extends the source window to 1.25x duration).
- Run streams are newline-delimited JSON from Redis when available, not SSE. Frontend callers must keep polling fallbacks because Redis is optional and not durable state.

## API Surface

- Health: `GET /healthz` (also reports non-secret YouTube-cookie, realtime/Redis, Modal worker-progress, and always-on autopilot-loop configuration booleans).
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/music/conversions`, `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer` (`mode`: `queue`/`schedule`/`now`), `POST /v1/publishing/posts/{post_id}/refresh-status`, `POST /v1/publishing/posts/{post_id}/mark-posted`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Autopilot: `GET /v1/autopilot`, `PATCH /v1/autopilot`, `POST /v1/autopilot/queue`, `DELETE /v1/autopilot/queue/{item_id}`, `POST /v1/autopilot/tick`.
- Internal worker progress: `POST /internal/progress`, requiring `X-Eclypte-Internal-Token`. Do not expose this token to the browser.

## Frontend Notes

- This is Next.js 16.2.3. Read local docs in `web/node_modules/next/dist/docs/` before changing Next APIs, routing conventions, proxy/middleware, cache behavior, server actions, metadata, `headers()`, `cookies()`, or `params`.
- Middleware/proxy lives at `web/src/proxy.ts`, following the Next.js 16 renamed convention.
- App Router pages live under `web/src/app/`.
- Marketing routes are `/` (landing), `/pricing` (three-tier pricing + FAQ), and `/demo` ("Screening Room" demo with poster-first lazy video; `web/src/components/demo/demoPlayer.tsx`).
- The dashboard is a 3-page IA — Home, Library, Settings — plus two unlisted-but-routable pages (New Edit, Synthesis) and three redirect stubs for bookmark compatibility:
  - `/dashboard` (Home): the pipeline feed and the dashboard's index route. Absorbed the old autopilot and publish pages — autopilot status (enable/pause, daily target, halt banner), a "Ready for you" Buffer-publishing review-card grid, "In the works"/"Up next" live job/backlog rows, a "Posted" strip, and `Sheet`-based review/composer flows (caption editing/regeneration, queue/schedule/post-now/mark-as-posted actions, live polling of in-flight posts against Buffer with a manual "Refresh from Buffer" re-check).
  - `/dashboard/assets` (Library, linked as "Library" in the top bar): direct R2 uploads with real byte progress, asset library with Films/Songs/Reels tab pills (`?tab=` query param) + a Hidden link — replacing the old Sources/Derived/Hidden tabs and absorbing the render-output library into the Reels tab — manual analysis, YouTube song import, preview/download, delete/restore.
  - `/dashboard/new-edit`: saved asset selection, export controls, crop preview, edit creation, run streaming/poll fallback, stage progress, preview/download, cancel/delete/redo. Not in the top-bar nav; still routable directly.
  - `/dashboard/synthesis`: reference queueing, consolidation, active prompt viewing/editing/version activation. Not in the top-bar nav; reachable via a link on `/dashboard/settings`.
  - `/dashboard/settings`: API/user/prompt/YouTube-cookie health plus realtime (Redis), worker-progress, and autopilot-loop status, with an Advanced disclosure for the raw API base URL and account id.
  - `/dashboard/publish` and `/dashboard/autopilot` redirect to `/dashboard`; `/dashboard/renders` redirects to `/dashboard/assets?tab=reels`.
- `NEXT_PUBLIC_ECLYPTE_API_BASE_URL` controls the API base and defaults to `http://127.0.0.1:8000`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`; backend Clerk JWT verification is intentionally deferred.
- Browser audio uploads accept WAV or any common audio format (MP3/M4A/AAC/FLAC/OGG), with non-WAV audio auto-converted to WAV server-side via `POST /v1/music/conversions`; video uploads are MP4-only.
- Prefer extending `web/src/services/eclypteApi.ts` over ad hoc browser `fetch` calls.
- Keep visual work aligned with the existing landing/dashboard design language. The dashboard is utilitarian product UI, not a placeholder.

## Backend Notes

- `api/main.py` exposes `api.app.create_app()` for local and Railway startup.
- `railpack.json` starts the service with `python -m api.main` on Python 3.13; root `requirements.txt` is intentionally self-contained for Railpack/Railway.
- Real `/v1/*` calls require R2 env vars. Optional `DATABASE_URL` moves runs/events/progress to Postgres. Optional `REDIS_URL` enables realtime dashboard streams.
- Buffer publishing requires `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`. `send-buffer` `mode` is `queue` (`addToQueue`, next posting-schedule slot), `schedule` (`customScheduled` at a chosen `dueAt`), or `now` (`customScheduled` at a server-computed `dueAt` = now + `ECLYPTE_BUFFER_POST_NOW_LEAD_SEC` (default 60s), to post near-immediately since Buffer has no instant-publish mode and rejects past `dueAt`). AI captions use `OPENAI_API_KEY` and optional `ECLYPTE_CAPTION_MODEL`, are generated with the source movie/anime + song names as context (yielding context-relevant hashtags); if unavailable or invalid, deterministic fallback captions are stored with `caption_source="fallback"`.
- `ECLYPTE_INTERNAL_PROGRESS_TOKEN` gates `/internal/progress`; Modal workers must send a matching `X-Eclypte-Internal-Token`. Keep it server-side only.
- Run and artifact models are strict Pydantic models. Preserve `schema_version: 1`, `_sec` timestamp naming, and existing `RunManifest.outputs` keys unless a coordinated migration is part of the task.
- Storage artifact kinds are `source_video`, `song_audio`, `lyrics`, `music_analysis`, `video_analysis`, `clip_index`, `timeline`, `render_output`, `render_poster`, and `source_poster`.
- Strict record models in `api/storage/models.py` include `FileManifest`, `FileVersionMeta`, `RunManifest`, `RunEvent`, `UploadReservation`, `SynthesisReferenceRecord`, `SynthesisPromptVersion`/`SynthesisPromptState`, and `PublishingPostRecord`.
- YouTube downloads stay backend-side. Surface `RunManifest.last_error` and `youtube_download_attempt` events instead of adding browser-side extraction.
- Do not commit secrets, exported cookies, Modal tokens, API keys, or `.env` files.

## Modal And ML Constraints

- Do not install the heavy ML stack locally unless the task explicitly asks for dependency work. Audio allin1, torch, natten, CLIP, OpenCV-CUDA, and related packages belong in Modal images.
- `api/requirements.txt` is for local backend/prototype development; `api/requirements-modal.txt` is for the heavy Modal audio image; root `requirements.txt` is for Railway.
- Keep pure analysis modules free of Modal imports. Modal wrappers should call pure functions through `add_local_python_source()` or explicit storage wrappers.
- Shared wrapper helpers (`modal_s3.py`, `progress_events.py`) live at `api/prototyping/`; list them in each app's `add_local_python_source()` and run `modal deploy` from `api/prototyping/` so they resolve.
- R2-aware Modal apps used by the API include `eclypte-video-r2` (`api/prototyping/video/storage_modal.py`), `eclypte-clip-index-r2` (`api/prototyping/edit/index/storage_modal.py`), and `eclypte-render-r2` (`api/prototyping/edit/render_storage_modal.py`).
- `eclypte-analysis` (`api/prototyping/music/analysis_modal.py`) and `eclypte-video` (`api/prototyping/video/analysis_modal.py`) are non-R2 Modal apps used in production by music analysis and synthesis reference ingest, respectively.

## Commands

- Backend broad check: `python -m pytest api -v`
- Focused API check: `python -m pytest api/test_api_v1.py -v`
- Storage check: `python -m pytest api/storage -v`
- Export option check: `python -m pytest api/test_export_options.py -v`
- Edit synthesis/index/skills checks: `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index api/prototyping/edit/skills -v`
- Credit detection check: `python -m pytest api/prototyping/video/test_credits.py -v`
- Poster-frame picker check: `python -m pytest api/prototyping/video/test_poster.py -v`
- Publishing checks: `python -m pytest api/test_publishing.py -v`
- Run API locally: `python -m api.main`
- Frontend dev: from `web/`, `npm run dev`
- Frontend verification: from `web/`, `npm run lint` and `npm run build`
- Canonical PowerShell/bash runbook: `api/COMMANDS.md`

## Working Conventions

- Prefer existing repository boundaries and typed helpers over new parallel abstractions.
- Add or update tests near the changed module when behavior changes.
- When changing API contracts, update both `api/app.py` models/routes and `web/src/services/eclypteApi.ts`.
- Keep API behavior, adapter behavior, and renderer behavior aligned through `api/export_options.py`.
- Keep acquisition/import private and lawful at the code boundary: do not add scraper, DRM bypass, or unauthorized downloader paths. Public publishing must stay review-gated unless a separate postability gate is explicitly designed.
- Treat `web/AGENTS.md`, `api/COMMANDS.md`, and root `CLAUDE.md` as living context; reconcile them if your change makes them stale.
- Preserve user work in the tree. Do not revert unrelated local changes.
