# CLAUDE.md

This file gives Claude Code working context for Eclypte. The repo-wide agent guide is `AGENTS.md`; this file keeps the same architecture in a Claude-oriented, operational form.

## Project Summary

Eclypte is an AMV creator monorepo. The dashboard is a Next.js 16 frontend; the backend is a FastAPI control plane that schedules media work, persists artifacts in Cloudflare R2, and delegates heavy audio/video/render/index jobs to Modal. Optional Postgres stores run manifests/events/progress; optional Redis broadcasts realtime run updates to the dashboard.

Core invariants:

- Audio and video analysis payloads use `schema_version: 1`.
- Time fields use seconds and the `_sec` suffix. Do not leak frame indices into shared schemas.
- `RunManifest.outputs` keys are frontend contracts. Change them only with coordinated API and frontend updates.
- Export behavior belongs in `api/export_options.py`; do not reimplement format/trim/crop logic in pages, planners, adapters, or renderers.
- Browser audio uploads may be WAV or any common audio format (MP3/M4A/AAC/FLAC/OGG), auto-converted to WAV server-side; video uploads are MP4 only.

## Top-Level Layout

- `web/`: Next.js 16.2.3, React 19.2, TypeScript, App Router. `web/AGENTS.md` has frontend-specific warnings.
- `api/`: FastAPI app, workflow orchestration, storage substrate, YouTube downloader, and prototype media pipelines.
- `api/publishing.py`: review-gated Buffer publishing for Instagram Reels — Gen-Z-voiced OpenAI/fallback caption generation (the model is fed the source movie/anime + song names — resolved from the render's run lineage by `resolve_edit_source_names` and persisted on the post as `source_name`/`song_name` — and produces context-relevant AI hashtags), public R2 media copies, Buffer GraphQL payloads (declares the Instagram `reel` post type; the send modes are `queue`=`addToQueue`, `schedule`/`now`=`customScheduled` — `now` posts immediately via a server-computed near-future `dueAt` from `immediate_due_at`, since Buffer has no instant-publish mode and rejects past `dueAt`), channel diagnostics, and post-status refresh (`apply_buffer_status`) that marks a post `published` as soon as Buffer reports it sent (`sentAt`/sent status) and independently back-fills the permalink from `externalLink` when it appears.
- `api/storage/`: R2 object access, file manifests, file versions, upload reservations, run manifests/events/progress, prompt versions, references, publishing posts, Postgres run store, Redis broadcaster, staging helpers, and tests.
- `api/prototyping/music/`: the pure allin1 analyzer, its Modal app (`eclypte-analysis`), and synced-lyrics lookup. (YouTube/audio ingestion and R2 publishing now live in the control plane — `api/youtube_download.py` and `api/workflows.py`.)
- `api/prototyping/video/`: scene detection, optical-flow motion analysis, impact detection, local CPU and Modal GPU runtimes, R2-aware Modal wrapper.
- `api/prototyping/edit/`: CLIP index, OpenAI synthesis agent, reference consolidator, timeline schemas/validators, MoviePy renderer (MP4 + poster frame), Modal render/index wrappers.
- `api/COMMANDS.md`: command runbook. Prefer updating it when operational instructions change.
- `.agent/`, `.superpowers/`: agent/process assets, not runtime app code. (The old `docs/` plans/specs directory has been removed.)
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
- `ECLYPTE_INTERNAL_PROGRESS_URL` and `ECLYPTE_INTERNAL_PROGRESS_TOKEN`: let Modal workers post live render/analysis progress to `/internal/progress` (workers send `X-Eclypte-Internal-Token` matching the token). Without them, progress falls back to slower R2 event JSON. Keep server-side only.
- `ECLYPTE_YOUTUBE_COOKIES_B64` or `ECLYPTE_YOUTUBE_COOKIES`: cookies for the `yt-dlp` YouTube fallback.
- `ECLYPTE_YOUTUBE_VISITOR_DATA` and `ECLYPTE_YOUTUBE_PO_TOKEN`: PO-token path for `pytubefix`.
- `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`: enable review-gated Buffer Instagram publishing from public R2 copies. `ECLYPTE_BUFFER_POST_NOW_LEAD_SEC` (default 60) is the lead added to "now" the post's computed `dueAt` so Buffer accepts it (must be in the future) and publishes near-immediately.
- `OPENAI_API_KEY`: enables AI caption generation for publishing packages. `ECLYPTE_CAPTION_MODEL` is optional and defaults to a small GPT-5.4-class model; deterministic fallback captions are used when OpenAI is unavailable.
- `ECLYPTE_AUTOPILOT=1`: starts the in-process autopilot loop (FastAPI lifespan task) that ticks every `ECLYPTE_AUTOPILOT_INTERVAL_SEC` (default 300) for every user with autopilot enabled. Without it, ticks only run via `POST /v1/autopilot/tick`.

Routes:

- Health: `GET /healthz` — also reports non-secret booleans for YouTube cookies, realtime streaming (`REDIS_URL`), and Modal worker-progress configuration.
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/music/conversions` (transcode an uploaded non-WAV audio file into a WAV `song_audio` asset), `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer` (`mode`: `queue`/`schedule`/`now`), `POST /v1/publishing/posts/{post_id}/refresh-status`, `POST /v1/publishing/posts/{post_id}/mark-posted`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Autopilot: `GET /v1/autopilot`, `PATCH /v1/autopilot` (enable/disable, daily target, clear halt), `POST /v1/autopilot/queue`, `DELETE /v1/autopilot/queue/{item_id}`, `POST /v1/autopilot/tick` (manual tick). `api/autopilot.py` owns the review-gated tick state machine: it imports YouTube songs, starts cinematic 9:16 Reels edit jobs (`reels_cinematic`) with an energy-ranked ~20–30s trim window (≈25s target) from the song's music analysis (section-anchored windows begin `CHORUS_LEAD_IN_SEC`≈5s early so a chorus reel captures the build-in), dedupes (video, song, window) combos, halts after 3 consecutive failures, and auto-creates `ready` publishing packages (`auto_created=true`) that wait for human approval on the publish page. State lives in R2 at `users/{user_id}/autopilot/state.json` with enabled-user markers under `autopilot/enabled/`.
- Internal: `POST /internal/progress`, requiring `X-Eclypte-Internal-Token`.

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
- `render_poster`

`StorageRepository` is the API-facing facade. It writes file/upload metadata to the object store, routes run state through Postgres when configured or R2 JSON otherwise, and publishes Redis updates after durable writes. Redis failures must not break persistence.

Default asset lists hide archived assets, render outputs, and render posters. Use `kind=render_output` to list render outputs. Archive/restore instead of hard deletion for normal dashboard lifecycle.

## Workflow Orchestration

`api/workflows.py` defines `WorkflowRunner` and `DefaultWorkflowRunner`. Workflow endpoints create a `RunManifest` with `status="running"` and schedule FastAPI background work.

Important workflows:

- `run_music_analysis`: loads audio from R2, calls `eclypte-analysis::analyze_remote`, publishes a `music_analysis` asset.
- `run_youtube_song_import`: downloads/transcodes audio through `api/youtube_download.py`, records `youtube_download_attempt` events, publishes `song_audio`, then runs music analysis.
- `run_video_analysis`: calls `eclypte-video-r2::analyze_r2`, publishes `video_analysis`.
- `run_timeline_plan`: runs the OpenAI/CLIP agent planner and publishes `timeline`.
- `run_render`: calls `eclypte-render-r2::render_r2`, publishes a `render_output` MP4 and a `render_poster` JPEG thumbnail.
- `run_edit_pipeline`: parent workflow that selects saved assets, ensures missing analysis, plans, renders, and writes child run ids/output refs onto the parent run.
- `run_synthesis_reference_ingest`: downloads/analyzes reference AMVs and records metrics.
- `run_synthesis_consolidation`: consolidates queued/completed references into generated prompt guidance and prompt versions.

Edit child run ids and render output ids are part of the dashboard contract. Preserve keys such as `music_run_id`, `video_run_id`, `timeline_run_id`, `render_run_id`, `render_output_file_id`, `render_output_version_id`, `render_poster_file_id`, and `render_poster_version_id`.

## Export Options

`api/export_options.py` owns:

- `reels_9_16`: 1080x1920, fill crop, `crop_focus_x`.
- `reels_cinematic`: 1080x1920, letterbox — the full widescreen picture centered on a native vertical canvas with black bars baked in (autopilot's default).
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

The control plane wires the music flow (`api/workflows.py`: `run_music_analysis`, `run_youtube_song_import`) — ingestion via `api/youtube_download.py`, Modal analysis, lyrics, and R2 publishing; the `music/` package itself is just the pure analyzer, its Modal app, and `lyrics.py`. `lyrics.py` uses `syncedlyrics`; lyrics are optional and separate from `song_analysis.json`. Production sourcing: `search_synced_lyrics(query)` (synced LRC only) is called opportunistically during both analysis paths — `run_youtube_song_import` (query = video title) and `run_music_analysis` (query = song filename) — and `_publish_song_lyrics` stores a `lyrics` asset, recording `lyrics_file_id`/`lyrics_version_id` in the run outputs. Best-effort: a miss/error stores nothing and never fails the run. `syncedlyrics` is in root `requirements.txt` because the fetch runs on the control plane (Railway).

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
- `credits.py`: end-credit detection. `decide_content_end` (pure, unit-tested) finds the dense-text credits block by scanning per-frame OCR word counts backward from the end and returns a conservative `content_end_sec = credits_start − 30s` (with guardrails so mid-film text can't truncate the edit); `detect_content_end` does the tail decode + Tesseract OCR (imports cv2/pytesseract lazily; stays Modal-free like scenes/motion).

`analysis_cuda.py` is the GPU orchestrator. It decodes sequentially and resets previous-frame state at scene boundaries so optical flow does not cross cuts, then runs `credits.detect_content_end` and adds a `credits` block (`{detected, credits_start_sec, content_end_sec}`) to the `video_analysis` payload. Planning hard-caps the usable source to `content_end_sec`: `_run_agent_timeline_plan` passes it as the agent's source duration, into `adapt(content_end_sec=...)` (clamps every shot's source range), and filters CLIP `query_clips` results beyond it. Older analyses without `credits` fall back to full duration.

Modal apps:

- `api/prototyping/video/analysis_modal.py`: volume-based prototype app `eclypte-video`.
- `api/prototyping/video/storage_modal.py`: R2-aware API app `eclypte-video-r2`, function `analyze_r2`. Its image bundles `tesseract-ocr` + `pytesseract` (for credit OCR) and `add_local_python_source(... "credits" ...)`; redeploy `eclypte-video-r2` after changing `analysis_cuda.py`/`credits.py` (re-analyze a film to populate the new `credits` block).

OpenCV-CUDA has no friendly local wheel path. Keep CUDA/OpenCV build complexity inside Modal unless the task explicitly asks for dependency work.

## Edit Pipeline

`api/prototyping/edit/` takes song analysis, source analysis, audio, and video and produces a timeline or rendered MP4.

Subsystems:

- `patterns/`: pattern catalog and registry. Stable pattern ids are `<layer>.<slug>`.
- `knowledge/`: seed pattern YAML and generated/reference guidance markdown.
- `skills/`: registry of agent-placed creative overlay skills (text/masks) composited over the reel. Each skill is one self-contained module (`text.hook`, `text.caption`, `text.lower_third`, `mask.vignette`) declaring `id`, an agent-facing `description`, a Pydantic `params_model`, and `build_layers(overlay, ctx)`. Skills self-register on import (`register(...)`); the agent tool enum, validators, and renderer all read the registry (`skills.ids()` / `skills.get()` / `skills.agent_catalog()`), so adding/removing a skill is a single module plus one import line in `skills/__init__.py`. Skill metadata stays moviepy-free (Railway control plane); `build_layers` imports moviepy/numpy lazily and runs only inside the Modal renderer. (Synced-lyric burn-in overlays were removed — the on-screen text looked cluttered; the standalone `lyrics` asset is still fetched/stored but no longer rendered.)
- `synthesis/timeline_schema.py`: Pydantic timeline schema. `Timeline.overlays` carries optional `Overlay` items (`skill_id` + window + validated `params`), composited over the shots. `AudioSpec.fade_out_sec`/`OutputSpec.fade_out_sec` carry the end-of-reel fade lengths; the shared `tail_fade_for(duration_sec)` helper clamps the fade to ≤ ⅓ of the reel.
- `synthesis/validators.py`: contiguity, bounds, and pattern-id validation, plus registry-driven overlay checks (known `skill_id`, in-bounds window).
- `synthesis/agent.py`: OpenAI Responses API synthesis loop.
- `synthesis/adapter.py`: converts agent output into renderable timelines, dedupes near-duplicate source timestamps, trims song-duration overshoot, runs continuity post-processing, beat-snaps interior cut boundaries (±0.15s) onto `markers.beats_used_sec`, maps optional per-shot `transition_in`/`effect` choices, and resolves the agent's optional `overlays` against the skill registry (clamps the window, validates params, and drops invalid/unknown overlays with a log rather than failing the edit). It also sets the audio/video `fade_out_sec` via `tail_fade_for`. The agent now returns `{"shots", "overlays"}`.
- `index/frames.py`: sequential frame extraction. Do not revert to per-frame `CAP_PROP_POS_MSEC` seeking on long videos.
- `index/embed.py`: CLIP frame/text embeddings.
- `index/query.py`: `query_clips` (Modal CLIP proxy) and `rank_with_content_filter` (ranks CLIP results, dropping near-black/flat frames). Used by the agent path.
- `index/storage_modal.py`: R2-aware API CLIP app `eclypte-clip-index-r2`, with `build_index_r2` and `query_index_r2`. The build records per-frame `brightness`/`detail` in the index; `query_index_r2` ranks through `query.rank_with_content_filter`, which drops near-black and flat frames (black intros/outros, credits, title cards) so the agent can't select them. Bump `CLIP_INDEX_BUILD_STEP` in `api/workflows.py` (and reindex) when the index format changes; redeploy `eclypte-clip-index-r2` after changing this.
- `reference/`: reference AMV download, metrics, ingest, consolidation, and prompt-weight parsing.
- `render/renderer.py`: `render_timeline` is the entry point. It validates, then **dispatches** (via `can_render_with_ffmpeg`): a timeline using only cuts/crossfade with no overlays/effects renders through a single native ffmpeg filtergraph — ~17× faster on the same hardware because pixels never leave ffmpeg (MoviePy's ~97% overhead was the per-frame Python decode→numpy→pipe pump, not the x264 encode). Anything else (overlays, `flash`/`freeze`/`punch_in`) falls back to the MoviePy v2 path in the same file. The MoviePy path reads timeline JSON + media only, composites `timeline.overlays` over the concatenated shots before attaching audio, applies the end-of-reel audio fade-out + video fade-to-black (`render/fades.py`, via `clip.transform`), saves an RGB JPEG poster (after compositing, so overlays show), reports progress via proglog's `frame_index` bar, and resolves the overlay font via `ECLYPTE_OVERLAY_FONT` → `/fonts/overlay.otf` → bundled DejaVu.
- `render/ffmpeg_filtergraph.py`: **pure** builder — a validated `Timeline` → ffmpeg argv (per-shot seeked input → scale/letterbox-or-cover-crop → concat, with crossfades folded into chained `xfade` at cumulative offsets, audio trim/gain, the end-of-reel `afade` + video `fade` tail fade, and the same CRF 18 / `-tune animation` / yuv420p / 192k AAC encode). No subprocess/moviepy, so it is fully unit-tested (`test_ffmpeg_filtergraph.py`). `can_render_with_ffmpeg` lives here and gates the dispatch (Phase 1 = cuts/crossfade/whip, no overlays/effects).
- `render/ffmpeg_run.py`: runs that argv as one process, parses `-progress` into the same `progress_callback` 0–100 contract, then extracts the JPEG poster. Resolves the ffmpeg binary via PATH → `imageio_ffmpeg`.
- `render_storage_modal.py`: R2-aware API renderer `eclypte-render-r2` (uploads the rendered MP4 and the poster image). Its image already bundles `ffmpeg`; redeploy after changing the render package.

Agent planning defaults:

- Timeline planning is always the OpenAI/CLIP agent (there is no other mode).
- `synthesis/agent.py` currently uses `MODEL = "gpt-5.5"`, `reasoning_effort="high"`, and `verbosity="low"`.
- The baseline system prompt has ONE source of truth: `synthesis/system_prompt.py` (`SYSTEM_PROMPT`). `agent.py` imports it as its fallback; `workflows.py`/`app.py` import it as `DEFAULT_SYNTHESIS_PROMPT` (the default prompt-version text and the consolidation base). Edit the prompt only there — do not re-inline it.
- Responses API state is carried through `previous_response_id`; do not re-upload full message history each loop.
- Tools are `query_clips(query, top_k)` and `finish_edit(timeline)`; timeline items optionally carry `transition_in` (`cut`/`flash`/`crossfade`) and `effect` (`freeze`/`punch_in`).
- The agent receives the source duration and is instructed to span the full source start→end regardless of song length, so short/trimmed edits still cover the whole film. This guidance is injected into the per-run user content (so it applies regardless of the active prompt version); nothing enforces it (no validator/forced spread), preserving the agent's freedom to dwell on standout moments.
- The agent is instructed to never select black frames, solid colors, title cards, logos, or end credits, and to span the end of the *content* (not the trailing credits/black). The data-side filter is partial: `query_clips` results are content-filtered in the CLIP index by brightness/detail (see `index/storage_modal.py`), which drops black/flat frames but NOT credits text on a colored background (bright + has edge detail). So the prompt (`system_prompt.py` + the per-run source context in `agent.py`) is reinforced to treat any text-heavy frame as credits regardless of background color, and to pull the CLOSING shot's source timestamp back from the very end of the source. The durable cap is `content_end_sec` from credit OCR (which needs a present/up-to-date `credits` block — re-analyze older films).
- Agent mode may create/reuse `clip_index` assets and records `clip_index_file_id`, `clip_index_version_id`, and `synthesis_prompt_version_id`.
- Agent failures should fail visibly via `RunManifest.last_error`; there is no fallback planner.

Rendering notes:

- `render_timeline` depends on timeline JSON, source video, and song audio, and auto-dispatches between the native ffmpeg path and the MoviePy fallback (see above). The native path is verified frame-parity with MoviePy on the same timeline (deep-in-shot frames pixel-near-identical; deviations of ≤~1 frame only at cut boundaries / high motion, within the ±0.15s beat-snap tolerance).
- MoviePy v2 (fallback path) methods include `subclipped`, `with_duration`, `resized`, `concatenate_videoclips(method="compose")`, and `with_audio`.
- Implemented effects/transitions: `flash` and `crossfade` transitions, `freeze` and `punch_in` effects (frame transforms that preserve duration/size). `whip`, `speed_ramp`, and `hold` are still no-op stubs. The agent opts in per shot via optional `transition_in`/`effect` fields on `finish_edit` items, mapped in `synthesis/adapter.py`. On the native ffmpeg path, cuts/crossfade are supported; the per-frame effects and `flash` still route to MoviePy until ported (Phase 2 also brings overlays in as PNG composites).
- The adapter beat-snaps interior shot boundaries to the nearest beat within ±0.15s (`snap_shots_to_beats`), records them in `markers.beats_used_sec`, and never collapses a shot below 0.4s.
- Both render paths apply an end-of-reel tail fade (audio fade-out + video fade-to-black) over the reel's final seconds: native ffmpeg emits `afade`/`fade`; the MoviePy fallback uses `render/fades.py` (`audio_fade_out`/`video_fade_out` via `clip.transform`). Length comes from `timeline.audio.fade_out_sec`/`timeline.output.fade_out_sec`, set by the adapter through `tail_fade_for` (≤ ⅓ of the reel). The fade is just filters/transforms, so it does not push a cuts/crossfade timeline off the fast native path, and the mid-clip poster is unaffected.
- The encoder writes CRF 18 / `-tune animation` / yuv420p with 192k AAC so Instagram/YouTube re-encodes start from a high-quality source (identical flags on both paths).
- The native ffmpeg path encodes on CPU in seconds; a GPU/NVENC path is unnecessary for the common montage and is not worth the CUDA-ffmpeg image cost. The MoviePy fallback remains CPU-pump-bound (vCPU count barely helps it).
- Edit `progress_percent` is a weighted average by typical stage duration (`EDIT_STAGE_WEIGHTS` in `api/app.py`), and the render stage fills smoothly from the renderer's real encode progress. The dashboard shows the poster instantly and lazy-loads the heavy MP4 on play.

## Frontend

Before changing Next.js code, read relevant docs under `web/node_modules/next/dist/docs/`. This project uses Next.js 16, where conventions may differ from memory. The proxy/middleware file is `web/src/proxy.ts`, not `middleware.ts`.

Frontend architecture:

- `web/src/app/layout.tsx`: fonts and app shell providers.
- `web/src/app/page.tsx`: marketing landing page.
- `web/src/app/pricing/page.tsx`: marketing pricing page — three tiers (Free/Creator/Studio) + FAQ.
- `web/src/app/demo/page.tsx`: marketing "Screening Room" demo page. Poster-first lazy video via `web/src/components/demo/demoPlayer.tsx` (`DemoReel`/`DemoTile`); posters in `web/public/demo/posters/` and web-optimized 1080p sources in `web/public/demo/web/` (4K originals are unreferenced).
- `web/src/app/dashboard/layout.tsx`: dashboard shell/sidebar.
- `web/src/app/dashboard/page.tsx`: redirects to `/dashboard/new-edit`.
- `web/src/app/dashboard/new-edit/page.tsx`: compose/edit pipeline UI.
- `web/src/app/dashboard/assets/page.tsx`: upload/import/manage asset library (Sources/Derived/Hidden tabs + a Songs/Sources kind filter on the Sources tab; library paginates at 24/page).
- `web/src/app/dashboard/synthesis/page.tsx`: references and prompt management.
- `web/src/app/dashboard/publish/page.tsx`: Buffer publishing queue with setup diagnostics, render preview, caption editing/regeneration, queue/schedule actions, posted/error metadata, per-lane tab counts, live reconciliation that polls in-flight posts against Buffer (~25s interval + on tab refocus) so queued posts auto-advance to Posted and permalinks back-fill, and a manual "Refresh from Buffer" button that re-checks on demand and surfaces Buffer errors (the background poll swallows them). A failed Buffer lookup is recorded on the post and shown inline rather than failing the request, and a manual "Mark as posted" override moves a stuck queued/scheduled post to Posted when Buffer can't reconcile it (`POST .../mark-posted`).
- `web/src/app/dashboard/autopilot/page.tsx`: autopilot status (enable/pause, daily target, halt banner), backlog form (video asset + song asset or YouTube link + optional brief), queue/activity list, and a manual "Run tick now" action.
- `web/src/app/dashboard/renders/page.tsx`: render outputs and recent render runs.
- `web/src/app/dashboard/settings/page.tsx`: API/user/prompt/YouTube-cookie health plus realtime (Redis) and worker-progress status.
- `web/src/app/dashboard/dashboardCommon.tsx`: shared dashboard page wrapper, skeleton placeholders (`Skeleton`/`SkeletonList`), formatting helpers (`formatBytes`/`formatDate`/`kindLabel`/`humanizeLabel` — `kindLabel` and `StatusBadge` Title-case raw enum/kind strings so the UI shows `Song Audio`/`Completed` not `song_audio`/`completed`), client-side list pagination (`usePagination` + the `Pager` control used by every big dashboard list; pass a `resetKey` such as the active tab/filter to reset to page 1), the `errorMessage`/`isAbortError` error helpers, and `useAbortableLoad` — a no-cache loader hook (aborts the prior in-flight load, drops stale/aborted responses) still used by `/settings`; the data pages load through the `web/src/stores/` cache instead.
- `web/src/stores/`: a zustand stale-while-revalidate cache shared across dashboard pages — `dashboardStore.ts` (generic per-key resource cache, in-flight dedup, latest-wins), `useResource.ts` (the SWR hook → `{ data, isLoading, error, revalidate, set }`), and `dashboardResources.ts` (typed, user-scoped wrappers: `useAssets`, `useEditJobs`, `useRuns`, `usePublishingPosts`, `usePublishingConfig`, `useSynthesisReferences`, `useSynthesisPrompt`, `useAutopilot`). Keys are scoped by `EclypteApiClient.userId`; signed URLs are never cached. `web/src/stores/README.md` documents the design, page→resource map, and editing gotchas.
- `web/src/app/dashboard/useRunStream.ts`: shared hook that subscribes to `/v1/runs/stream` with a debounced refresh callback, a ~15s safety-poll watchdog that reconciles a connected-but-silent stream, and a 1s polling fallback when the stream fails; used by the new-edit, renders, and autopilot pages.
- `web/src/components/dashboard/sidebar/`: dashboard navigation.
- `web/src/services/eclypteApi.ts`: typed browser API client. Extend this before adding ad hoc fetch calls.

Run streams are newline-delimited JSON. Use `readJsonLineStream()` and `drainJsonLines()` from `eclypteApi.ts`; keep polling fallback logic because Redis may be absent or stale.

Dashboard data loading uses the `web/src/stores/` zustand SWR cache: route each page's primary list through a typed `useResource` wrapper, so navigation serves cached data instantly and revalidates in the background (TTL ~30s) with in-flight dedup and latest-wins. Mutations patch the cache via the hook's `set` (value or updater) instead of re-pulling the whole collection (archive/restore/delete patch the array in place); `useRunStream` and the publish Buffer-poll refreshers call `revalidate`. A fetch is deliberately not aborted on unmount — finishing it populates the shared cache (latest-wins + dedup keep it correct). Two non-obvious rules: the Publish package list uses the compact `.packageRow` layout because the 5-column `.assetRow` table only fits the wide panel; and the Synthesis prompt textarea is user-owned — a background revalidate must not overwrite unsaved edits (guarded by a last-seeded-value dirty check, `lastSeededRef`).

The frontend depends on these output keys:

- `music_analysis_file_id`, `music_analysis_version_id`
- `video_analysis_file_id`, `video_analysis_version_id`
- `timeline_file_id`, `timeline_version_id`
- `render_output_file_id`, `render_output_version_id`
- `render_poster_file_id`, `render_poster_version_id`
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

- `eclypte-video` (used in production by synthesis reference ingest via `analyze_remote_bytes`)

Modal wrappers should use pure local modules through `add_local_python_source()` or explicit storage wrappers. Pure analysis modules should not import Modal.

Shared wrapper helpers live at the `api/prototyping/` root: `modal_s3.py` (S3/R2 client + object download) and `progress_events.py` (progress emission). Import them by bare module name inside Modal function bodies, list them in each app's `add_local_python_source()`, and deploy from `api/prototyping/` so they resolve.

`add_local_python_source()` snapshots local code at `modal deploy` time. Pushing to Railway does NOT update Modal: after changing anything inside the bundled `edit` package that the renderer uses (`edit/render/**`, `edit/skills/**`, `edit/synthesis/timeline_schema.py`, `edit/synthesis/validators.py`), redeploy `eclypte-render-r2` or live renders keep running the old code (and may reject timelines that use newer schema values, or silently drop overlays whose skills the old image lacks). `eclypte-clip-index-r2` also bundles `edit` but only needs a redeploy when index code changes. On Windows, prefix `modal` commands with `PYTHONUTF8=1` (or `$env:PYTHONIOENCODING="utf-8"`) — the CLI prints Unicode glyphs that crash the default charmap console.

## Testing Guidance

- Backend behavior changes: run focused tests near the changed module, then `python -m pytest api -v` when feasible.
- API contract changes: run `python -m pytest api/test_api_v1.py -v` and update `web/src/services/eclypteApi.ts`.
- Storage changes: run `python -m pytest api/storage -v`.
- Publishing changes: run `python -m pytest api/test_publishing.py -v`.
- Export option changes: run `python -m pytest api/test_export_options.py -v`.
- Synthesis/index changes: run `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v`.
- Frontend changes: from `web/`, run `npm run lint` and `npm run build`.

`pytest.ini` disables pytest's cache provider and sets temp-path retention to zero to reduce `.pytest*` artifacts.

## Current Focus & Next Steps (June 2026)

The active push is Instagram Reels growth via autopilot: review-gated packages rendered as `reels_cinematic` (native 1080x1920, baked-in bars) from ~20–30s energy-ranked windows (≈25s, 5s chorus lead-in), agent-planned with beat-snapped cuts, real flash/crossfade/freeze/punch_in effects, an audio+video tail fade for a clean ending, and a CRF 18 encode. Captions name the source movie/anime + song with context-relevant AI hashtags.

Operational checklist:

- Confirm `ECLYPTE_AUTOPILOT=1` (and optionally `ECLYPTE_AUTOPILOT_INTERVAL_SEC`) is set on Railway; `/healthz` reports `autopilot_loop_configured`. Without it, ticks are manual.
- QA the first post-deploy package before approving to Buffer: native vertical canvas (no platform-added letterbox), cuts audibly on beats, hook lands inside ~1.5s, effects visible.
- Existing autopilot users keep their stored `daily_target`; the new default of 3 applies only to fresh state.

Deferred, in rough priority order:

- Impact-aligned shot selection: line up video-analysis impact moments with musical downbeats during planning.
- `whip` transition and `speed_ramp`/`hold` effects (still no-op stubs).
- YouTube publishing path (16:9 renders already exist; no upload integration).
- Retention experiment: the "span the full source" prompt rule turns a ~25s reel into a whole-film montage — once IG insights accumulate, test single-scene reels against it and revisit the rule.
- Per-shot crop focus for fill-mode reels; posting-time optimization stays in Buffer.

## Working Rules

- Prefer existing repository boundaries and helpers over new parallel abstractions.
- Keep storage, API, frontend client, and dashboard UI in sync when contracts change.
- Do not commit secrets, `.env` files, cookies, Modal tokens, or OpenAI keys.
- Do not install heavy ML stacks locally unless the task is explicitly dependency work.
- Keep `AGENTS.md`, `web/AGENTS.md`, `api/COMMANDS.md`, and this file reconciled when architecture or commands change.
- Preserve unrelated local changes. At the time this guide was refreshed, `README.md` already had local modifications and was intentionally left alone.
