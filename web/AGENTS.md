<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes - APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

Repo-wide architecture and backend guidance lives in `../AGENTS.md`; this file adds frontend-specific notes for `web/`.

## Current Frontend Shape

- App Router lives in `src/app/`.
- `src/app/page.tsx` is the main marketing landing page and composes most shared homepage components.
- `src/app/pricing/page.tsx` is a three-tier pricing page (Free/Creator/Studio) with a short FAQ.
- `src/app/demo/page.tsx` is the "Screening Room" demo page. It uses poster-first lazy video (`src/components/demo/demoPlayer.tsx` — `DemoReel`/`DemoTile`): a small `webp` poster loads immediately and the `<video>` mounts only on click, one at a time. Posters live in `public/demo/posters/` and web-optimized 1080p sources in `public/demo/web/` (the 4K originals are unreferenced).
- `src/app/dashboard/page.tsx` redirects to the creator console default route at `/dashboard/new-edit`.
- The dashboard console uses real App Router pages:
  - `/dashboard/new-edit` selects existing song/video assets, previews the source crop, sets export format and audio trim, reuses completed analyses when available, auto-runs missing analysis, then chains AI-agent timeline planning, rendering, and final preview/download. It also exposes an optional creative brief, job cancel/delete, and redo for failed/canceled jobs.
  - `/dashboard/assets` uploads persistent WAV/MP4 assets to R2, cleans up failed upload reservations, lists the R2-backed library (Sources/Derived/Hidden tabs, plus a Songs/Sources kind filter on the Sources tab) including hidden archived items, starts manual analysis, imports YouTube songs, opens preview/download URLs, and deletes/restores assets. The library paginates at 24/page; the other dashboard lists at 10/page.
  - `/dashboard/publish` reviews Buffer publishing packages for Instagram Reels, shows setup diagnostics, previews render outputs, edits/regenerates captions, posts now (immediate via a server-computed near-future `dueAt`)/queues/schedules posts, records Buffer/public-media status, polls in-flight posts against Buffer (~25s interval + on tab refocus) so queued posts auto-advance to Posted and permalinks back-fill, offers a manual "Refresh from Buffer" button to re-check on demand (surfacing Buffer errors the background poll swallows), and a "Mark as posted" override that unsticks a queued/scheduled post Buffer can't reconcile. A failed Buffer lookup is recorded on the post and shown inline instead of 502ing.
  - `/dashboard/synthesis` queues Instagram Reel references, runs synthesis consolidation, exposes the effective system prompt, saves prompt versions, and reactivates older versions.
  - `/dashboard/autopilot` manages the review-gated content autopilot: enable/pause, daily target, a backlog form pairing a saved video with a song asset or YouTube link (optional creative brief), a queue/activity list refreshed via `useRunStream`, a halt banner with clear action, and a manual "Run tick now" button (needed when the server lacks `ECLYPTE_AUTOPILOT=1`). Packaged items link to `/dashboard/publish`, where auto-created packages are marked "autopilot".
  - `/dashboard/renders` lists render runs and output MP4 assets with preview/download actions, refreshing active render runs from run streams with polling fallback.
  - `/dashboard/settings` shows the API base URL, signed-in Clerk user id, API health, YouTube-cookie configuration, realtime (Redis) and worker-progress status, and the active synthesis prompt version.
- `src/proxy.ts` contains the Clerk middleware matcher for app and API routes.
- `src/components/login/login.tsx` renders the Clerk `SignIn` modal; `src/components/navbar/navbar.tsx` controls opening it.
- Fonts are configured in `src/app/layout.tsx` with both Google fonts and local font assets from `public/fonts/`.
- The dashboard's visual identity ("Edit Bay") is a dark, semantic CSS-token set defined under `[data-surface="studio"]` in `src/app/globals.css` (surfaces/text/lines/accent, the `--energy` gradient signature, `--font-display`/`--font-ui`/`--font-mono`), applied via `data-surface="studio"` on the dashboard container in `src/app/dashboard/layout.tsx`. The dashboard CSS modules consume those semantic tokens directly. The marketing site keeps its own `--color-*` / `[data-theme="dark"]` theme — do not edit `:root`/`[data-theme]`/the reset/`body` when touching dashboard styling.
- `src/services/eclypteApi.ts` is the typed browser API client for FastAPI v1 endpoints, including uploads, assets, run streams, edit jobs, export options, downloads, synthesis prompt/reference, and publishing APIs.
- `src/app/dashboard/dashboardCommon.tsx` exports the shared dashboard page wrapper, skeletons, formatting helpers (`formatBytes`/`formatDate`/`kindLabel`/`humanizeLabel` — `kindLabel` and `StatusBadge` Title-case raw enum/kind strings so the UI shows `Song Audio`/`Completed`, not `song_audio`/`completed`), client-side list pagination (`usePagination` + the `Pager` control, used by every big dashboard list — pass a `resetKey` like the active tab/filter to jump back to page 1), the `errorMessage`/`isAbortError` error helpers, and `useAbortableLoad` — a no-cache loader hook (aborts the prior in-flight load, drops stale/aborted responses). `/settings` still uses it directly; the data pages now load through the cache store below.
  - It also centralizes the **creator-facing humanizers** that keep backend internals out of the UI — `statusLabel` (raw status enum → friendly word, wired into `StatusBadge`), `humanizeStageDetail` (raw worker `stage.detail`/`current_step` → a friendly sentence), `formatClock`/`formatDuration` (seconds → `m:ss` / `25s`), and the shared `EmptyState`, `MetaList` (replaces `JSON.stringify` dumps), and `CopyableId` (hides raw UUIDs) components. Prefer these over inlining raw IDs, JSON, or infra/jargon strings on a page.
- `src/stores/` is a zustand stale-while-revalidate cache shared across dashboard pages: `dashboardStore.ts` (generic per-key resource cache with in-flight dedup + latest-wins via AbortController), `useResource.ts` (the SWR hook → `{ data, isLoading, isValidating, error, revalidate, set }`), and `dashboardResources.ts` (typed, user-scoped wrappers: `useAssets`, `useEditJobs`, `useRuns`, `usePublishingPosts`, `usePublishingConfig`, `useSynthesisReferences`, `useSynthesisPrompt`, `useAutopilot`). Cache keys are scoped by `EclypteApiClient.userId`; signed download/preview URLs are never cached. **`src/stores/README.md` has the full design, the page→resource map, and the editing gotchas (extract stable `revalidate`/`set` before using them in deps; memoize `data ?? []` when it feeds an effect; dirty-guard user-owned inputs).**
- `src/app/dashboard/useRunStream.ts` is the shared run-stream hook (debounced refresh callback, a ~15s safety-poll watchdog that reconciles a connected-but-silent stream, plus a 1s polling fallback when the stream fails) used by `/dashboard/new-edit`, `/dashboard/renders`, and `/dashboard/autopilot`.

## Dashboard Pipeline Notes

- The dashboard API base comes from `NEXT_PUBLIC_ECLYPTE_API_BASE_URL`, defaulting to `http://127.0.0.1:8000`. Local development should use `web/.env.local`; deployed frontends should set the same public env var in the hosting provider.
- The current production API is `https://api-production-8fb8.up.railway.app`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`. Backend Clerk JWT verification is intentionally deferred.
- Dashboard data loading uses the `src/stores/` zustand SWR cache: each page's primary list goes through a typed `useResource` wrapper, so route changes serve cached data instantly and revalidate in the background (TTL ~30s) with in-flight dedup and latest-wins. Mutations patch the cache via the hook's `set` (value or updater) instead of re-pulling the whole collection (archive/restore/delete update the array in place); `useRunStream` and the publish Buffer-poll refreshers call `revalidate`. Deliberately, a fetch is NOT aborted on unmount — letting it finish populates the shared cache; correctness comes from latest-wins + dedup. The Publish package list uses the compact `.packageRow` layout because the 5-column `.assetRow` table only fits the wide panel. The Synthesis prompt textarea is user-owned — a background revalidate must not overwrite unsaved edits, guarded by a last-seeded-value dirty check (`lastSeededRef`).
- V1 audio uploads accept WAV or any common audio format (MP3/M4A/AAC/FLAC/OGG); non-WAV audio is auto-converted to a WAV `song_audio` asset server-side via `POST /v1/music/conversions` (the assets page chains upload→convert→poll and archives the raw upload). Video uploads are `video/mp4` only. Validate accordingly before upload.
- Uploads are browser-to-R2 using presigned PUT URLs from `POST /v1/uploads`, followed by `POST /v1/uploads/{upload_id}/complete` with a browser-computed SHA-256. `sha256File()` in `eclypteApi.ts` hashes the file in chunks via `hash-wasm` (not `crypto.subtle.digest`, which caps inputs at 2 GB), so large uploads work; the effective ceiling is R2's ~5 GiB single-PUT limit because multipart upload is not implemented.
- Failed or aborted uploads should call `DELETE /v1/uploads/{upload_id}` so orphaned reservations/blob keys do not linger.
- The dashboard library is persistent and R2-backed. `/v1/assets` hides archived records by default and excludes render outputs and render posters unless `kind=render_output` is requested. `/dashboard/assets` owns upload, archive/restore, and manual analysis; `/dashboard/new-edit` composes from saved assets and starts missing analyses only when needed.
- `/dashboard/assets` can import songs from YouTube via `POST /v1/music/youtube-imports`; imports publish a `song_audio` asset and auto-run music analysis.
- `/dashboard/publish` uses `/v1/publishing/*` endpoints through `src/services/eclypteApi.ts`. Buffer/OpenAI secrets stay server-side; the browser only receives non-secret config booleans, channel metadata, publishing records, and signed preview/download URLs.
- Publish packages are review-gated and sent as Instagram Reels. Public R2 publishing copies and Buffer posts are only created when the user queues or schedules a post. A post is marked `published` as soon as Buffer reports it sent (`sentAt`/sent status) and its permalink (`externalLink`) back-fills independently when it appears, via `POST /v1/publishing/posts/{post_id}/refresh-status` — driven by the page's live poll of in-flight posts (~25s interval + on tab refocus) or the manual "Refresh from Buffer" button, which also surfaces Buffer errors the poll swallows.
- YouTube media download stays backend-side in `api/youtube_download.py`. The frontend should poll the returned run manifest and surface `RunManifest.last_error` for failures rather than attempting browser-side media extraction.
- Backend YouTube import runs record provider-level `youtube_download_attempt` events, but the current dashboard client does not expose run events as a first-class UI view.
- New Edit uses `/v1/edits` durable edit jobs, subscribes to `/v1/runs/stream` while jobs are active, falls back to polling, and then requests the render download URL. The UI exposes cancel, delete/archive, and redo through the edit-job lifecycle endpoints.
- The New Edit export controls serialize `ExportOptions`: `reels_9_16` for 1080x1920 vertical fill crop, `reels_cinematic` for 1080x1920 with the widescreen picture letterboxed on the vertical canvas, `youtube_16_9` for 1920x1080 letterbox, optional `audioStartSec`/`audioEndSec`, and `cropFocusX` for vertical framing (fill mode only). The frontend defaults the compose UI to Reels; the backend default remains YouTube 16:9 when export options are omitted.
- Timeline planning always runs the AI agent: it may create/reuse a `clip_index` asset, uses the active synthesis prompt version, and fails visibly through `RunManifest.last_error` if OpenAI/CLIP planning fails.
- Run streams are newline-delimited JSON, not SSE. Use `readJsonLineStream`/`drainJsonLines` and keep polling fallback logic because Redis may be unconfigured or stale.
- Synthesis prompt versions and reference records are stored under the current `X-User-Id` in R2. The active prompt is used by future agent-mode timeline planning.
- The frontend depends on these `RunManifest.outputs` keys:
  - `music_analysis_file_id`, `music_analysis_version_id`
  - `video_analysis_file_id`, `video_analysis_version_id`
  - `timeline_file_id`, `timeline_version_id`
  - `render_output_file_id`, `render_output_version_id`
  - `render_poster_file_id`, `render_poster_version_id`
- Agent timeline runs may also return `clip_index_file_id`, `clip_index_version_id`, and `synthesis_prompt_version_id`.
- R2 bucket CORS must allow browser `PUT` uploads and `GET`/range playback from local and deployed frontend origins. A missing bucket CORS config presents as a failed preflight on the presigned R2 URL, even when Railway API CORS is correct.

## Working Assumptions

- Preserve the existing visual language on the landing page rather than replacing it with generic boilerplate.
- Check whether a route is still placeholder-level before doing large refactors; `/pricing` and `/demo` are now built-out marketing pages and `/dashboard` has real orchestration behavior — treat all as product code.
- Project history, a full timeline editor, refresh-resume for in-flight workflows, and backend Clerk JWT verification are still deferred.
- Keep `/editor` out of scope unless the task explicitly asks for it.

## Verification Notes

- Run `npm run lint` and `npm run build` from `web/` after dashboard/frontend API changes.
- A live smoke test on 2026-04-25 confirmed Railway API health, API CORS, R2 upload preflight/PUT/complete, music analysis, video analysis, timeline planning, rendering, and final MP4 range download against `https://api-production-8fb8.up.railway.app`.
- A production YouTube import smoke on 2026-04-25 completed `run_9a16fbdfff0a` for `75qIYkMUGVE`, producing `song_audio` plus `music_analysis` outputs after the downloader was realigned with the working prototype path.
- The Codex in-app browser may not support signed-in Clerk flows. If browser automation is unavailable or cannot authenticate, validate the pipeline with direct API/R2 smoke tests and clearly call out that UI clickthrough was not exercised.
