<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes - APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

Repo-wide architecture and backend guidance lives in `../AGENTS.md`; this file adds frontend-specific notes for `web/`.

## Current Frontend Shape

- App Router lives in `src/app/`.
- `src/app/page.tsx` is the main marketing landing page and composes most shared homepage components.
- `src/app/pricing/page.tsx` is still lightweight.
- `src/app/dashboard/page.tsx` redirects to the creator console default route at `/dashboard/new-edit`.
- The dashboard console uses real App Router pages:
  - `/dashboard/new-edit` selects existing song/video assets, reuses completed analyses when available, auto-runs missing analysis, then chains AI-agent timeline planning by default, rendering, and final preview/download. It also exposes a deterministic planning opt-out and optional creative brief.
  - `/dashboard/assets` uploads persistent WAV/MP4 assets to R2, lists the R2-backed library, starts manual analysis, and opens preview/download URLs.
  - `/dashboard/synthesis` queues Instagram Reel references, runs synthesis consolidation, exposes the effective system prompt, saves prompt versions, and reactivates older versions.
  - `/dashboard/renders` lists render runs and output MP4 assets with preview/download actions.
  - `/dashboard/settings` shows the API base URL, signed-in Clerk user id, API health, and active synthesis prompt version.
- `src/proxy.ts` contains the Clerk middleware matcher for app and API routes.
- `src/components/login/login.tsx` renders the Clerk `SignIn` modal; `src/components/navbar/navbar.tsx` controls opening it.
- Fonts are configured in `src/app/layout.tsx` with both Google fonts and local font assets from `public/fonts/`.
- `src/services/eclypteApi.ts` is the typed browser API client for FastAPI v1 endpoints, including asset/run listing and synthesis prompt/reference APIs.

## Dashboard Pipeline Notes

- The dashboard API base comes from `NEXT_PUBLIC_ECLYPTE_API_BASE_URL`, defaulting to `http://127.0.0.1:8000`. Local development should use `web/.env.local`; deployed frontends should set the same public env var in the hosting provider.
- The current production API is `https://api-production-8fb8.up.railway.app`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`. Backend Clerk JWT verification is intentionally deferred.
- V1 intentionally accepts only `audio/wav` and `video/mp4`; validate those before upload.
- Uploads are browser-to-R2 using presigned PUT URLs from `POST /v1/uploads`, followed by `POST /v1/uploads/{upload_id}/complete` with a browser-computed SHA-256.
- The dashboard library is persistent and R2-backed. `/dashboard/assets` owns upload and manual analysis; `/dashboard/new-edit` composes from saved assets and starts missing analyses only when needed.
- `/dashboard/assets` can import songs from YouTube via `POST /v1/music/youtube-imports`; imports publish a `song_audio` asset and auto-run music analysis.
- YouTube media download stays backend-side in `api/youtube_download.py`. The frontend should poll the returned run manifest and surface `RunManifest.last_error` for failures rather than attempting browser-side media extraction.
- Backend YouTube import runs record provider-level `youtube_download_attempt` events, but the current dashboard client does not expose run events as a first-class UI view.
- New Edit polls run manifests for music analysis, video analysis, timeline planning, and rendering, then requests the render download URL.
- Timeline planning now defaults to `planning_mode: "agent"`. Agent mode may create/reuse a `clip_index` asset, uses the active synthesis prompt version, and fails visibly through `RunManifest.last_error` if OpenAI/CLIP planning fails. Send `planning_mode: "deterministic"` to opt out.
- Synthesis prompt versions and reference records are stored under the current `X-User-Id` in R2. The active prompt is used by future agent-mode timeline planning.
- The frontend depends on these `RunManifest.outputs` keys:
  - `music_analysis_file_id`, `music_analysis_version_id`
  - `video_analysis_file_id`, `video_analysis_version_id`
  - `timeline_file_id`, `timeline_version_id`
  - `render_output_file_id`, `render_output_version_id`
- Agent timeline runs may also return `clip_index_file_id`, `clip_index_version_id`, and `synthesis_prompt_version_id`.
- R2 bucket CORS must allow browser `PUT` uploads and `GET`/range playback from local and deployed frontend origins. A missing bucket CORS config presents as a failed preflight on the presigned R2 URL, even when Railway API CORS is correct.

## Working Assumptions

- Preserve the existing visual language on the landing page rather than replacing it with generic boilerplate.
- Check whether a route is still placeholder-level before doing large refactors; `/pricing` is skeletal, but `/dashboard` now has real orchestration behavior and should be treated as product code.
- Project history, a full timeline editor, refresh-resume for in-flight workflows, and backend Clerk JWT verification are still deferred.
- Keep `/editor` out of scope unless the task explicitly asks for it.

## Verification Notes

- Run `npm run lint` and `npm run build` from `web/` after dashboard/frontend API changes.
- A live smoke test on 2026-04-25 confirmed Railway API health, API CORS, R2 upload preflight/PUT/complete, music analysis, video analysis, timeline planning, rendering, and final MP4 range download against `https://api-production-8fb8.up.railway.app`.
- A production YouTube import smoke on 2026-04-25 completed `run_9a16fbdfff0a` for `75qIYkMUGVE`, producing `song_audio` plus `music_analysis` outputs after the downloader was realigned with the working prototype path.
- The Codex in-app browser may not support signed-in Clerk flows. If browser automation is unavailable or cannot authenticate, validate the pipeline with direct API/R2 smoke tests and clearly call out that UI clickthrough was not exercised.
