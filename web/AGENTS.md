<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Current Frontend Shape

- App Router lives in `src/app/`.
- `src/app/page.tsx` is the main marketing landing page and composes most shared homepage components.
- `src/app/pricing/page.tsx` is still lightweight.
- `src/app/dashboard/page.tsx` is the first real signed-in product flow: a client-side "New Edit" workspace that accepts one WAV song and one MP4 source video, then chains upload, music analysis, video analysis, timeline planning, rendering, and final preview/download.
- `src/proxy.ts` contains the Clerk middleware matcher for app and API routes.
- `src/components/login/login.tsx` renders the Clerk `SignIn` modal; `src/components/navbar/navbar.tsx` controls opening it.
- Fonts are configured in `src/app/layout.tsx` with both Google fonts and local font assets from `public/fonts/`.
- `src/services/eclypteApi.ts` is the typed browser API client for the existing FastAPI v1 endpoints.

## Dashboard Pipeline Notes

- The dashboard API base comes from `NEXT_PUBLIC_ECLYPTE_API_BASE_URL`, defaulting to `http://127.0.0.1:8000`. Local development should use `web/.env.local`; deployed frontends should set the same public env var in the hosting provider.
- The current production API is `https://api-production-8fb8.up.railway.app`.
- Temporary auth sends Clerk `user.id` as `X-User-Id`. Backend Clerk JWT verification is intentionally deferred.
- V1 intentionally accepts only `audio/wav` and `video/mp4`; validate those before upload.
- Uploads are browser-to-R2 using presigned PUT URLs from `POST /v1/uploads`, followed by `POST /v1/uploads/{upload_id}/complete` with a browser-computed SHA-256.
- After upload completion, the dashboard starts music and video analysis in parallel, polls run manifests, then starts timeline planning, rendering, and finally requests the render download URL.
- The frontend depends on these `RunManifest.outputs` keys:
  - `music_analysis_file_id`, `music_analysis_version_id`
  - `video_analysis_file_id`, `video_analysis_version_id`
  - `timeline_file_id`, `timeline_version_id`
  - `render_output_file_id`, `render_output_version_id`
- R2 bucket CORS must allow browser `PUT` uploads and `GET`/range playback from local and deployed frontend origins. A missing bucket CORS config presents as a failed preflight on the presigned R2 URL, even when Railway API CORS is correct.

## Working Assumptions

- Preserve the existing visual language on the landing page rather than replacing it with generic boilerplate.
- Check whether a route is still placeholder-level before doing large refactors; `/pricing` is skeletal, but `/dashboard` now has real orchestration behavior and should be treated as product code.
- This first dashboard slice is session-only by design: no project history, no list endpoints, no refresh resume, and no backend auth overhaul.
- Keep `/editor` out of scope unless the task explicitly asks for it.

## Verification Notes

- Run `npm run lint` and `npm run build` from `web/` after dashboard/frontend API changes.
- A live smoke test on 2026-04-25 confirmed Railway API health, API CORS, R2 upload preflight/PUT/complete, music analysis, video analysis, timeline planning, rendering, and final MP4 range download against `https://api-production-8fb8.up.railway.app`.
- The Codex in-app browser may not support signed-in Clerk flows. If browser automation is unavailable or cannot authenticate, validate the pipeline with direct API/R2 smoke tests and clearly call out that UI clickthrough was not exercised.
